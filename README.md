# MDTXTRT

Bot Telegram e Mini App para importar, editar, visualizar, converter e publicar conteúdo Markdown (`.md`) e texto (`.txt`). O projeto usa um documento semântico compartilhado e oferece Rich Messages, HTML Telegram, MarkdownV2, exportação e publicação no Telegraph.

## Estado do produto

- código do produto: finalizado na linha `release/mdtxtrt-final-v2`;
- aparência v2 aplicada: controles Rich corrigidos e preferência pessoal de sete cores;
- gate interno, compilação Python, testes e sintaxe JavaScript fazem parte da verificação da release;
- Telegram Bot API 10.3 e aiogram 3.31.0;
- transporte do bot: long polling;
- versões anteriores preservadas; sem merge automático;
- artefatos temporários de checkpoint/release não fazem parte da árvore final v2;
- operação real exige `TOKEN`, persistência configurada e validação E2E no ambiente de produção.

A cronologia está em `docs/CONTINUITY.md` e a evolução visual em `docs/APPEARANCE_V2.md`.

## Execução

Requer Python 3.10–3.14. A combinação de referência é Python 3.12 com as versões fixadas em `requirements.txt`.

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
.venv/bin/python -m compileall -q mdtxtrt scripts tests
.venv/bin/python -m unittest discover -s tests
node --check mdtxtrt/static/release.js
git diff --check
```

Os gates locais não substituem teste real de Telegram, Telegraph, Mini App e clientes móveis.

## Documentação

- `docs/CONTRACT.md`: contrato funcional;
- `docs/APPEARANCE_V2.md`: aparência e controles Rich finais;
- `docs/IMPLEMENTATION_VERIFICATION.md`: níveis de evidência;
- `docs/CONTINUITY.md`: cronologia completa;
- `docs/CONFIGURATION_2026-09-15.md`: configuração operacional.
