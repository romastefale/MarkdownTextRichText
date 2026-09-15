# Implementação x verificação

Este documento separa estados que não podem ser tratados como equivalentes.

## Níveis de evidência

1. **Materializado** — o código ou artefato está presente na branch.
2. **Verificado mecanicamente** — sintaxe, manifesto, hashes, estrutura ou checagens estáticas passaram.
3. **Integrado** — os componentes envolvidos foram executados em conjunto no mesmo fluxo.
4. **E2E validado** — o fluxo real foi observado do ponto de entrada até o efeito externo esperado.
5. **QA móvel validado** — o comportamento foi observado em clientes/dispositivos móveis reais compatíveis.
6. **Deploy validado** — build, startup, healthcheck e serviço externo ficaram operacionais com configuração real.

Um nível não implica automaticamente o seguinte.

## Estado atual — 2026-09-15

### Materializado, verificado mecanicamente e integrado localmente

- checkpoint `2026-09-13-v2` materializado na branch `feat/mdtxtrt-implementation`;
- modelo semântico e renderizadores presentes;
- sete comandos presentes;
- Mini App, importação e prévia presentes;
- 26 arquivos Python passaram em análise sintática durante a materialização;
- `mdtxtrt/static/app.js` passou em `node --check` durante a materialização;
- hashes do manifesto do checkpoint foram conferidos.
- gate interno oficial executado com sucesso em Python 3.12.14, aiogram 3.31.0 e Bot API 10.3;
- modelos Rich Message, seleção de renderizador, handlers, contrato estático e sintaxe JavaScript aprovados;
- aplicação iniciada localmente e `/health` respondeu com `ok: true`.

O deploy oficial existente no Railway está em estado `SUCCESS`, com build, startup e healthcheck aprovados. Esses fatos não comprovam E2E Telegram nem QA móvel real.

## Divergências de aderência resolvidas

O gate atual comprovou a implementação das correções anteriormente registradas:

- accent laranja, H1/H2/H3, controles nativos, safe areas e viewport estável;
- prévia e envio usando o mesmo classificador;
- `/converter` com estado `waiting_text` e `/formatos` com estruturas Rich;
- botão Rich com fallback tradicional;
- distinção entre Blocks, Rich Markdown, Rich HTML, HTML tradicional e MarkdownV2.

A issue #4 preserva o histórico dessas correções.

## Pendências externas

- o serviço oficial não possui `TOKEN`; por isso o bot permanece desativado;
- `KEY` foi configurada sem disparar deploy;
- nenhum volume persistente está conectado a `/data`; a persistência do SQLite ainda não está garantida;
- o serviço oficial continua usando `feat/mdtxtrt-official-release`, não o head atual;
- a tentativa de corrigir volume e branch foi bloqueada pelo limite de uso do agente Railway;
- E2E Telegram e QA móvel real somente podem ser marcados após essas configurações e uma sessão real.

## Regra de status

- código presente não autoriza marcar E2E;
- checagem de sintaxe não autoriza marcar integração;
- resposta HTTP isolada não autoriza afirmar publicação correta no Telegram;
- deploy `FAILED` antes do build não prova defeito da aplicação;
- QA simulado não substitui QA móvel real;
- nenhuma evidência deve ser promovida de nível por inferência.

## Regras de entrega

- preservar histórico Git;
- registrar evidências na issue e na PR;
- manter PR em draft até os critérios externos serem satisfeitos;
- não fazer merge automaticamente;
- marcar cada item somente depois da evidência correspondente.
