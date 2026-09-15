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
- deploy oficial Railway `22c99d7e-84b6-4124-9950-3440ae221b01`: `SUCCESS`, com healthcheck aprovado.

## Limite externo

O código do produto está concluído no escopo contratado. A operação real do bot não pode ser validada enquanto `TOKEN` não existir no serviço Railway. `KEY` foi gerada e configurada no serviço oficial sem disparar deploy. O serviço ainda precisa de um volume persistente em `/data` e continua apontando para a branch anterior; a correção dessas duas configurações foi bloqueada pelo limite de uso do agente Railway. E2E Telegram e QA móvel permanecem não comprovados.

O PR #8 foi posteriormente mesclado pela conta GitHub `romastefale` às 04:37 UTC, fora das ações executadas pelo assistente. O workflow histórico restaurado foi acionado por esse merge e materializou novamente o checkpoint na branch de implementação. Nenhuma reversão destrutiva foi executada.
