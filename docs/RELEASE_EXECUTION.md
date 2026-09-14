# MDTXTRT — árvore de lançamento oficial

Branch de execução: `feat/mdtxtrt-official-release`.

Esta árvore parte de `feat/mdtxtrt-implementation` no commit `18e2b5194d0b3b952091344d1e7317e6b78fe4d4`. A árvore de implementação original permanece preservada. Não fazer merge automático.

## Nove etapas eficazes

1. **Contrato e diferença atual** — usar #1 e #4 como contrato executável; não promover evidência por inferência.
2. **Núcleo** — preservar o documento semântico, importação, histórico e recuperação que já estão materializados; corrigir somente divergências comprovadas.
3. **Renderização e prévia** — distinguir Rich Message (`blocks`, Rich Markdown, Rich HTML) dos fallbacks tradicionais (HTML e MarkdownV2); prévia deve consultar o mesmo classificador usado no envio.
4. **Bot, backend e segurança** — sete comandos, `waiting_text`, `initData`, `destination_id`, publicação e `message_id`.
5. **Mini App móvel** — accent laranja, H1/H2/H3, controles nativos, safe areas, viewport estável, teclado e botão inferior nativo.
6. **Integração interna** — CI deve importar tipos reais do aiogram, validar renderizadores, handlers, JS e `/health` sem credenciais externas.
7. **Railway** — build, startup, domínio, `/health` e credenciais reais. Falha anterior ao build não é classificada automaticamente como erro da aplicação.
8. **E2E + QA móvel** — sessão Telegram real, destino autorizado, envio real, `message_id` confirmado e clientes móveis reais.
9. **Release gate** — somente liberar quando a evidência própria de cada etapa exigida estiver presente; sem merge automático.

## Alterações desta árvore

- UI de release separada do checkpoint anterior (`release.js`/`release.css`), mantendo o histórico anterior intacto.
- H1/H2/H3 distintos.
- accent laranja e shell próprio reduzido à barra documental; controles de navegação/configuração/envio usam APIs nativas quando disponíveis.
- safe area, content safe area e viewport estável usados na composição móvel.
- prévia consulta `/api/conversion/review`, o mesmo classificador consumido pelo envio.
- envio da Mini App envia `destination_id` e `format`; nunca envia `chat_id` arbitrário.
- `/converter` isolado passa a consumir a próxima mensagem textual por handler pendente.
- `/formatos` cria blocos Rich reais.
- botão global usa `RichMessageButton(style="success")` quando Rich Message é apropriada, com fallback de teclado inline para respostas tradicionais.
- fallbacks Telegram HTML e MarkdownV2 tradicionais são separados dos três campos de `InputRichMessage`.

## Evidência permitida

- `materializado`: arquivo/commit presente;
- `verificado mecanicamente`: workflow/compilação/hash/sintaxe;
- `integrado`: módulos executados em conjunto e healthcheck local/CI;
- `deploy validado`: Railway constrói, inicia e responde externamente;
- `E2E validado`: Telegram real produz o efeito externo esperado;
- `QA móvel validado`: comportamento observado em cliente móvel real.

Nenhum estado implica automaticamente o seguinte.
