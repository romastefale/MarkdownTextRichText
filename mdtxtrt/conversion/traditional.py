from __future__ import annotations

from html import escape
import re

from mdtxtrt.domain.document import plain_text


ADVANCED_NODE_TYPES = {
    "heading", "details", "math", "table", "media", "map", "buttons", "anchor",
    "pullquote", "footer",
}


def traditional_compatibility(document: dict) -> tuple[bool, list[str]]:
    """Return whether the document can use traditional Telegram parse modes without structural loss."""
    warnings: list[str] = []
    for node in document.get("nodes") or []:
        typ = str(node.get("type") or "")
        if typ in ADVANCED_NODE_TYPES:
            warnings.append(f"Estrutura `{typ}` exige Rich Message para preservar a semântica.")
        if typ == "list":
            for item in node.get("items") or []:
                if isinstance(item, dict) and item.get("checked") is not None:
                    warnings.append("Lista de tarefas exige Rich Message para preservar o estado do checkbox.")
                    break
        if typ == "blockquote" and node.get("expandable"):
            warnings.append("Citação expansível exige Rich Message.")
    return not warnings, warnings


def _strip_tags(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.I)
    return re.sub(r"<[^>]+>", "", value)


def to_traditional_html(document: dict) -> str:
    """Telegram HTML fallback for the subset that traditional messages can represent safely."""
    compatible, warnings = traditional_compatibility(document)
    if not compatible:
        raise ValueError("Documento exige Rich Message: " + " ".join(warnings))
    out: list[str] = []
    for node in document.get("nodes") or []:
        typ = node.get("type")
        if typ == "paragraph":
            out.append(str(node.get("html") or ""))
        elif typ == "blockquote":
            out.append(f"<blockquote>{node.get('html') or ''}</blockquote>")
        elif typ == "code":
            language = re.sub(r"[^A-Za-z0-9_+.-]", "", str(node.get("language") or ""))
            body = escape(str(node.get("text") or ""), quote=False)
            out.append(f'<pre><code class="language-{language}">{body}</code></pre>' if language else f"<pre>{body}</pre>")
        elif typ == "list":
            ordered = bool(node.get("ordered"))
            for index, item in enumerate(node.get("items") or [], 1):
                html = item.get("html") if isinstance(item, dict) else escape(str(item), quote=False)
                out.append(f"{index}. {html}" if ordered else f"• {html}")
        elif typ == "divider":
            out.append("—")
        elif typ == "raw_markdown":
            out.append(escape(str(node.get("raw") or ""), quote=False))
        else:
            text = plain_text({"nodes": [node]})
            if text:
                out.append(escape(text, quote=False))
    return "\n".join(part for part in out if part != "")


_MD_V2_SPECIAL = re.compile(r"([_\*\[\]()~`>#+\-=|{}.!\\])")


def _escape_v2(value: str) -> str:
    return _MD_V2_SPECIAL.sub(r"\\\1", value)


def to_markdown_v2(document: dict) -> str:
    """Conservative MarkdownV2 fallback. Advanced structures are rejected instead of flattened silently."""
    compatible, warnings = traditional_compatibility(document)
    if not compatible:
        raise ValueError("Documento exige Rich Message: " + " ".join(warnings))
    out: list[str] = []
    for node in document.get("nodes") or []:
        typ = node.get("type")
        if typ == "paragraph":
            out.append(_escape_v2(_strip_tags(str(node.get("html") or ""))))
        elif typ == "blockquote":
            text = _escape_v2(_strip_tags(str(node.get("html") or "")))
            out.extend("> " + line for line in text.splitlines() or [""])
        elif typ == "code":
            language = re.sub(r"[^A-Za-z0-9_+.-]", "", str(node.get("language") or ""))
            body = str(node.get("text") or "").replace("\\", "\\\\").replace("`", "\\`")
            out.append(f"```{language}\n{body}\n```")
        elif typ == "list":
            ordered = bool(node.get("ordered"))
            for index, item in enumerate(node.get("items") or [], 1):
                text = item.get("html") if isinstance(item, dict) else str(item)
                text = _escape_v2(_strip_tags(str(text or "")))
                out.append(f"{index}\\. {text}" if ordered else f"• {text}")
        elif typ == "divider":
            out.append("—")
        elif typ == "raw_markdown":
            out.append(_escape_v2(str(node.get("raw") or "")))
        else:
            text = plain_text({"nodes": [node]})
            if text:
                out.append(_escape_v2(text))
    return "\n".join(part for part in out if part != "")
