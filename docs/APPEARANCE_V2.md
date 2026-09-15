# Aparência v2 — 2026-09-15

Evolução aplicada sobre `release/mdtxtrt-final-v1` (2bf3bc5), preservando a implementação Python/aiogram, o contrato funcional e o editor existente. O protótipo JavaScript independente da conversa anterior não substitui esta base.

- Laranja continua sendo o destaque padrão.
- Configurações → Cor de destaque oferece vermelho, laranja, amarelo, verde, azul, anil e violeta.
- `/configuracoes` e `/cor` apresentam sete botões integrados Rich; um toque salva a preferência, sem digitar o nome da cor.
- Preferência persistente por usuário, compartilhada entre bot e Mini App.
- A abertura e a reativação da Mini App sincronizam a preferência; mudança de tema mantém a cor escolhida.
- Fundos branco e preto puros. Texto dos botões adapta o contraste à cor.
- O botão integrado de entrada permanece `success` (verde), independente da preferência do editor.
- Nenhuma mudança nos documentos, destinos de publicação ou nos sete comandos anteriores.

Verificação: teste de paleta, rejeição de valores inválidos, persistência e isolamento entre usuários; sintaxe Python e JavaScript. Validação visual em Telegram Android/iPhone e comandos contra o bot real ainda dependem da ativação externa. Esta mudança não transforma os gates anteriores em comprovação integral do produto.

Cronologia: versão anterior preservada na branch de origem; implementação desta evolução em `feat/mdtxtrt-accent-settings`; sem merge automático.

Correção de interação: um único botão de estilo de texto reúne texto normal e títulos 1–6. Aplicar o estilo transforma o trecho selecionado, preservando seu conteúdo. A barra usa SVGs com traço consistente. Exclusão saiu do X sobre o texto e passou ao menu do trecho, com confirmação e desfazer. A seleção é preservada ao tocar nos controles de formatação.
