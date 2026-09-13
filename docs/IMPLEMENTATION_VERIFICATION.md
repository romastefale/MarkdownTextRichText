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

## Estado atual

### Materializado e verificado mecanicamente

- checkpoint `2026-09-13-v2` materializado na branch `feat/mdtxtrt-implementation`;
- modelo semântico e renderizadores presentes;
- sete comandos presentes;
- Mini App, importação e prévia presentes;
- 26 arquivos Python passaram em análise sintática durante a materialização;
- `mdtxtrt/static/app.js` passou em `node --check` durante a materialização;
- hashes do manifesto do checkpoint foram conferidos.

Esses fatos não comprovam integração, E2E, QA móvel nem deploy funcional.

## Divergências de aderência identificadas

Antes de promover o produto para validação final, permanecem correções próprias de implementação:

- interface visual ainda diverge do contrato em accent e uso de controles nativos;
- H1/H2/H3 não estão expostos como três ações independentes;
- integração de BackButton, botão inferior nativo, safe areas e viewport estável precisa ser completada;
- prévia precisa usar o mesmo pipeline final de renderização/envio;
- `/converter` precisa consumir uma mensagem textual subsequente quando estiver em `waiting_text`;
- `/formatos` precisa demonstrar estruturas Rich reais;
- botão global deve usar o mecanismo Rich apropriado quando suportado e fallback compatível quando não;
- documentação e código precisam manter a distinção entre `InputRichMessage.blocks`, `InputRichMessage.markdown`, `InputRichMessage.html` e os formatos tradicionais HTML/MarkdownV2.

A issue #4 controla essas correções.

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