# Proveniência da reconstrução

A implementação neste pacote foi reconstruída usando três fontes distintas:

1. decisões funcionais e arquiteturais aprovadas pelo proprietário;
2. artefatos forenses/contextuais recuperados do rebuild perdido;
3. fonte física da implementação monolítica anterior quando necessária para preservar comportamento.

Os artefatos recuperados afirmam explicitamente que não existe, no conjunto de evidências disponível, uma cópia byte a byte confirmada do rebuild modular completo. Portanto, a existência de um nome/caminho conhecido não autoriza chamar o conteúdo recriado de original.

Os caminhos de alta confiança contextual incluem `config.py`, `conversion/markdown.py`, `web/auth.py` e `web/server.py`, além dos grupos `domain`, `services`, `storage`, `telegram`, `web`, `conversion` e `static`.

A posição histórica exata de alguns nomes recuperados, como `telegram_formats.py`, `telegraph.py` e arquivos `static`, era ambígua. A posição usada nesta versão é uma decisão da arquitetura v2, não uma alegação de recuperação byte a byte.
