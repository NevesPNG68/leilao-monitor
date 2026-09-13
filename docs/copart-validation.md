# Validação da Copart

## Fonte escolhida

Listagem pública inicial: `https://www.copart.com.br/quickpick/financiamento/?displayStr=Financiamento&from=popularSearch&page=1`.

Ela é adequada para o piloto porque a página oficial informa lote, ano, marca/modelo, categoria, condição, FIPE, pátio, data do leilão e lance/preço em sua listagem.

## Evidência de validação em 13/09/2026

Em Playwright, a URL respondeu HTTP 200 sem login ou CAPTCHA e exibiu 1.409 registros. A tabela de resultados continha 20 lotes na primeira página, com cabeçalhos Código, Ano Modelo, Marca, Modelo, Documento, Categoria, Condição, Valor FIPE, Pátio Veículo, Data do Leilão, Pátio do Leilão, Lote/Vaga e Lance Atual.

O adapter localiza essa tabela pelos cabeçalhos, não por classes CSS frágeis. Cada linha tinha 16 células; o Código e o primeiro link para o lote formam a identidade estável. A paginação expõe o link Próximo.

Documento NORMAL é uma condição documental. Condição FINANCIAMENTO é a procedência. Nenhum dos dois é tratado como confirmação de que o veículo não foi batido; essa informação fica pendente até existir fonte verificável no lote.

Por isso, o modelo inicial exige a condição física NAO BATIDO, mas a listagem atual ainda não fornece essa evidência. Esses lotes ficam como PENDENTE DE DADOS e não recebem alerta prioritário até que o adaptador valide a descrição/fotos ou outra fonte permitida.

## Itens obrigatórios antes de extrair lotes

1. Verificar termos de uso, robots e eventual permissão de automação.
2. Executar a URL em Playwright e guardar a URL final, título e evidências de login/CAPTCHA.
3. Inspecionar a estrutura entregue ao navegador e registrar seletores para cabeçalho, linhas, link, paginação e estado do lote.
4. Testar duas páginas e confirmar que o identificador do lote é estável.
5. Comparar uma amostra extraída com a tela, incluindo preço, condição, UF e link.
6. Implementar espera limitada, retentativas e encerramento seguro em bloqueios.
