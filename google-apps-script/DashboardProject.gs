/**
 * Projeto Apps Script separado para o painel.
 * Implante este projeto com acesso restrito à sua conta Google.
 * Propriedade obrigatória: SHEET_ID.
 */
const DASHBOARD_ALLOWED_HOSTS = ['www.copart.com.br', 'copart.com.br'];

function doGet() {
  return HtmlService.createHtmlOutputFromFile('Dashboard').setTitle('Monitor de Leilões');
}

function getDashboardData() {
  const sheetId = PropertiesService.getScriptProperties().getProperty('SHEET_ID');
  if (!sheetId) throw new Error('SHEET_ID não configurado no projeto do dashboard');
  const ss = SpreadsheetApp.openById(sheetId);
  const sheet = ss.getSheetByName('resultados');
  if (!sheet) throw new Error('Aba resultados ausente');
  const values = sheet.getDataRange().getDisplayValues();
  const headers = values.shift().map(header => header.trim());
  return values.filter(row => row.some(cell => cell !== '')).map(row => {
    const item = Object.fromEntries(headers.map((header, index) => [header, row[index] || '']));
    return {
      titulo: item.titulo, lote: item.lote, site: item.site, uf: item.uf, cidade: item.cidade,
      lance_atual: item.lance_atual, custo_total_estimado: item.custo_total_estimado,
      margem_estimada_percentual: item.margem_estimada_percentual, pontuacao: item.pontuacao,
      classificacao: item.classificacao, pendencias: item.pendencias, link: safeDashboardUrl_(item.link),
      ultima_captura_em: item.ultima_captura_em,
    };
  });
}

function safeDashboardUrl_(value) {
  const url = String(value || '').trim();
  const match = url.match(/^https:\/\/([^/]+)(?:\/|$)/i);
  return match && DASHBOARD_ALLOWED_HOSTS.indexOf(match[1].toLowerCase()) >= 0 ? url : '';
}
