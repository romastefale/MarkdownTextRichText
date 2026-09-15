from __future__ import annotations

from html import escape, unescape
import hashlib
import json
from html.parser import HTMLParser
import re

from mdtxtrt.domain.document import make_node, new_document, normalize_document

FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
HR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
LIST_RE = re.compile(r"^(\s*)([-+*]|\d+[.)])\s+(.*)$")
TABLE_DIVIDER_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
MEDIA_RE = re.compile(r'^!\[([^\]]*)\]\(([^\s)]+)(?:\s+"([^"]*)")?\)\s*$')
KNOWN_RICH_START = re.compile(r"^\s*<(table|details|blockquote|aside|figure|tg-button-row|tg-map|tg-collage|tg-slideshow|footer|tg-math-block)\b", re.I)
MARKDOWN_HINT = re.compile(r"(^|\n)\s*(#{1,6}\s|>|[-+*]\s|\d+[.)]\s|```|~~~)|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\)|<u>.*?</u>|<tg-", re.S)


def looks_like_markdown(text: str) -> bool:
    return bool(MARKDOWN_HINT.search(text or ""))


def _inline_html(source: str) -> str:
    text = escape(source or "", quote=False)
    placeholders: dict[str, str] = {}

    def hold(value: str) -> str:
        key = f"\x00m{len(placeholders)}\x00"
        placeholders[key] = value
        return key

    text = re.sub(r"`([^`\n]*)`", lambda m: hold(f"<code>{m.group(1)}</code>"), text)
    text = re.sub(r"!\[([^\]]*)\]\(tg://emoji\?id=([^)]+)\)", lambda m: hold(f'<span data-tg-emoji="{escape(unescape(m.group(2)), quote=True)}">{m.group(1)}</span>'), text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: hold(f'<a href="{escape(unescape(m.group(2)), quote=True)}">{m.group(1)}</a>'), text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    text = re.sub(r"==(.+?)==", r"<mark>\1</mark>", text)
    text = re.sub(r"\|\|(.+?)\|\|", r'<span data-spoiler="1">\1</span>', text)
    text = re.sub(r"&lt;u&gt;(.*?)&lt;/u&gt;", r"<u>\1</u>", text, flags=re.S)
    text = re.sub(r"&lt;sub&gt;(.*?)&lt;/sub&gt;", r"<sub>\1</sub>", text, flags=re.S)
    text = re.sub(r"&lt;sup&gt;(.*?)&lt;/sup&gt;", r"<sup>\1</sup>", text, flags=re.S)
    for key, value in placeholders.items():
        text = text.replace(key, value)
    return text


class _InlineMarkdown(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        at = dict(attrs)
        wrappers = {
            "strong": "**", "b": "**", "em": "*", "i": "*", "u": "<u>",
            "s": "~~", "strike": "~~", "del": "~~", "mark": "==", "sub": "<sub>",
            "sup": "<sup>", "code": "`",
        }
        if tag in wrappers:
            token = wrappers[tag]
            self.out.append(token)
            closing = {"<u>": "</u>", "<sub>": "</sub>", "<sup>": "</sup>"}.get(token, token)
            self.stack.append((tag, closing))
            return
        if tag == "a":
            self.stack.append((tag, f"]({at.get('href') or ''})"))
            self.out.append("[")
            return
        if tag == "span" and at.get("data-spoiler") == "1":
            self.out.append("||")
            self.stack.append((tag, "||"))
            return
        if tag == "br":
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                _, closing = self.stack.pop(index)
                self.out.append(closing)
                return

    def handle_data(self, data: str) -> None:
        self.out.append(data)


def inline_html_to_markdown(value: str) -> str:
    parser = _InlineMarkdown()
    parser.feed(value or "")
    parser.close()
    return "".join(parser.out)


def _collect_html_block(lines: list[str], start: int) -> tuple[str, int]:
    first = lines[start]
    match = KNOWN_RICH_START.match(first)
    if not match:
        return first, start + 1
    tag = match.group(1).lower()
    if tag == "tg-map" and "/>" in first:
        return first, start + 1
    if tag in {"footer", "tg-math-block"} and f"</{tag}>" in first.lower():
        return first, start + 1
    depth = 0
    out: list[str] = []
    open_re = re.compile(rf"<{re.escape(tag)}\b", re.I)
    close_re = re.compile(rf"</{re.escape(tag)}\s*>", re.I)
    for index in range(start, len(lines)):
        line = lines[index]
        depth += len(open_re.findall(line))
        depth -= len(close_re.findall(line))
        out.append(line)
        if depth <= 0 and index > start or close_re.search(line):
            return "\n".join(out), index + 1
    return "\n".join(out), len(lines)


def _split_table_row(line: str) -> list[str]:
    value = line.strip().strip("|")
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", value)]


def _raw_suggestion(raw: str) -> dict:
    lower = raw.lstrip().lower()
    mapping = [
        ("<table", "table"), ("<details", "details"), ("<blockquote", "blockquote"),
        ("<aside", "pullquote"), ("<figure", "media"), ("<tg-button-row", "buttons"),
        ("<tg-map", "map"), ("<tg-math-block", "math"), ("<footer", "footer"),
    ]
    for prefix, typ in mapping:
        if lower.startswith(prefix):
            return {"recommended_type": typ, "message": f"Converter este Markdown Rich para bloco visual {typ}."}
    return {"recommended_type": "paragraph", "message": "Preservar cru ou converter para parágrafo visual após revisão."}




def _nodes_fingerprint(nodes: list) -> str:
    raw = json.dumps(nodes, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _remember_source(document: dict, source: str, source_format: str) -> dict:
    value = normalize_document(document)
    metadata = value.setdefault("metadata", {})
    metadata["source_format"] = source_format
    metadata["source_text"] = source
    metadata["source_nodes_sha256"] = _nodes_fingerprint(value.get("nodes") or [])
    return value


def _unchanged_source(document: dict, source_format: str) -> str | None:
    metadata = document.get("metadata") if isinstance(document, dict) else None
    if not isinstance(metadata, dict) or metadata.get("source_format") != source_format:
        return None
    source = metadata.get("source_text")
    expected = metadata.get("source_nodes_sha256")
    if not isinstance(source, str) or not isinstance(expected, str):
        return None
    if _nodes_fingerprint(document.get("nodes") or []) != expected:
        return None
    return source
def import_markdown(source: str) -> tuple[dict, dict]:
    text = (source or "").replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.split("\n")
    document = new_document()
    nodes: list[dict] = []
    warnings: list[dict] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            language = fence.group(2).strip()
            body: list[str] = []
            index += 1
            while index < len(lines) and not re.match(rf"^\s*{re.escape(marker[0])}{{{len(marker)},}}\s*$", lines[index]):
                body.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            nodes.append(make_node("code", text="\n".join(body), language=language or None))
            continue
        heading = HEADING_RE.match(line)
        if heading:
            nodes.append(make_node("heading", level=len(heading.group(1)), html=_inline_html(heading.group(2))))
            index += 1
            continue
        if HR_RE.match(line):
            nodes.append(make_node("divider"))
            index += 1
            continue
        media = MEDIA_RE.match(line)
        if media:
            alt, url, title = media.groups()
            nodes.append(make_node("media", kind="auto", url=url, caption=title or alt or "", name=alt or ""))
            index += 1
            continue
        if line.strip() == "$$":
            body = []
            index += 1
            while index < len(lines) and lines[index].strip() != "$$":
                body.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            nodes.append(make_node("math", expression="\n".join(body), display=True))
            continue
        if TABLE_DIVIDER_RE.match(lines[index + 1]) if index + 1 < len(lines) else False:
            headers = _split_table_row(line)
            rows = [[{"text": cell, "header": True} for cell in headers]]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append([{"text": cell, "header": False} for cell in _split_table_row(lines[index])])
                index += 1
            nodes.append(make_node("table", rows=rows, bordered=True, striped=False, compact=False, caption=""))
            continue
        if line.lstrip().startswith(">"):
            body = []
            while index < len(lines) and lines[index].lstrip().startswith(">"):
                body.append(re.sub(r"^\s*>\s?", "", lines[index]))
                index += 1
            nodes.append(make_node("blockquote", html=_inline_html("\n".join(body)), credit=""))
            continue
        list_match = LIST_RE.match(line)
        if list_match:
            ordered = list_match.group(2)[0].isdigit()
            items = []
            while index < len(lines):
                current = LIST_RE.match(lines[index])
                if not current or current.group(2)[0].isdigit() != ordered:
                    break
                raw_item = current.group(3)
                checked = None
                task = re.match(r"^\[([ xX])\]\s+(.*)$", raw_item)
                if task:
                    checked = task.group(1).lower() == "x"
                    raw_item = task.group(2)
                items.append({"id": make_node("paragraph")["id"], "html": _inline_html(raw_item), "checked": checked})
                index += 1
            nodes.append(make_node("list", ordered=ordered, items=items))
            continue
        if KNOWN_RICH_START.match(line):
            raw, index = _collect_html_block(lines, index)
            suggestion = _raw_suggestion(raw)
            nodes.append(make_node("raw_markdown", raw=raw, suggestion=suggestion, reason="rich_structure_requires_visual_confirmation"))
            warnings.append({"type": "raw_preserved", "message": suggestion["message"], "raw": raw})
            continue
        paragraph = [line]
        index += 1
        while index < len(lines) and lines[index].strip():
            if FENCE_RE.match(lines[index]) or HEADING_RE.match(lines[index]) or HR_RE.match(lines[index]) or LIST_RE.match(lines[index]) or KNOWN_RICH_START.match(lines[index]):
                break
            if index + 1 < len(lines) and TABLE_DIVIDER_RE.match(lines[index + 1]):
                break
            paragraph.append(lines[index])
            index += 1
        nodes.append(make_node("paragraph", html=_inline_html("\n".join(paragraph))))
    document["nodes"] = nodes
    document = _remember_source(document, source or "", "markdown")
    report = {
        "ok": True,
        "format": "markdown",
        "warnings": warnings,
        "partial": bool(warnings),
        "node_count": len(nodes),
    }
    return document, report


def import_literal_text(source: str) -> tuple[dict, dict]:
    original = source or ""
    document = new_document()
    normalized = original.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = re.split(r"\n\s*\n", normalized)
    document["nodes"] = [make_node("paragraph", html=escape(value, quote=False).replace("\n", "<br>")) for value in paragraphs if value != ""]
    document = _remember_source(document, original, "literal")
    return document, {"ok": True, "format": "text", "warnings": [], "partial": False, "node_count": len(document["nodes"])}


def _table_markdown(node: dict) -> str:
    rows = node.get("rows") or []
    if not rows:
        return ""
    def cell_text(cell):
        value = cell.get("text") if isinstance(cell, dict) else cell
        return str(value or "").replace("|", "\\|")
    first = rows[0]
    out = ["| " + " | ".join(cell_text(cell) for cell in first) + " |"]
    out.append("| " + " | ".join("---" for _ in first) + " |")
    for row in rows[1:]:
        out.append("| " + " | ".join(cell_text(cell) for cell in row) + " |")
    return "\n".join(out)


def node_to_markdown(node: dict) -> str:
    typ = node.get("type")
    if typ == "paragraph":
        return inline_html_to_markdown(str(node.get("html") or ""))
    if typ == "heading":
        level = min(6, max(1, int(node.get("level") or 1)))
        return "#" * level + " " + inline_html_to_markdown(str(node.get("html") or ""))
    if typ == "blockquote":
        body = inline_html_to_markdown(str(node.get("html") or ""))
        credit = str(node.get("credit") or "").strip()
        if credit:
            return f"<blockquote>\n{body}\n<cite>{credit}</cite>\n</blockquote>"
        return "\n".join("> " + line for line in body.split("\n"))
    if typ == "pullquote":
        body = inline_html_to_markdown(str(node.get("html") or ""))
        credit = str(node.get("credit") or "").strip()
        return f"<aside>\n{body}" + (f"\n<cite>{credit}</cite>" if credit else "") + "\n</aside>"
    if typ == "code":
        language = str(node.get("language") or "")
        return f"```{language}\n{node.get('text') or ''}\n```"
    if typ == "math":
        expression = str(node.get("expression") or "")
        return f"<tg-math-block>{expression}</tg-math-block>" if node.get("display", True) else f"$${expression}$$"
    if typ == "divider":
        return "---"
    if typ == "footer":
        return f"<footer>{inline_html_to_markdown(str(node.get('html') or ''))}</footer>"
    if typ == "anchor":
        return f'<a name="{str(node.get("name") or "")}"></a>'
    if typ == "raw_markdown":
        return str(node.get("raw") or "")
    if typ == "list":
        out = []
        ordered = bool(node.get("ordered"))
        for idx, item in enumerate(node.get("items") or [], 1):
            prefix = f"{idx}." if ordered else "-"
            checked = item.get("checked") if isinstance(item, dict) else None
            marker = ""
            if checked is not None:
                marker = "[x] " if checked else "[ ] "
            html = item.get("html") if isinstance(item, dict) else str(item)
            out.append(f"{prefix} {marker}{inline_html_to_markdown(str(html or ''))}")
        return "\n".join(out)
    if typ == "table":
        return _table_markdown(node)
    if typ == "details":
        summary = inline_html_to_markdown(str(node.get("summary_html") or node.get("summary") or ""))
        body = "\n\n".join(node_to_markdown(child) for child in node.get("children") or [])
        opened = " open" if node.get("open") else ""
        return f"<details{opened}>\n<summary>{summary}</summary>\n{body}\n</details>"
    if typ == "map":
        attrs = [f'lat="{node.get("latitude")}"', f'long="{node.get("longitude")}"']
        if node.get("zoom") is not None:
            attrs.append(f'zoom="{int(node["zoom"])}"')
        name = str(node.get("name") or "").strip()
        address = str(node.get("address") or "").strip()
        meta = ""
        if name or address:
            meta = " data-name=\"" + escape(name, quote=True) + "\" data-address=\"" + escape(address, quote=True) + "\""
        return "<tg-map " + " ".join(attrs) + meta + "/>"
    if typ == "media":
        url = str(node.get("url") or "")
        blob_id = str(node.get("blob_id") or "")
        kind = str(node.get("kind") or "photo")
        caption = str(node.get("caption") or node.get("name") or "")
        if blob_id:
            return f'![{caption}](mdtxtrt://{kind}/{blob_id})'
        return f'![{caption}]({url})' if url else f'[{caption or "Mídia"}]'
    if typ == "buttons":
        rows = node.get("rows") or []
        out = [f'<tg-button-row align="{escape(str(node.get("align") or "center"), quote=True)}">']
        for row in rows:
            for button in row if isinstance(row, list) else [row]:
                attrs = []
                typb = str(button.get("type") or "url")
                attrs.append(f'type="{escape(typb, quote=True)}"')
                for source, target in [("url", "url"), ("data", "data"), ("style", "style"), ("query", "query"), ("copy_text", "text")]:
                    value = button.get(source)
                    if value not in (None, ""):
                        attrs.append(f'{target}="{escape(str(value), quote=True)}"')
                out.append("<tg-button " + " ".join(attrs) + ">" + inline_html_to_markdown(str(button.get("html") or button.get("text") or "Botão")) + "</tg-button>")
        out.append("</tg-button-row>")
        return "\n".join(out)
    return str(node.get("raw") or "")


def to_markdown(document: dict) -> str:
    original = _unchanged_source(document, "markdown")
    if original is not None:
        return original
    value = normalize_document(document)
    return "\n\n".join(part for part in (node_to_markdown(node) for node in value.get("nodes") or []) if part != "")
