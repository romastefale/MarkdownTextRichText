# Restauração de arquivos apagados — 2026-09-15

## Escopo

Esta versão restaura 22 arquivos encontrados como excluídos no histórico da branch `feat/mdtxtrt-implementation`. O estado anterior permanece preservado no commit `15d6e2dafa63b90d677bc7290e0ecebd17b32e7f`; a restauração foi realizada na branch separada `restore/deleted-artifacts-v3`.

## Origens preservadas

- `.checkpoint/` e `.github/workflows/materialize-checkpoint.yml`: conteúdo anterior ao commit `58bdb38d297eddd8a6df5fbafafcfbfa08c60704`.
- `.release/`: conteúdo anterior ao commit `ad4321cb3bbc980b0c80e599ab802727b023676f`.
- `.github/workflows/apply-official-release.yml`: conteúdo anterior ao commit `c9fe6fb12915d06338d6685907e2c205143300a7`.

## Verificação

- O arquivo de checkpoint reconstruído a partir de `.checkpoint/parts/p*` corresponde ao SHA-256 `79d71ec74214a6073b4da08c7aaac6965210ffb691d1754e589da76e75b854e0`.
- O arquivo de release reconstruído a partir de `.release/part*` corresponde ao SHA-256 `c91aa747e32560eeabf4fc0ae7ea186428bc4f3f58a4d5a15a7d9a3b1dea3831`.
- Os workflows restaurados correspondem byte a byte às versões históricas selecionadas.

Nenhum merge foi realizado.
