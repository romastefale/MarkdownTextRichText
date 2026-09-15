# Continuidade de implementação — 2026-09-13

## Estado observado antes desta versão

- `main` continha apenas o commit inicial.
- `feat/mdtxtrt-implementation` continha apenas `docs/CONTRACT.md`.
- PR #2 estava aberto como draft, sem merge.
- Railway `MarkdownTextRichText` existia sem serviços.
- O código modular anterior não havia sido aplicado neste repositório.

## Fonte de continuidade

Esta versão usa como base física o snapshot persistido `MDTXTRT-rebuild-v2-2026-09-08.zip` e o registro técnico de continuidade. O snapshot é uma reconstrução persistida do trabalho anterior, não uma alegação de bytes originais do runtime perdido.

## Mudanças desta versão

1. Materialização da arquitetura modular: domínio canônico, conversores, SQLite, bot aiogram, Web API aiohttp, frontend visual, Telegram Rich e Telegraph.
2. Importação limitada ao contrato atual: somente `.md` e `.txt`.
3. Preservação literal: TXT importado sem edição pode ser exportado com os mesmos caracteres e finais de linha; a fonte literal é usada apenas enquanto a árvore visual permanece inalterada.
4. Preservação lexical de Markdown: a fonte Markdown e seus escapes são reutilizados enquanto a árvore importada permanece inalterada; após edição, a saída é regenerada do documento canônico.
5. Bot alinhado aos sete comandos públicos: `/start`, `/help`, `/importar`, `/converter`, `/editor`, `/formatos`, `/cancelar`.
6. `/converter` funciona sem abrir o Mini App para texto respondido/enviado e arquivos `.md`/`.txt` UTF-8.
7. Sessão do Mini App continua validada no servidor a partir de `initData`, com TTL configurável e `owner_id` derivado do Telegram.
8. Destino Telegram deixou de aceitar `chat_id` arbitrário do navegador. Chats passam a ser registrados pelo servidor a partir de interações reais do usuário com o bot e o Mini App envia apenas um `destination_id` pertencente ao usuário autenticado.
9. Publicação registra `destination_id`, `chat_id` resolvido e `message_id` para rastreabilidade.

## Verificação desta versão

Somente verificações mecânicas de sintaxe/estrutura foram executadas localmente. Não há alegação de validação ponta a ponta com Telegram, Telegraph ou Railway nesta versão.

## Cronologia posterior

- 2026-09-15 — versão `restore/deleted-artifacts-v3`: restaurados, sem alterar as versões anteriores, os 23 arquivos removidos pelos commits `58bdb38d297eddd8a6df5fbafafcfbfa08c60704`, `ad4321cb3bbc980b0c80e599ab802727b023676f` e `c9fe6fb12915d06338d6685907e2c205143300a7`. A proveniência e as verificações constam em `docs/RESTORATION_2026-09-15.md`.
- 2026-09-15 — versão de finalização interna: escopo do contrato congelado, compatibilidade atual verificada, gate e healthcheck aprovados e deploy Railway confirmado. Credenciais e validações externas permanecem explicitamente separadas em `docs/FINALIZATION_2026-09-15.md`.
- 2026-09-15 — versão de simplificação da configuração: as variáveis externas foram reduzidas a `TOKEN` para o token do bot e `KEY` para a chave técnica que protege os tokens Telegraph armazenados. O gate passou a verificar os dois nomes.
- 2026-09-15 — preparação Railway: `KEY` gerada e configurada no serviço `mdtxtrt-official-release` sem deploy. A ligação do volume `/data` e a troca da branch de produção foram solicitadas, mas o Railway recusou a operação por limite de uso do agente; `TOKEN` continua ausente.
