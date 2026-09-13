# MDTXTRT — contrato v1

Estado: contrato registrado; implementação e validação pendentes.

## Resultado esperado

Bot Telegram e Mini App para importar Markdown (.md) e texto (.txt), editar,
visualizar e publicar conteúdo no destino autorizado. Conversão direta pelo bot
deve funcionar sem abrir a Mini App. Não reescrever o conteúdo do usuário.

## Interface

- Nome MDTXTRT, sem subtítulo técnico.
- Mobile-first Android/iPhone, tela cheia, controles nativos do Telegram.
- Fundo branco no claro, preto no escuro; destaque laranja; ícones SVG.
- Texto dominante; barra compacta e menus contextuais por categoria.
- Edição/prévia, importar, desfazer/refazer, localizar/substituir, versões.
- Adaptar viewport e áreas seguras; não encobrir cursor com teclado.
- Evitar zoom automático; manter acessibilidade e seleção de texto.

## Categorias funcionais

1. Formatação: texto, negrito, itálico, sublinhado, tachado, spoiler, marcado,
   subscrito, sobrescrito, limpar formatação e combinar estilos.
2. Estrutura: parágrafos, quebras, títulos, rodapé, divisor e direção da escrita.
3. Citações: simples, expansível, destacada e detalhes recolhíveis.
4. Listas: marcadores, numeração, tarefas, níveis e estado dos itens.
5. Código/matemática: inline, blocos, linguagem e fórmulas.
6. Links/referências: URL, e-mail, telefone, menções, hashtags, comandos,
   data/hora, emojis, âncoras e referências.
7. Tabelas: células, linhas, colunas, cabeçalho e modo compacto.
8. Mídia: imagem, vídeo, áudio, voz, animação, documento, legenda, créditos,
   colagem, slideshow e mapa.
9. Interação: botões integrados e teclado inline, tratados separadamente.
10. Arquivos e histórico: importar/exportar, copiar/colar, rascunhos e versões.
11. Publicação: enviar/editar, destino autorizado e erros recuperáveis.

## Comandos

| Comando | Comportamento |
| --- | --- |
| /start | Apresentação concisa e rich |
| /help | Ajuda com exemplos estruturados |
| /importar | Receber .md/.txt e responder convertido |
| /converter | Converter texto enviado ou mensagem respondida |
| /editor | Oferecer entrada na Mini App |
| /formatos | Demonstrar recursos realmente implementados |
| /cancelar | Encerrar operação pendente, sem botão |

Todos exceto /cancelar: botão integrado verde com texto "Entrar no MDTXTRT".
O estilo é nativo do cliente, não uma garantia de tonalidade hexadecimal.
Separar resultado do usuário de mensagens operacionais do bot.
/cancelar não deve afirmar que nada foi publicado se uma operação já concluiu.

## Renderização

Modelo semântico compartilhado pelo editor, conversor e prévia.
Três alternativas: Rich Message, HTML Telegram e MarkdownV2.
Não simular silenciosamente recursos sem equivalente. HTML comum não é HTML
Telegram; Markdown comum não é MarkdownV2. TXT preserva conteúdo literal.
Verificar suporte oficial e schemas antes de implementar qualquer campo.

## Publicação e segurança

Validar initData no servidor e não confiar em chat_id enviado pelo navegador.
A forma de abertura da Mini App define o fluxo permitido de publicação.
Token somente no servidor/segredos Railway, nunca no frontend, Git ou logs.
Arquivos e mídias devem ter limites, validação e política explícita de retenção.
Rascunhos e versões devem ficar isolados por usuário.

## Entrega

Implementar, testar e registrar evidências por função. Não afirmar ausência
absoluta de erros. Testes móveis reais permanecem distintos de simulações.
Histórico Git preservado; issue e PR completos; nunca fazer merge automático.

## Infraestrutura autorizada

- GitHub: romastefale/MarkdownTextRichText
- Branch: feat/mdtxtrt-implementation
- Issue: https://github.com/romastefale/MarkdownTextRichText/issues/1
- Railway: MarkdownTextRichText, 19b2c24f-d78f-466e-8da1-d51f5fc41606
- Environment: production, 8a67ddf0-060f-4b1e-a07d-b226ab2152ae
- Create State: 048473bb-637b-4f45-8b12-4ad9cdc83713

## Cronologia

2026-09-13: repositório inicial inspecionado (README, commit 28b2d8c).
Projeto Railway exclusivo criado; sem serviço ou deployment.
Create State conectado e contrato registrado. Branch e issue iniciadas.
Esta versão não contém ainda o aplicativo executável.
