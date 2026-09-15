"""Projeções legadas adaptadas da fonte física monolítica para o rebuild modular."""
from __future__ import annotations

from dataclasses import dataclass
import html
import re
from urllib.parse import urlparse

LOCAL_MEDIA_RE = re.compile(
    r'!\[([^\]]*)\]\(mdtxtrt://(photo|video|animation|audio|document)/([A-Za-z0-9_-]+)(?:\s+"([^"]*)")?\)'
)
HTTP_MEDIA_RE = re.compile(
    r'^!\[([^\]]*)\]\((https?://[^\s)]+)(?:\s+"([^"]*)")?\)\s*$'
)
INLINE_LINK_RE = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
TG_REMOTE_MEDIA_RE = re.compile(
    r'tg://(photo|video|document|audio)\?id=([^&\s"\'>)]+)(?:&amp;|&)file=([^&\s"\'>)]+)',
    re.I,
)

_RICH_NO_MARKDOWN_BLOCKS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "aside", "pre", "footer", "table", "caption",
    "tr", "th", "td", "ul", "ol", "li", "figure", "figcaption",
    "tg-button-row", "tg-button", "tg-map", "tg-math-block",
}
_TAG_TOKEN_RE = re.compile(r'(<!--.*?-->|</?[A-Za-z][^>]*>)', re.S)
_FENCE_START_RE = re.compile(r'^\s*(`{3,}|~{3,})([^`]*)$')


@dataclass(frozen=True)
class LocalMediaRef:
    kind: str
    media_id: str
    caption: str = ""

    @property
    def telegram_scheme(self) -> str:
        if self.kind == "photo":
            return "photo"
        if self.kind in {"video", "animation"}:
            return "video"
        if self.kind == "document":
            return "document"
        return "audio"


@dataclass(frozen=True)
class TelegraphProjection:
    html: str
    adaptations: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()

    @property
    def compatible(self) -> bool:
        return not self.unsupported

    @property
    def degradations(self) -> tuple[str, ...]:
        """Compatibilidade retroativa: antigas 'degradations' agora são adaptações seguras."""
        return self.adaptations


@dataclass(frozen=True)
class CanonicalDocument:
    markdown: str

    @classmethod
    def from_markdown(cls, source: str) -> "CanonicalDocument":
        text = (source or "").replace("\r\n", "\n").replace("\r", "\n")
        if text.startswith("\ufeff"):
            text = text[1:]
        return cls(text)

    def telegram_markdown(self) -> tuple[str, tuple[LocalMediaRef, ...]]:
        refs: list[LocalMediaRef] = []
        rendered = _telegram_semantic_markdown(self.markdown)

        def repl(match: re.Match) -> str:
            alt, kind, media_id, caption = match.groups()
            caption = caption or alt or ""
            ref = LocalMediaRef(kind=kind, media_id=media_id, caption=caption)
            refs.append(ref)
            title = f' "{caption.replace(chr(34), "")}"' if caption else ""
            return f"![](tg://{ref.telegram_scheme}?id={media_id}{title})"

        return LOCAL_MEDIA_RE.sub(repl, rendered), tuple(refs)

    def telegraph(self) -> TelegraphProjection:
        return markdown_to_telegraph(self.markdown)


def _unique(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return tuple(out)


def _tag_name(token: str) -> tuple[str, bool, bool]:
    token = token.strip()
    if token.startswith("<!--"):
        return "", False, True
    closing = token.startswith("</")
    match = re.match(r"</?\s*([A-Za-z0-9-]+)", token)
    if not match:
        return "", closing, True
    name = match.group(1).lower()
    self_closing = token.rstrip().endswith("/>") or name in {"hr", "img", "input", "tg-map"}
    return name, closing, self_closing


def _rich_inline_html(text: str) -> str:
    """Converte apenas marcação Markdown que estaria inerte dentro de HTML de bloco."""
    placeholders: dict[str, str] = {}

    def hold(value: str) -> str:
        key = f"\x00mdtxtrt{len(placeholders)}\x00"
        placeholders[key] = value
        return key

    text = re.sub(
        r"`([^`\n]*)`",
        lambda m: hold(f"<code>{html.escape(m.group(1), quote=False)}</code>"),
        text,
    )
    text = re.sub(
        r"!\[([^\]]*)\]\(tg://emoji\?id=([^)]+)\)",
        lambda m: hold(
            f'<tg-emoji emoji-id="{html.escape(m.group(2), quote=True)}">'
            f"{html.escape(m.group(1), quote=False)}</tg-emoji>"
        ),
        text,
    )

    def link_repl(match: re.Match) -> str:
        label, target = match.groups()
        return hold(
            f'<a href="{html.escape(target, quote=True)}">'
            f"{_rich_inline_html(label)}</a>"
        )

    text = INLINE_LINK_RE.sub(link_repl, text)
    text = re.sub(
        r"(?<!\$)\$([^\n$]+)\$(?!\$)",
        lambda m: hold(f"<tg-math>{html.escape(m.group(1), quote=False)}</tg-math>"),
        text,
    )
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<i>\1</i>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    text = re.sub(r"==(.+?)==", r"<mark>\1</mark>", text)
    text = re.sub(r"\|\|(.+?)\|\|", r"<tg-spoiler>\1</tg-spoiler>", text)

    for key, value in placeholders.items():
        text = text.replace(key, value)
    return text


def _telegram_semantic_markdown(source: str) -> str:
    """Mantém a origem intacta e adapta somente regiões onde Rich Markdown não é interpretado."""
    lines = (source or "").split("\n")
    out: list[str] = []
    stack: list[str] = []
    fenced_in_inert_html = False
    fence_marker = ""

    for line in lines:
        inert = any(tag in _RICH_NO_MARKDOWN_BLOCKS for tag in stack)

        if fenced_in_inert_html:
            if re.match(rf"^\s*{re.escape(fence_marker[0])}{{{len(fence_marker)},}}\s*$", line):
                out.append("</code></pre>")
                fenced_in_inert_html = False
                fence_marker = ""
            else:
                out.append(html.escape(line, quote=False))
            continue

        fence = _FENCE_START_RE.match(line)
        if inert and fence:
            marker = fence.group(1)
            language = fence.group(2).strip()
            cls = (
                f' class="language-{html.escape(language, quote=True)}"'
                if language else ""
            )
            out.append(f"<pre><code{cls}>")
            fenced_in_inert_html = True
            fence_marker = marker
            continue

        pieces = _TAG_TOKEN_RE.split(line)
        rendered: list[str] = []
        for piece in pieces:
            if not piece:
                continue
            if piece.startswith("<") and piece.endswith(">"):
                rendered.append(piece)
                name, closing, self_closing = _tag_name(piece)
                if not name:
                    continue
                if closing:
                    for index in range(len(stack) - 1, -1, -1):
                        if stack[index] == name:
                            del stack[index:]
                            break
                elif not self_closing:
                    stack.append(name)
                continue

            if any(tag in _RICH_NO_MARKDOWN_BLOCKS for tag in stack):
                rendered.append(_rich_inline_html(piece))
            else:
                rendered.append(piece)
        out.append("".join(rendered))

    return "\n".join(out)


def _media_kind_from_url(url: str) -> str:
    path = urlparse(url).path.lower()
    if path.endswith((".jpg", ".jpeg", ".png", ".webp", ".avif")):
        return "image"
    if path.endswith((".mp4", ".webm", ".mov", ".m4v", ".gif")):
        return "video"
    if path.endswith((".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav")):
        return "audio"
    return "document"


def _attrs(source: str) -> dict[str, str | bool]:
    result: dict[str, str | bool] = {}
    for match in re.finditer(
        r'([A-Za-z_:][-A-Za-z0-9_:.]*)(?:\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s"\'>]+)))?',
        source or "",
    ):
        name = match.group(1).lower()
        value = next((v for v in match.groups()[1:] if v is not None), None)
        result[name] = value if value is not None else True
    return result


def _inline_telegraph(
    text: str,
    adaptations: list[str],
    unsupported: list[str],
) -> str:
    text = html.unescape(text)
    placeholders: dict[str, str] = {}

    def hold(value: str) -> str:
        key = f"\x00telegraph{len(placeholders)}\x00"
        placeholders[key] = value
        return key

    def semantic_entity(match: re.Match) -> str:
        attrs = _attrs(match.group(1))
        body = _inline_telegraph(match.group(2), adaptations, unsupported)
        typ = str(attrs.get("type") or "entity")
        metadata = "; ".join(
            f"{name}={value}" for name, value in attrs.items() if name != "type"
        )
        adaptations.append("Tipo e parâmetros de entidade Rich sem equivalente explícito no Telegraph são preservados textualmente.")
        suffix = f"; {metadata}" if metadata else ""
        return hold(body + f" <code>[rich:{html.escape(typ + suffix)}]</code>")

    text = re.sub(r"<tg-entity\b([^>]*)>(.*?)</tg-entity>", semantic_entity, text, flags=re.I | re.S)

    def anchor(match: re.Match) -> str:
        name = match.group(1)
        adaptations.append("Âncoras internas não navegam no Telegraph; o identificador é preservado textualmente.")
        return hold(f"<code>[anchor:{html.escape(name)}]</code>")

    text = re.sub(r'<a\s+name=["\']([^"\']+)["\']\s*></a>', anchor, text, flags=re.I)

    def reference(match: re.Match) -> str:
        name, body = match.groups()
        adaptations.append("Referências internas não navegam no Telegraph; relação e identificador são preservados textualmente.")
        rendered = _inline_telegraph(body, adaptations, unsupported)
        return hold(rendered + f" <code>[reference:{html.escape(name)}]</code>")

    text = re.sub(
        r'<tg-reference\s+name=["\']([^"\']+)["\']>(.*?)</tg-reference>',
        reference,
        text,
        flags=re.I | re.S,
    )

    def emoji(match: re.Match) -> str:
        emoji_id, body = match.groups()
        adaptations.append("Custom emoji é exibido pelo texto alternativo; o identificador é preservado.")
        visible = _inline_telegraph(body, adaptations, unsupported)
        return hold(visible + f" <code>[emoji:{html.escape(emoji_id)}]</code>")

    text = re.sub(
        r'<tg-emoji\s+emoji-id=["\']([^"\']+)["\']>(.*?)</tg-emoji>',
        emoji,
        text,
        flags=re.I | re.S,
    )

    def tg_time(match: re.Match) -> str:
        attrs_text, body = match.groups()
        at = _attrs(attrs_text)
        unix = at.get("unix", "")
        fmt = at.get("format", "")
        adaptations.append("Data/hora Rich é exibida como texto; parâmetros sem equivalente são preservados.")
        visible = _inline_telegraph(body, adaptations, unsupported)
        meta = f"time unix={unix}" + (f" format={fmt}" if fmt else "")
        return hold(visible + f" <code>[{html.escape(meta)}]</code>")

    text = re.sub(r"<tg-time\b([^>]*)>(.*?)</tg-time>", tg_time, text, flags=re.I | re.S)

    def spoiler(match: re.Match) -> str:
        adaptations.append("Spoiler do Telegram é publicado revelado no Telegraph.")
        return hold(_inline_telegraph(match.group(1), adaptations, unsupported))

    text = re.sub(r"<tg-spoiler>(.*?)</tg-spoiler>", spoiler, text, flags=re.I | re.S)

    def math_inline(match: re.Match) -> str:
        adaptations.append("Fórmulas LaTeX são preservadas como código porque o Telegraph não possui matemática nativa.")
        return hold(f"<code>{html.escape(match.group(1), quote=False)}</code>")

    text = re.sub(r"<tg-math>(.*?)</tg-math>", math_inline, text, flags=re.I | re.S)

    def html_link(match: re.Match) -> str:
        target, label = match.groups()
        rendered = _inline_telegraph(label, adaptations, unsupported)
        if target.startswith("#"):
            adaptations.append("Links internos não navegam no Telegraph; o alvo é preservado textualmente.")
            return hold(rendered + f" <code>[→{html.escape(target[1:])}]</code>")
        return hold(f'<a href="{html.escape(target, quote=True)}">{rendered}</a>')

    text = re.sub(
        r'<a\s+href=["\']([^"\']+)["\']\s*>(.*?)</a>',
        html_link,
        text,
        flags=re.I | re.S,
    )

    tag_map = {
        "b": "strong", "strong": "strong",
        "i": "em", "em": "em",
        "u": "u", "ins": "u",
        "s": "s", "strike": "s", "del": "s",
        "code": "code",
    }
    for source_tag, target_tag in tag_map.items():
        pattern = rf"<{source_tag}\b[^>]*>(.*?)</{source_tag}>"
        text = re.sub(
            pattern,
            lambda m, t=target_tag: hold(
                f"<{t}>{_inline_telegraph(m.group(1), adaptations, unsupported)}</{t}>"
            ),
            text,
            flags=re.I | re.S,
        )

    def mark(match: re.Match) -> str:
        adaptations.append("Texto marcado é publicado em destaque simples no Telegraph.")
        return hold(f"<strong>{_inline_telegraph(match.group(1), adaptations, unsupported)}</strong>")

    text = re.sub(r"<mark\b[^>]*>(.*?)</mark>", mark, text, flags=re.I | re.S)

    def sub_sup(match: re.Match) -> str:
        adaptations.append("Subscrito/sobrescrito é preservado como texto normal no Telegraph.")
        return hold(_inline_telegraph(match.group(2), adaptations, unsupported))

    text = re.sub(r"<(sub|sup)\b[^>]*>(.*?)</\1>", sub_sup, text, flags=re.I | re.S)

    def md_link(match: re.Match) -> str:
        label, target = match.groups()
        rendered = _inline_telegraph(label, adaptations, unsupported)
        if target.startswith("#"):
            adaptations.append("Links internos não navegam no Telegraph; o alvo é preservado textualmente.")
            return hold(rendered + f" <code>[→{html.escape(target[1:])}]</code>")
        return hold(f'<a href="{html.escape(target, quote=True)}">{rendered}</a>')

    text = INLINE_LINK_RE.sub(md_link, text)
    text = re.sub(
        r"`([^`\n]+)`",
        lambda m: hold(f"<code>{html.escape(m.group(1), quote=False)}</code>"),
        text,
    )
    text = re.sub(
        r"(?<!\$)\$([^\n$]+)\$(?!\$)",
        lambda m: math_inline(m),
        text,
    )

    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"~~(.+?)~~", r"<s>\1</s>", escaped)

    if re.search(r"==.+?==", escaped, re.S):
        adaptations.append("Texto marcado é publicado em destaque simples no Telegraph.")
        escaped = re.sub(r"==(.+?)==", r"<strong>\1</strong>", escaped)
    if re.search(r"\|\|.+?\|\|", escaped, re.S):
        adaptations.append("Spoiler do Telegram é publicado revelado no Telegraph.")
        escaped = re.sub(r"\|\|(.+?)\|\|", r"\1", escaped)

    for key, value in placeholders.items():
        escaped = escaped.replace(key, value)
    return escaped


def _collect_tag_block(lines: list[str], start: int, closing: str) -> tuple[str, int]:
    block: list[str] = []
    i = start
    closing_lower = closing.lower()
    depth = 0
    open_name = closing_lower.replace("</", "").replace(">", "")
    open_re = re.compile(rf"<{re.escape(open_name)}\b", re.I)
    close_re = re.compile(re.escape(closing), re.I)
    while i < len(lines):
        line = lines[i]
        block.append(line)
        depth += len(open_re.findall(line))
        depth -= len(close_re.findall(line))
        i += 1
        if depth <= 0 and close_re.search(line):
            break
    return "\n".join(block), i


def _strip_outer(blob: str, tag: str) -> str:
    body = re.sub(rf"^\s*<{tag}\b[^>]*>", "", blob, flags=re.I | re.S)
    body = re.sub(rf"</{tag}>\s*$", "", body, flags=re.I | re.S)
    return body.strip()


def _telegraph_button_row(
    blob: str,
    adaptations: list[str],
    unsupported: list[str],
) -> str:
    opening = re.search(r"<tg-button-row\b([^>]*)>", blob, re.I)
    row_attrs = _attrs(opening.group(1)) if opening else {}
    row_meta: list[str] = []
    if row_attrs.get("align") not in (None, False, ""):
        row_meta.append(f"align={row_attrs['align']}")
        adaptations.append("Alinhamento da linha de botões não existe no Telegraph; o valor é preservado textualmente.")
    for name, value in row_attrs.items():
        if name != "align" and value not in (None, False, ""):
            row_meta.append(f"{name}={value}")
            adaptations.append("Atributos visuais ou estruturais da linha de botões sem equivalente no Telegraph são preservados textualmente.")
    buttons = re.findall(r"<tg-button\s+([^>]*)>(.*?)</tg-button>", blob, re.I | re.S)
    rendered: list[str] = []
    for attrs_text, raw_label in buttons:
        attrs = _attrs(attrs_text)
        label = re.sub(r"<[^>]+>", "", raw_label).strip() or "Botão"
        safe_label = html.escape(label)
        typ = str(attrs.get("type") or "")
        style = attrs.get("style")
        metadata: list[str] = []
        if style:
            metadata.append(f"style={style}")
            adaptations.append("Estilo visual de botão não existe no Telegraph; o valor do estilo é preservado textualmente.")

        url = str(attrs.get("url") or "")
        if typ in {"url", "web_app", "login_url"} and url:
            body = f'<a href="{html.escape(url, quote=True)}">{safe_label}</a>'
            if typ != "url":
                metadata.append(f"type={typ}")
            if attrs.get("forward-text") not in (None, False):
                metadata.append(f"forward-text={attrs.get('forward-text')}")
            if attrs.get("request-write-access"):
                metadata.append("request-write-access")
        elif typ == "copy_text":
            copied = str(attrs.get("text") or "")
            body = f"{safe_label}: <code>{html.escape(copied)}</code>"
            metadata.append("type=copy_text")
        else:
            body = f"<strong>{safe_label}</strong>"
            metadata.append(f"type={typ or 'button'}")
            if typ == "callback_data":
                metadata.append(f"data={attrs.get('data', '')}")
            elif typ in {"switch_inline_query", "switch_inline_query_current_chat"}:
                metadata.append(f"query={attrs.get('query', '')}")
            elif typ == "switch_inline_query_chosen_chat":
                metadata.append(f"query={attrs.get('query', '')}")
                for flag in (
                    "allow-user-chats", "allow-bot-chats",
                    "allow-group-chats", "allow-channel-chats",
                ):
                    if attrs.get(flag):
                        metadata.append(flag)
            elif typ == "disabled":
                metadata.append("disabled")
            adaptations.append("Ação exclusiva do Telegram é representada textualmente no Telegraph com seus parâmetros.")

        if metadata:
            body += " <code>[" + html.escape("; ".join(str(x) for x in metadata)) + "]</code>"
        rendered.append(body)
    if row_meta:
        rendered.insert(0, "<code>[button-row: " + html.escape("; ".join(row_meta)) + "]</code>")
    return "<p>" + "<br>".join(rendered) + "</p>" if rendered else ""


def _telegraph_html_table(
    blob: str,
    adaptations: list[str],
    unsupported: list[str],
) -> str:
    rows: list[str] = []
    structural_attrs = False
    opening = re.search(r"<table\b([^>]*)>", blob, re.I)
    table_attrs = _attrs(opening.group(1)) if opening else {}
    table_meta = [
        name if value is True else f"{name}={value}"
        for name, value in table_attrs.items()
        if value not in (None, False, "")
    ]
    if table_meta:
        adaptations.append("Atributos visuais ou estruturais da tabela sem equivalente no Telegraph são preservados textualmente.")
    caption_match = re.search(r"<caption\b[^>]*>(.*?)</caption>", blob, re.I | re.S)
    caption = ""
    if caption_match:
        caption = re.sub(r"<[^>]+>", "", _inline_telegraph(caption_match.group(1), adaptations, unsupported))
        caption = html.unescape(caption).strip()
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", blob, re.I | re.S):
        cells: list[str] = []
        for match in re.finditer(r"<(th|td)\b([^>]*)>(.*?)</\1>", row, re.I | re.S):
            tag, attrs_text, body = match.groups()
            attrs = _attrs(attrs_text)
            text = re.sub(r"</?p\b[^>]*>", "", body, flags=re.I)
            visible = re.sub(r"<[^>]+>", "", _inline_telegraph(text, adaptations, unsupported))
            visible = html.unescape(visible).strip()
            meta: list[str] = []
            if tag.lower() == "th":
                meta.append("header")
            for name in ("colspan", "rowspan", "align", "valign"):
                value = attrs.get(name)
                if value not in (None, False, "", "1", 1):
                    meta.append(f"{name}={value}")
                    structural_attrs = True
            cell = visible + (f" [{'; '.join(meta)}]" if meta else "")
            cells.append(cell)
        if cells:
            rows.append("\t".join(cells))
    adaptations.append("Tabela é representada de forma preformatada no Telegraph preservando linhas, colunas e células.")
    if structural_attrs:
        adaptations.append("Atributos estruturais da tabela sem equivalente nativo são preservados textualmente.")
    preface: list[str] = []
    if caption:
        preface.append(f"Legenda: {caption}")
    if table_meta:
        preface.append("[table: " + "; ".join(table_meta) + "]")
    return f"<pre>{html.escape(chr(10).join(preface + rows))}</pre>"


def _telegraph_media_element(
    blob: str,
    adaptations: list[str],
    unsupported: list[str],
    caption: str = "",
    credit: str = "",
) -> str:
    src_match = re.search(r'\bsrc=["\']([^"\']+)["\']', blob, re.I)
    if not src_match:
        return ""
    src = html.unescape(src_match.group(1))
    tag_match = re.search(r"<\s*([A-Za-z0-9-]+)", blob)
    tag = tag_match.group(1).lower() if tag_match else "media"

    remote = TG_REMOTE_MEDIA_RE.search(src)
    if remote or src.startswith("tg://"):
        unsupported.append("Mídia baseada em file_id/arquivo do Telegram não possui URL pública persistível no Telegraph.")
        info = f"mídia Telegram {tag}: {src}"
        body = f"<code>{html.escape(info)}</code>"
        legend = " — ".join(piece for piece in (caption, credit) if piece)
        if legend:
            body = f"<em>{html.escape(legend)}</em><br>{body}"
        return f"<p>{body}</p>"

    if not src.startswith(("http://", "https://")):
        unsupported.append("Mídia sem URL pública não pode ser persistida pelo Telegraph.")
        return f"<p><code>{html.escape(src)}</code></p>"

    safe = html.escape(src, quote=True)
    if tag == "img":
        node = f'<img src="{safe}">'
    elif tag in {"video"}:
        node = f'<video src="{safe}"></video>'
    else:
        adaptations.append("Áudio/documento por URL é representado como link no Telegraph.")
        label = html.escape(caption or "Abrir mídia")
        suffix = f" <em>— {html.escape(credit)}</em>" if credit else ""
        return f'<p><a href="{safe}">{label}</a>{suffix}</p>'
    if caption or credit:
        legend = html.escape(caption)
        if credit:
            legend += (" " if legend else "") + f"<em>— {html.escape(credit)}</em>"
        return f"<figure>{node}<figcaption>{legend}</figcaption></figure>"
    return node


def _telegraph_map_element(
    blob: str,
    adaptations: list[str],
    unsupported: list[str],
    caption: str = "",
    credit: str = "",
) -> str:
    match = re.search(r"<tg-map\b([^>]*)/?>", blob, re.I | re.S)
    if not match:
        return ""
    attrs = _attrs(match.group(1))
    lat = attrs.get("lat", attrs.get("latitude"))
    lon = attrs.get("long", attrs.get("longitude"))
    if lat in (None, False, "") or lon in (None, False, ""):
        unsupported.append("Mapa Rich sem latitude/longitude não pode ser projetado para o Telegraph.")
        return "<p><code>[mapa sem coordenadas]</code></p>"
    adaptations.append("Mapa Rich é representado por link de coordenadas no Telegraph.")
    url = f"https://maps.google.com/?q={lat},{lon}"
    zoom = attrs.get("zoom")
    if zoom not in (None, False, ""):
        url += f"&z={zoom}"
        adaptations.append("Zoom do mapa é preservado semanticamente no link e textualmente no Telegraph.")
    metadata: list[str] = []
    for name in ("zoom", "width", "height"):
        value = attrs.get(name)
        if value not in (None, False, ""):
            metadata.append(f"{name}={value}")
    if attrs.get("width") not in (None, False, "") or attrs.get("height") not in (None, False, ""):
        adaptations.append("Dimensões do mapa não são reproduzíveis no Telegraph; width/height são preservados textualmente.")
    label = caption or f"Mapa: {lat}, {lon}"
    body = f'<a href="{html.escape(url, quote=True)}">{_inline_telegraph(label, adaptations, unsupported)}</a>'
    if credit:
        body += f" <em>— {_inline_telegraph(credit, adaptations, unsupported)}</em>"
        adaptations.append("Crédito do mapa é preservado textualmente porque o Telegraph não possui campo equivalente.")
    if metadata:
        body += " <code>[" + html.escape("; ".join(metadata)) + "]</code>"
    return f"<p>{body}</p>"


def markdown_to_telegraph(source: str) -> TelegraphProjection:
    text = CanonicalDocument.from_markdown(source).markdown
    adaptations: list[str] = []
    unsupported: list[str] = []
    lines = text.split("\n")
    parts: list[str] = []
    para: list[str] = []
    i = 0

    def flush_para() -> None:
        if not para:
            return
        raw = " ".join(x.strip() for x in para if x.strip())
        para.clear()
        if raw:
            parts.append(f"<p>{_inline_telegraph(raw, adaptations, unsupported)}</p>")

    while i < len(lines):
        raw_line = lines[i]
        stripped = raw_line.strip()

        if stripped.startswith(("```", "~~~")):
            flush_para()
            marker = stripped[:3]
            language = stripped[3:].strip().lower()
            i += 1
            body: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith(marker):
                body.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            if language == "math":
                adaptations.append("Blocos matemáticos são publicados como preformatado no Telegraph.")
            parts.append(f"<pre>{html.escape(chr(10).join(body))}</pre>")
            continue

        if stripped == "$$" or stripped.startswith("$$"):
            flush_para()
            expr = stripped[2:]
            if stripped.endswith("$$") and len(stripped) > 4:
                expr = stripped[2:-2]
                i += 1
            else:
                i += 1
                body = [expr] if expr else []
                while i < len(lines) and "$$" not in lines[i]:
                    body.append(lines[i])
                    i += 1
                if i < len(lines):
                    tail = lines[i].split("$$", 1)[0]
                    if tail:
                        body.append(tail)
                    i += 1
                expr = "\n".join(body)
            adaptations.append("Fórmulas LaTeX são preservadas como preformatado no Telegraph.")
            parts.append(f"<pre>{html.escape(expr.strip())}</pre>")
            continue

        local = LOCAL_MEDIA_RE.fullmatch(stripped)
        if local:
            flush_para()
            alt, kind, media_id, caption = local.groups()
            caption = caption or alt or "Mídia"
            unsupported.append("Mídia de upload local não pode ser persistida pelo Telegraph sem hospedagem pública.")
            parts.append(
                f"<p><em>{html.escape(caption)}</em><br>"
                f"<code>[mídia local {html.escape(kind)}:{html.escape(media_id)}]</code></p>"
            )
            i += 1
            continue

        media = HTTP_MEDIA_RE.fullmatch(stripped)
        if media:
            flush_para()
            alt, url, caption = media.groups()
            caption = caption or alt or ""
            safe_url = html.escape(url, quote=True)
            kind = _media_kind_from_url(url)
            if kind == "image":
                node = f'<img src="{safe_url}">'
            elif kind == "video":
                node = f'<video src="{safe_url}"></video>'
            else:
                adaptations.append("Áudio/documento Rich por URL vira link no Telegraph.")
                parts.append(
                    f'<p><a href="{safe_url}">{html.escape(caption or "Abrir mídia")}</a></p>'
                )
                i += 1
                continue
            parts.append(
                f"<figure>{node}<figcaption>{html.escape(caption)}</figcaption></figure>"
                if caption else node
            )
            i += 1
            continue

        p_match = re.fullmatch(r"<p\b[^>]*>(.*?)</p>", stripped, re.I | re.S)
        if p_match:
            flush_para()
            parts.append(f"<p>{_inline_telegraph(p_match.group(1), adaptations, unsupported)}</p>")
            i += 1
            continue

        html_heading = re.fullmatch(r"<h([1-6])\b[^>]*>(.*?)</h\1>", stripped, re.I | re.S)
        if html_heading:
            flush_para()
            level = int(html_heading.group(1))
            tag = "h3" if level <= 2 else "h4"
            if level not in {3, 4}:
                adaptations.append("Heading sem nível nativo equivalente é remapeado deterministicamente no Telegraph.")
            parts.append(f"<{tag}>{_inline_telegraph(html_heading.group(2), adaptations, unsupported)}</{tag}>")
            i += 1
            continue

        if re.match(r"<blockquote\b", stripped, re.I):
            flush_para()
            blob, i = _collect_tag_block(lines, i, "</blockquote>")
            if re.search(r"<blockquote\b[^>]*\bexpandable\b", blob, re.I):
                adaptations.append("Citação expandível é publicada como citação normal no Telegraph.")
            inner = _strip_outer(blob, "blockquote")
            credit_match = re.search(r"<cite>(.*?)</cite>", inner, re.I | re.S)
            credit = credit_match.group(1).strip() if credit_match else ""
            inner = re.sub(r"<cite>.*?</cite>", "", inner, flags=re.I | re.S)
            inner = re.sub(r"</?p\b[^>]*>", "", inner, flags=re.I)
            rendered = _inline_telegraph(" ".join(inner.splitlines()), adaptations, unsupported)
            if credit:
                rendered += f" <em>— {_inline_telegraph(credit, adaptations, unsupported)}</em>"
            parts.append(f"<blockquote>{rendered}</blockquote>")
            continue

        if stripped.lower().startswith("<aside"):
            flush_para()
            blob, i = _collect_tag_block(lines, i, "</aside>")
            inner = _strip_outer(blob, "aside")
            credit_match = re.search(r"<cite>(.*?)</cite>", inner, re.I | re.S)
            credit = credit_match.group(1).strip() if credit_match else ""
            body = re.sub(r"<cite>.*?</cite>", "", inner, flags=re.I | re.S).strip()
            body = re.sub(r"</?p\b[^>]*>", "", body, flags=re.I)
            rendered = _inline_telegraph(body, adaptations, unsupported)
            if credit:
                rendered += f" <em>— {_inline_telegraph(credit, adaptations, unsupported)}</em>"
            parts.append(f"<aside>{rendered}</aside>")
            continue

        if stripped.lower().startswith("<details"):
            flush_para()
            blob, i = _collect_tag_block(lines, i, "</details>")
            adaptations.append("Blocos <details> são publicados expandidos no Telegraph.")
            summary = re.search(r"<summary>(.*?)</summary>", blob, re.I | re.S)
            if summary:
                parts.append(f"<h4>{_inline_telegraph(summary.group(1), adaptations, unsupported)}</h4>")
            body = re.sub(r"<summary>.*?</summary>", "", blob, flags=re.I | re.S)
            body = re.sub(r"</?details[^>]*>", "", body, flags=re.I).strip()
            if body:
                nested = markdown_to_telegraph(body)
                parts.append(nested.html)
                adaptations.extend(nested.adaptations)
                unsupported.extend(nested.unsupported)
            continue

        if stripped.lower().startswith("<table"):
            flush_para()
            blob, i = _collect_tag_block(lines, i, "</table>")
            parts.append(_telegraph_html_table(blob, adaptations, unsupported))
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            flush_para()
            table: list[str] = []
            while (
                i < len(lines)
                and lines[i].strip().startswith("|")
                and lines[i].strip().endswith("|")
            ):
                table.append(lines[i].rstrip())
                i += 1
            adaptations.append("Tabela GFM é preservada integralmente como preformatado no Telegraph.")
            parts.append(f"<pre>{html.escape(chr(10).join(table))}</pre>")
            continue

        if stripped.lower().startswith("<tg-button-row"):
            flush_para()
            blob, i = _collect_tag_block(lines, i, "</tg-button-row>")
            adaptations.append("Botões Rich são projetados para links ou representação textual no Telegraph.")
            rendered = _telegraph_button_row(blob, adaptations, unsupported)
            if rendered:
                parts.append(rendered)
            continue

        if stripped.lower().startswith(("<tg-collage", "<tg-slideshow")):
            flush_para()
            tag = "tg-collage" if stripped.lower().startswith("<tg-collage") else "tg-slideshow"
            blob, i = _collect_tag_block(lines, i, f"</{tag}>")
            inner = _strip_outer(blob, tag)
            adaptations.append(f"{tag} perde apenas o agrupamento nativo; todos os elementos são projetados individualmente.")
            nested = markdown_to_telegraph(inner)
            parts.append(nested.html)
            adaptations.extend(nested.adaptations)
            unsupported.extend(nested.unsupported)
            continue

        if stripped.lower().startswith("<figure"):
            flush_para()
            blob, i = _collect_tag_block(lines, i, "</figure>")
            caption_match = re.search(r"<figcaption>(.*?)</figcaption>", blob, re.I | re.S)
            caption_raw = caption_match.group(1) if caption_match else ""
            credit_match = re.search(r"<cite>(.*?)</cite>", caption_raw, re.I | re.S)
            credit_raw = credit_match.group(1) if credit_match else ""
            caption_body = re.sub(r"<cite>.*?</cite>", "", caption_raw, flags=re.I | re.S)
            caption = re.sub(r"<[^>]+>", "", caption_body).strip()
            credit = re.sub(r"<[^>]+>", "", credit_raw).strip()
            if credit:
                adaptations.append("Crédito de mídia é preservado textualmente porque o Telegraph não possui campo equivalente.")
            map_match = re.search(r"<tg-map\b[^>]*/?>", blob, re.I | re.S)
            media_match = re.search(
                r"(<(?:img|video|audio|tg-document)\b.*?(?:/>|</(?:video|audio|tg-document)>))",
                blob,
                re.I | re.S,
            )
            if map_match:
                parts.append(_telegraph_map_element(map_match.group(0), adaptations, unsupported, caption, credit))
            elif media_match:
                parts.append(_telegraph_media_element(media_match.group(1), adaptations, unsupported, caption, credit))
            elif caption or credit:
                parts.append(f"<p>{_inline_telegraph(caption_raw, adaptations, unsupported)}</p>")
            continue

        if re.match(r"<(?:img|video|audio|tg-document)\b", stripped, re.I):
            flush_para()
            blob = stripped
            if re.match(r"<(?:video|audio|tg-document)\b", stripped, re.I) and not re.search(
                r"</(?:video|audio|tg-document)>", stripped, re.I
            ):
                tag_match = re.match(r"<([A-Za-z0-9-]+)", stripped)
                tag = tag_match.group(1) if tag_match else "video"
                blob, i = _collect_tag_block(lines, i, f"</{tag}>")
            else:
                i += 1
            parts.append(_telegraph_media_element(blob, adaptations, unsupported))
            continue

        map_match = re.search(r"<tg-map\b[^>]*/?>", stripped, re.I | re.S)
        if map_match:
            flush_para()
            parts.append(_telegraph_map_element(map_match.group(0), adaptations, unsupported))
            i += 1
            continue

        if stripped.lower().startswith(("<ul", "<ol")):
            flush_para()
            tag = "ul" if stripped.lower().startswith("<ul") else "ol"
            blob, i = _collect_tag_block(lines, i, f"</{tag}>")
            items = []
            for item in re.findall(r"<li\b([^>]*)>(.*?)</li>", blob, re.I | re.S):
                attrs_text, body = item
                checked = bool(re.search(r"<input\b[^>]*\bchecked\b", body, re.I))
                has_checkbox = bool(re.search(r"<input\b[^>]*type=[\"\']checkbox[\"\']", body, re.I))
                body = re.sub(r"<input\b[^>]*>", "", body, flags=re.I)
                body = re.sub(r"</?p\b[^>]*>", "", body, flags=re.I)
                prefix = ("☑ " if checked else "☐ ") if has_checkbox else ""
                meta = _attrs(attrs_text)
                suffix = ""
                if tag == "ol" and (meta.get("value") or meta.get("type")):
                    suffix = f" <code>[value={html.escape(str(meta.get('value') or ''))}; type={html.escape(str(meta.get('type') or ''))}]</code>"
                    adaptations.append("Metadados de numeração de lista são preservados textualmente no Telegraph.")
                items.append(f"<li>{prefix}{_inline_telegraph(body, adaptations, unsupported)}{suffix}</li>")
            parts.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue

        footer_match = re.fullmatch(r"<footer>(.*?)</footer>", stripped, re.I | re.S)
        if footer_match:
            flush_para()
            adaptations.append("Rodapé Rich é preservado como parágrafo enfatizado no Telegraph.")
            parts.append(f"<p><em>{_inline_telegraph(footer_match.group(1), adaptations, unsupported)}</em></p>")
            i += 1
            continue

        if re.match(r"^(---+|\*\*\*+)$", stripped):
            flush_para()
            parts.append("<hr>")
            i += 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            flush_para()
            level = len(heading.group(1))
            tag = "h3" if level <= 2 else "h4"
            if level not in {3, 4}:
                adaptations.append("Heading sem nível nativo equivalente é remapeado deterministicamente no Telegraph.")
            parts.append(f"<{tag}>{_inline_telegraph(heading.group(2), adaptations, unsupported)}</{tag}>")
            i += 1
            continue

        if stripped.startswith(">"):
            flush_para()
            quote: list[str] = []
            while i < len(lines) and (lines[i].strip().startswith(">") or not lines[i].strip()):
                current = lines[i].strip()
                if current.startswith(">"):
                    quote.append(current[1:].lstrip())
                elif quote:
                    quote.append("")
                i += 1
            parts.append(
                f"<blockquote>{_inline_telegraph(' '.join(quote).strip(), adaptations, unsupported)}</blockquote>"
            )
            continue

        list_match = re.match(r"^([-*+]|\d+\.)\s+(.*)$", stripped)
        if list_match:
            flush_para()
            ordered = list_match.group(1)[0].isdigit()
            items: list[str] = []
            while i < len(lines):
                cur = lines[i].strip()
                task = re.match(r"^[-*+]\s+\[([ xX])\]\s+(.*)$", cur)
                ul = re.match(r"^[-*+]\s+(.*)$", cur)
                ol = re.match(r"^\d+\.\s+(.*)$", cur)
                if task and not ordered:
                    mark = "☑" if task.group(1).lower() == "x" else "☐"
                    items.append(f"<li>{mark} {_inline_telegraph(task.group(2), adaptations, unsupported)}</li>")
                elif ul and not ordered:
                    items.append(f"<li>{_inline_telegraph(ul.group(1), adaptations, unsupported)}</li>")
                elif ol and ordered:
                    items.append(f"<li>{_inline_telegraph(ol.group(1), adaptations, unsupported)}</li>")
                else:
                    break
                i += 1
            tag = "ol" if ordered else "ul"
            parts.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue

        if not stripped:
            flush_para()
            i += 1
            continue

        para.append(stripped)
        i += 1

    flush_para()
    return TelegraphProjection(
        "".join(parts).strip() or "<p></p>",
        _unique(adaptations),
        _unique(unsupported),
    )
