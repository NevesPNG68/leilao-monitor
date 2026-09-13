# Monitor de oportunidades em leilões

Monitor para compra e revenda rápida de veículos. A operação começa pela Copart e mantém cada leiloeiro isolado, para que novos adaptadores não alterem regras de cálculo ou dados existentes.

## Estado atual

- A planilha é a fonte dos critérios, UFs, cidades, pátios, custos, destinos e resultados.
- O cálculo considera lance observado, comissão, frete, documentação/regularização e reserva de reparos. Cada custo registra a origem e se é estimativa.
- O resultado recebe uma classificação: `PRIORITÁRIA`, `EM ANÁLISE`, `PENDENTE DE DADOS` ou `FORA DOS CRITÉRIOS`.
- O Apps Script faz atualização idempotente por `site + lote`, registra cada alerta e mantém tentativas em caso de falha.
- A execução diária é 09:30 em `America/Sao_Paulo`. O GitHub pode atrasar execuções agendadas; o histórico de execuções permite identificar isso.
- A listagem pública da Copart foi validada em Playwright, incluindo tabela, identidade do lote e paginação. A validação de termos e de campos que confirmem o estado físico do veículo continua pendente.

## Planilha

Crie uma planilha e importe, em abas com os nomes exatos, todos os CSVs em [`sheets-templates`](sheets-templates):

`buscas`, `estados`, `custos`, `notificacoes`, `resultados`, `alertas`, `relatorios`, `configuracoes` e `execucoes`.

O exemplo em `buscas` usa a listagem oficial de financiamento da Copart. Começa com Brasil inteiro e teto de R$ 70.000 de custo total. Para restringir UFs, defina `modo_estados` como `selecionados` e altere `ativo` em `estados`; cidades e pátios também aceitam listas separadas por vírgula. Não é necessário mudar código.

`preco_revenda_referencia` é uma referência editável, não uma FIPE automática. Sem ela, a margem permanece pendente em vez de ser inventada.

## Apps Script e painel privado

1. Abra **Extensões → Apps Script** dentro da planilha e cole [`google-apps-script/Code.gs`](google-apps-script/Code.gs). Esse é o projeto da API.
2. Em **Propriedades do script**, crie `MONITOR_API_KEY` com uma chave aleatória longa. Para Telegram, crie também `TELEGRAM_BOT_TOKEN`.
3. Implante a API como **Aplicativo da Web**, executando como você e permitindo acesso público. A API não expõe dados por GET; aceita somente POST com a chave no corpo. Copie a URL `/exec` para o secret do GitHub.
4. Crie um segundo projeto Apps Script, cole [`google-apps-script/DashboardProject.gs`](google-apps-script/DashboardProject.gs) e [`google-apps-script/Dashboard.html`](google-apps-script/Dashboard.html).
5. No segundo projeto, crie a propriedade `SHEET_ID` com o ID da planilha. Implante o painel como Aplicativo da Web com acesso restrito à sua conta Google.

Essa separação permite que o GitHub Actions envie dados sem tornar o painel público. A página em `dashboard/` é somente uma página pública de orientação no GitHub Pages, sem dados operacionais e sem segredos.

## GitHub Actions

Crie um repositório Git e trabalhe em uma branch de teste antes de enviar a `main`. Em **Settings → Secrets and variables → Actions**, cadastre:

- `SHEETS_WEBAPP_URL`: URL `/exec` do Apps Script;
- `SHEETS_API_KEY`: o mesmo valor de `MONITOR_API_KEY`.

O workflow [`daily-auction-check.yml`](.github/workflows/daily-auction-check.yml) roda diariamente às 09:30 de Brasília e também pode ser disparado manualmente. Para alertas mais rápidos, aumente a cadência depois de validar a permissão operacional e os limites da Copart; o alerta imediato é enviado na mesma execução que detectar o lote.

Em **Settings → Pages**, escolha **GitHub Actions** como fonte. O workflow [`deploy-dashboard.yml`](.github/workflows/deploy-dashboard.yml) publica apenas o conteúdo seguro de `dashboard/`.

## Telegram e e-mail

Na aba `notificacoes`, preencha o e-mail ou `chat_id` do Telegram. Use `pontuacao_minima` para evitar alertas sem qualidade. O Apps Script cria uma linha em `alertas` antes de enviar e registra o resumo diário em `relatorios`. Se falhar, registra `ultimo_erro` e tenta de novo em execuções posteriores, até `tentativas_maximas`.

## Validação da Copart

A URL inicial é:

`https://www.copart.com.br/quickpick/financiamento/?displayStr=Financiamento&from=popularSearch&page=1`

A rotina verifica se a página é realmente uma listagem e se apresenta CAPTCHA. Se houver bloqueio, ela apenas registra o incidente; não contorna mecanismos de acesso. A evidência da estrutura e da paginação está em `docs/copart-validation.md`.

## Verificação local e contínua

```powershell
python -m unittest discover -s tests -v
```

O GitHub Actions executa esses testes antes da coleta. Os testes cobrem conversão monetária, custo total, ausência de lance e restrição de UF.
