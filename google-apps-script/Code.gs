/** Monitor de leilões: API de ingestão, fila de alertas e dashboard autenticado. */

const REQUIRED_SHEETS = [
  'buscas', 'estados', 'custos', 'notificacoes', 'resultados',
  'alertas', 'relatorios', 'configuracoes', 'execucoes',
];
const ALLOWED_LOT_HOSTS = ['www.copart.com.br', 'copart.com.br'];

function doGet() {
  // O dashboard é servido pelo Apps Script autenticado; a API de ingestão usa somente POST.
  return HtmlService.createHtmlOutputFromFile('Dashboard')
    .setTitle('Monitor de Leilões');
}

function doPost(e) {
  try {
    const body = JSON.parse(e.postData && e.postData.contents || '{}');
    assertApiKey_(body.key);
    const ss = SpreadsheetApp.getActive();
    assertSheets_(ss);
    switch (body.action) {
      case 'config':
        return json_({
          buscas: objects_(ss, 'buscas').filter(active_),
          estados: objects_(ss, 'estados'),
          custos: objects_(ss, 'custos'),
          notificacoes: objects_(ss, 'notificacoes').filter(active_),
          configuracoes: settings_(ss),
        });
      case 'sync_results':
        return json_(syncResults_(ss, Array.isArray(body.resultados) ? body.resultados : []));
      case 'run_log':
        appendObject_(ss.getSheetByName('execucoes'), body.evento || {});
        return json_({ok: true});
      case 'daily_summary':
        return json_(createDailySummary_(ss));
      default:
        return json_({error: 'acao_invalida'});
    }
  } catch (error) {
    console.error(error && error.stack || error);
    return json_({error: String(error && error.message || error)});
  }
}

function syncResults_(ss, received) {
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const resultSheet = ss.getSheetByName('resultados');
    const existing = objects_(ss, 'resultados');
    const index = new Map(existing.map((row, offset) => [resultKey_(row), {row, number: offset + 2}]));
    let created = 0;
    let updated = 0;
    const changedRows = [];
    received.forEach(raw => {
      const incoming = sanitizeResult_(raw);
      const key = resultKey_(incoming);
      if (!key || key.endsWith('|')) throw new Error('Resultado sem site ou lote');
      const current = index.get(key);
      if (!current) {
        incoming.resultado_id = Utilities.getUuid();
        incoming.primeira_captura_em = incoming.capturado_em || new Date().toISOString();
        incoming.ultima_captura_em = incoming.capturado_em || new Date().toISOString();
        incoming.notificado = 0;
        appendObject_(resultSheet, incoming);
        created += 1;
        changedRows.push(incoming);
        index.set(key, {row: incoming, number: resultSheet.getLastRow()});
      } else {
        const merged = Object.assign({}, current.row, incoming, {
          resultado_id: current.row.resultado_id,
          primeira_captura_em: current.row.primeira_captura_em,
          ultima_captura_em: incoming.capturado_em || new Date().toISOString(),
          busca_ids: mergeValues_(current.row.busca_ids, incoming.busca_ids),
        });
        if (meaningfulChange_(current.row, merged)) {
          writeObject_(resultSheet, current.number, merged);
          updated += 1;
          changedRows.push(merged);
        }
      }
    });
    enqueueAlerts_(ss, changedRows);
    const deliveries = processPendingAlerts_(ss);
    processPendingReports_(ss);
    return {ok: true, recebidos: received.length, novos: created, atualizados: updated, alertas: deliveries};
  } finally {
    lock.releaseLock();
  }
}

function createDailySummary_(ss) {
  const timezone = settings_(ss).fuso_horario || 'America/Sao_Paulo';
  const referenceDate = Utilities.formatDate(new Date(), timezone, 'yyyy-MM-dd');
  const results = objects_(ss, 'resultados')
    .filter(row => row.classificacao === 'PRIORITÁRIA')
    .filter(row => isWithinLastDay_(row.ultima_captura_em))
    .sort((a, b) => Number(b.pontuacao || 0) - Number(a.pontuacao || 0))
    .slice(0, 20);
  const content = results.length
    ? 'Relatório diário — ' + referenceDate + '\n\n' + results.map(summaryLine_).join('\n\n')
    : 'Relatório diário — ' + referenceDate + '\n\nNenhuma oportunidade prioritária foi capturada nas últimas 24 horas.';
  const reportSheet = ss.getSheetByName('relatorios');
  const existing = new Set(objects_(ss, 'relatorios').map(row => row.data_referencia + '|' + row.canal + '|' + row.destino));
  objects_(ss, 'notificacoes').filter(row => active_(row) && active_(row.resumo_diario)).forEach(notification => {
    const key = referenceDate + '|' + notification.tipo + '|' + notification.destino;
    if (existing.has(key)) return;
    appendObject_(reportSheet, {
      relatorio_id: Utilities.getUuid(), data_referencia: referenceDate, canal: notification.tipo,
      destino: notification.destino, status: 'pendente', tentativas: 0, ultimo_erro: '',
      criado_em: new Date().toISOString(), ultima_tentativa_em: '', enviado_em: '',
      conteudo: content, quantidade_oportunidades: results.length,
    });
  });
  return {ok: true, data_referencia: referenceDate, oportunidades: results.length, enviados: processPendingReports_(ss)};
}

function processPendingReports_(ss) {
  const reportSheet = ss.getSheetByName('relatorios');
  const notifications = new Map(objects_(ss, 'notificacoes').map(row => [row.tipo + '|' + row.destino, row]));
  let sent = 0;
  objects_(ss, 'relatorios').forEach((report, offset) => {
    const notification = notifications.get(report.canal + '|' + report.destino);
    const maxAttempts = Number(notification && notification.tentativas_maximas || 3);
    if (report.status === 'enviado' || Number(report.tentativas || 0) >= maxAttempts || !notification || !active_(notification)) return;
    report.tentativas = Number(report.tentativas || 0) + 1;
    report.ultima_tentativa_em = new Date().toISOString();
    try {
      sendReport_(report.canal, report.destino, report.data_referencia, report.conteudo);
      report.status = 'enviado';
      report.enviado_em = new Date().toISOString();
      report.ultimo_erro = '';
      sent += 1;
    } catch (error) {
      report.status = 'pendente';
      report.ultimo_erro = String(error && error.message || error).slice(0, 500);
    }
    writeObject_(reportSheet, offset + 2, report);
  });
  return sent;
}

function sendReport_(channel, destination, referenceDate, content) {
  if (channel === 'email') {
    MailApp.sendEmail(destination, '[Leilão] Relatório diário ' + referenceDate, content);
    return;
  }
  if (channel === 'telegram') {
    const token = getProperty_('TELEGRAM_BOT_TOKEN');
    if (!token) throw new Error('TELEGRAM_BOT_TOKEN não configurado nas propriedades do script');
    const response = UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/sendMessage', {
      method: 'post', contentType: 'application/json', payload: JSON.stringify({chat_id: destination, text: content}), muteHttpExceptions: true,
    });
    if (response.getResponseCode() < 200 || response.getResponseCode() >= 300) throw new Error('Telegram HTTP ' + response.getResponseCode());
    return;
  }
  throw new Error('Canal de relatório não suportado: ' + channel);
}

function sanitizeResult_(raw) {
  const allowed = [
    'site', 'lote', 'busca_ids', 'status_lote', 'titulo', 'marca', 'modelo', 'ano', 'km', 'cidade', 'uf',
    'patio', 'condicao_fisica', 'procedencia', 'documento', 'categoria', 'data_leilao', 'tipo_preco',
    'lance_atual', 'preco_revenda_referencia', 'valor_referencia_tipo', 'custo_total_estimado',
    'margem_estimada', 'margem_estimada_percentual', 'pontuacao', 'classificacao', 'pendencias',
    'detalhe_custos', 'link', 'capturado_em',
  ];
  const result = {};
  allowed.forEach(key => result[key] = raw[key] == null ? '' : String(raw[key]));
  if (typeof raw.detalhe_custos === 'object') result.detalhe_custos = JSON.stringify(raw.detalhe_custos);
  result.site = result.site.toLowerCase().trim();
  result.lote = result.lote.trim();
  result.link = safeUrl_(result.link);
  return result;
}

function enqueueAlerts_(ss, rows) {
  const notifications = objects_(ss, 'notificacoes').filter(row => active_(row) && active_(row.alerta_imediato));
  const alertSheet = ss.getSheetByName('alertas');
  const existing = new Set(objects_(ss, 'alertas').map(row => `${row.resultado_id}|${row.canal}|${row.destino}|${row.tipo_evento}`));
  rows.forEach(result => notifications.forEach(notification => {
    const minimum = Number(notification.pontuacao_minima || 0);
    if (Number(result.pontuacao || 0) < minimum || result.classificacao !== 'PRIORITÁRIA') return;
    const key = `${result.resultado_id}|${notification.tipo}|${notification.destino}|nova_oportunidade`;
    if (existing.has(key)) return;
    appendObject_(alertSheet, {
      alerta_id: Utilities.getUuid(), resultado_id: result.resultado_id, canal: notification.tipo,
      destino: notification.destino, tipo_evento: 'nova_oportunidade', status: 'pendente', tentativas: 0,
      ultimo_erro: '', criado_em: new Date().toISOString(), ultima_tentativa_em: '', enviado_em: '',
    });
    existing.add(key);
  }));
}

function processPendingAlerts_(ss) {
  const alertSheet = ss.getSheetByName('alertas');
  const alerts = objects_(ss, 'alertas');
  const results = new Map(objects_(ss, 'resultados').map(row => [row.resultado_id, row]));
  const notifications = new Map(objects_(ss, 'notificacoes').map(row => [`${row.tipo}|${row.destino}`, row]));
  let sent = 0;
  alerts.forEach((alert, offset) => {
    const notification = notifications.get(`${alert.canal}|${alert.destino}`);
    const maxAttempts = Number(notification && notification.tentativas_maximas || 3);
    if (alert.status === 'enviado' || Number(alert.tentativas || 0) >= maxAttempts) return;
    const result = results.get(alert.resultado_id);
    if (!result || !notification || !active_(notification)) return;
    alert.tentativas = Number(alert.tentativas || 0) + 1;
    alert.ultima_tentativa_em = new Date().toISOString();
    try {
      sendAlert_(alert, result);
      alert.status = 'enviado';
      alert.enviado_em = new Date().toISOString();
      alert.ultimo_erro = '';
      markResultNotified_(ss.getSheetByName('resultados'), result.resultado_id);
      sent += 1;
    } catch (error) {
      alert.status = 'pendente';
      alert.ultimo_erro = String(error && error.message || error).slice(0, 500);
      console.error(`Alerta ${alert.alerta_id}: ${alert.ultimo_erro}`);
    }
    writeObject_(alertSheet, offset + 2, alert);
  });
  return sent;
}

function retryPendingAlerts() {
  const ss = SpreadsheetApp.getActive();
  assertSheets_(ss);
  return processPendingAlerts_(ss);
}

function sendAlert_(alert, result) {
  const text = [
    `Oportunidade ${result.classificacao} | nota ${result.pontuacao}`,
    result.titulo, `Lote ${result.lote} | ${result.uf || 'UF não informada'}`,
    `Lance observado: ${result.lance_atual || 'não informado'}`,
    `Custo total estimado: ${result.custo_total_estimado || 'pendente'}`,
    `Margem estimada: ${result.margem_estimada_percentual || 'pendente'}%`, result.link,
  ].filter(Boolean).join('\n');
  if (alert.canal === 'email') {
    MailApp.sendEmail(alert.destino, `[Leilão] ${result.titulo}`, text);
    return;
  }
  if (alert.canal === 'telegram') {
    const token = getProperty_('TELEGRAM_BOT_TOKEN');
    if (!token) throw new Error('TELEGRAM_BOT_TOKEN não configurado nas propriedades do script');
    const response = UrlFetchApp.fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: 'post', contentType: 'application/json', payload: JSON.stringify({chat_id: alert.destino, text}), muteHttpExceptions: true,
    });
    if (response.getResponseCode() < 200 || response.getResponseCode() >= 300) throw new Error(`Telegram HTTP ${response.getResponseCode()}`);
    return;
  }
  throw new Error(`Canal de alerta não suportado: ${alert.canal}`);
}

function getDashboardData() {
  const ss = SpreadsheetApp.getActive();
  assertSheets_(ss);
  return objects_(ss, 'resultados').map(row => ({
    titulo: row.titulo, lote: row.lote, site: row.site, uf: row.uf, cidade: row.cidade,
    lance_atual: row.lance_atual, custo_total_estimado: row.custo_total_estimado,
    margem_estimada_percentual: row.margem_estimada_percentual, pontuacao: row.pontuacao,
    classificacao: row.classificacao, pendencias: row.pendencias, link: safeUrl_(row.link),
    ultima_captura_em: row.ultima_captura_em,
  }));
}

function assertApiKey_(provided) {
  const expected = getProperty_('MONITOR_API_KEY');
  if (!expected || !provided || provided !== expected) throw new Error('unauthorized');
}

function getProperty_(name) { return PropertiesService.getScriptProperties().getProperty(name); }
function active_(row) { return ['1', 'true', 'sim', 'ativo'].includes(String(row.ativo).trim().toLowerCase()); }
function resultKey_(row) { return `${String(row.site || '').toLowerCase().trim()}|${String(row.lote || '').trim()}`; }
function mergeValues_(a, b) { return [...new Set(`${a || ''},${b || ''}`.split(',').map(x => x.trim()).filter(Boolean))].join(','); }
function meaningfulChange_(before, after) {
  return ['lance_atual', 'status_lote', 'classificacao', 'pontuacao', 'custo_total_estimado', 'pendencias', 'link'].some(key => String(before[key] || '') !== String(after[key] || ''));
}
function safeUrl_(value) {
  const url = String(value || '').trim();
  const match = url.match(/^https:\/\/([^/]+)(?:\/|$)/i);
  return match && ALLOWED_LOT_HOSTS.indexOf(match[1].toLowerCase()) >= 0 ? url : '';
}
function settings_(ss) { return Object.fromEntries(objects_(ss, 'configuracoes').map(row => [row.chave, row.valor])); }
function isWithinLastDay_(value) {
  const time = new Date(value).getTime();
  return Number.isFinite(time) && time >= Date.now() - 24 * 60 * 60 * 1000;
}
function summaryLine_(row) {
  return [row.titulo + ' | nota ' + row.pontuacao, 'Lance: ' + (row.lance_atual || 'não informado'),
    'Custo estimado: ' + (row.custo_total_estimado || 'pendente'), row.link].filter(Boolean).join('\n');
}
function objects_(ss, name) {
  const values = ss.getSheetByName(name).getDataRange().getDisplayValues();
  const headers = values.shift().map(header => header.trim());
  return values.filter(row => row.some(cell => cell !== '')).map(row => Object.fromEntries(headers.map((header, i) => [header, row[i] || ''])));
}
function appendObject_(sheet, object) {
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getDisplayValues()[0];
  sheet.appendRow(headers.map(header => object[header] == null ? '' : object[header]));
}
function writeObject_(sheet, row, object) {
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getDisplayValues()[0];
  sheet.getRange(row, 1, 1, headers.length).setValues([headers.map(header => object[header] == null ? '' : object[header])]);
}
function markResultNotified_(sheet, resultId) {
  const rows = objects_(SpreadsheetApp.getActive(), 'resultados');
  const position = rows.findIndex(row => row.resultado_id === resultId);
  if (position >= 0) writeObject_(sheet, position + 2, Object.assign({}, rows[position], {notificado: 1}));
}
function assertSheets_(ss) {
  const missing = REQUIRED_SHEETS.filter(name => !ss.getSheetByName(name));
  if (missing.length) throw new Error(`Abas ausentes: ${missing.join(', ')}`);
}
function json_(payload) { return ContentService.createTextOutput(JSON.stringify(payload)).setMimeType(ContentService.MimeType.JSON); }
