# Estado da release — 2026-09-15

## Repositório

- escopo funcional congelado;
- código e documentação materializados;
- arquivos apagados recuperados com proveniência;
- variáveis externas simplificadas para `TOKEN` e `KEY`;
- gate interno, compilação Python, sintaxe JavaScript e `git diff --check` aprovados;
- versão atual preservada em `restore/deleted-artifacts-v3`;
- issue de finalização: #9;
- PR corretivo: #10, sem merge automático.

O repositório está concluído como candidato de release. Isso não equivale à aprovação operacional do bot.

## Compatibilidade

- Telegram Bot API: 10.3, publicada em 2026-08-24;
- aiogram: 3.31.0, com cobertura nativa declarada para Bot API 10.3;
- Python validado localmente: 3.12.14;
- faixa do aiogram: Python 3.10–3.14;
- transporte: long polling;
- dependências relevantes: aiogram 3.31.0, aiohttp 3.14.3, telegraph 2.2.0 e cryptography.

Webhook não foi adotado porque alteraria a arquitetura validada sem necessidade do escopo.

## Railway

- serviço atual: `mdtxtrt-implementation`;
- deploy atual: `SUCCESS`;
- domínio: `https://mdtxtrt-implementation-production.up.railway.app`;
- `KEY`: configurada;
- `MDTXTRT_DB`: preparado como `/data/mdtxtrt.sqlite3`;
- `WEB_APP_URL`: configurada;
- `TOKEN`: ausente;
- volume persistente em `/data`: ausente;
- branch implantada: `feat/mdtxtrt-implementation`;
- branch candidata: `restore/deleted-artifacts-v3`.

A conexão do volume e a troca de branch não foram executadas porque o Railway respondeu `Agent usage limit reached`.

## Aprovação

Concluído: repositório e candidato interno.

Não concluído: ativação do bot, persistência garantida, E2E Telegram/Telegraph e QA móvel.

Critérios externos restantes:

1. configurar `TOKEN` no Railway;
2. montar volume persistente em `/data`;
3. implantar a branch candidata;
4. confirmar `/health` com bot ativo;
5. executar os sete comandos, envio Rich, Mini App e Telegraph em sessão real.
