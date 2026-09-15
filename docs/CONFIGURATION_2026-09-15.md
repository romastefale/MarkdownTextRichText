# Configuração simplificada — 2026-09-15

Esta versão substitui os nomes longos das duas credenciais externas:

- `TOKEN`: token do bot fornecido pelo BotFather;
- `KEY`: chave Base64 de 32 bytes usada internamente para criptografar os tokens de edição do Telegraph antes de armazená-los no banco.

O usuário não fornece token do Telegraph. O aplicativo cria uma conta Telegraph por usuário e protege o token retornado usando `KEY` com AES-256-GCM.

As versões anteriores e sua cronologia permanecem preservadas. Nenhum merge foi realizado.
