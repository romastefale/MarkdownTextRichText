# MDTXTRT

Bot Telegram e Mini App para importar, editar, visualizar, converter e publicar conteúdo Markdown (`.md`) e texto (`.txt`). O projeto usa um documento semântico compartilhado e oferece Rich Messages, HTML Telegram, MarkdownV2, exportação e publicação no Telegraph.

## Estado da entrega

- código do escopo contratado: concluído;
- gate interno, compilação Python e sintaxe JavaScript: aprovados;
- Telegram Bot API 10.3 e aiogram 3.31.0;
- transporte: long polling;
- PR de finalização: [#10](https://github.com/romastefale/MarkdownTextRichText/pull/10), sem merge automático;
- operação real do bot: pendente de `TOKEN` e validação E2E;
- persistência Railway: pendente de volume montado em `/data`.

O estado verificável e os limites da aprovação estão em [`docs/RELEASE_STATUS.md`](docs/RELEASE_STATUS.md).

## Execução

Requer Python 3.10–3.14. A combinação validada localmente foi Python 3.12.14 com as versões fixadas em `requirements.txt`.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
TOKEN='token-do-bot' KEY='chave-base64-de-32-bytes' WEB_APP_URL='https://exemplo' .venv/bin/python app.py
```

Variáveis do produto:

- `TOKEN`: token do bot fornecido pelo BotFather;
- `KEY`: chave Base64 de 32 bytes usada para proteger as credenciais Telegraph armazenadas;
- `WEB_APP_URL`: endereço HTTPS público da Mini App;
- `MDTXTRT_DB`: arquivo SQLite, recomendado como `/data/mdtxtrt.sqlite3` no Railway;
- `PORT`: porta HTTP, definida automaticamente pelo Railway.

Não grave segredos no Git, frontend ou logs.

## Verificação

```bash
PYTHONPATH=. .venv/bin/python scripts/release_gate.py
.venv/bin/python -m compileall -q mdtxtrt scripts
node --check mdtxtrt/static/release.js
git diff --check
```

O gate valida modelos Rich Message do aiogram, seleção de renderizadores, handlers, contrato estático e os nomes `TOKEN`/`KEY`. Ele não substitui o teste real no Telegram, Telegraph e clientes móveis.

## Documentação

- [`docs/CONTRACT.md`](docs/CONTRACT.md): escopo funcional;
- [`docs/IMPLEMENTATION_VERIFICATION.md`](docs/IMPLEMENTATION_VERIFICATION.md): níveis de evidência;
- [`docs/CONTINUITY.md`](docs/CONTINUITY.md): cronologia;
- [`docs/RESTORATION_2026-09-15.md`](docs/RESTORATION_2026-09-15.md): arquivos recuperados;
- [`docs/CONFIGURATION_2026-09-15.md`](docs/CONFIGURATION_2026-09-15.md): configuração simplificada.
