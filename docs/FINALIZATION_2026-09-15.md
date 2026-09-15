# Finalização interna — 2026-09-15

## Escopo congelado

Somente o contrato existente do MDTXTRT foi validado. Nenhuma funcionalidade foi acrescentada.

## Compatibilidade verificada

- Telegram Bot API 10.3, publicada em 2026-08-24.
- aiogram 3.31.0, estável, com cobertura nativa declarada para Bot API 10.3.
- Python 3.12.14 no gate local; o aiogram selecionado suporta Python 3.10–3.14.
- Transporte do bot: long polling, já implementado.
- Dependências do projeto: aiogram 3.31.0, aiohttp 3.14.3, telegraph 2.2.0 e cryptography.

Não foi escolhida uma versão antiga do aiogram porque 3.31.0 é a versão estável atual com cobertura nativa do Bot API 10.3. Webhook não foi adotado porque mudaria a arquitetura já definida e validada por long polling.

## Evidências concluídas

- `scripts/release_gate.py`: aprovado.
- compilação dos módulos Python: aprovada.
- `node --check mdtxtrt/static/release.js`: aprovado.
- startup local e `/health`: aprovados.
- o deploy Railway histórico `22c99d7e-84b6-4124-9950-3440ae221b01` foi aprovado antes da remoção do serviço correspondente;
- o serviço atual `mdtxtrt-implementation` possui deploy `SUCCESS` e domínio público.

## Limite externo

O código do produto está concluído no escopo contratado. O serviço `mdtxtrt-official-release` foi removido do Railway. O serviço atual é `mdtxtrt-implementation`, com domínio `https://mdtxtrt-implementation-production.up.railway.app`. Nele, `KEY`, `MDTXTRT_DB=/data/mdtxtrt.sqlite3` e `WEB_APP_URL` foram preparados sem disparar deploy. A operação real do bot não pode ser validada enquanto `TOKEN` não existir. O volume persistente em `/data` e a troca da branch foram bloqueados pelo limite de uso do agente Railway. E2E Telegram e QA móvel permanecem não comprovados.

O PR #8 foi posteriormente mesclado pela conta GitHub `romastefale` às 04:37 UTC, fora das ações executadas pelo assistente. O workflow histórico restaurado foi acionado por esse merge e materializou novamente o checkpoint na branch de implementação. Nenhuma reversão destrutiva foi executada.
