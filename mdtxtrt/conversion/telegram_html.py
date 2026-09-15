from __future__ import annotations

from html import escape
import re


def _attrs(values: dict[str, object]) -> str:
    out = []
    for key, value in values.items():
        if value is None or value is False or value == "":
            continue
        if value is True:
            out.append(key)
        else:
            out.append(f'{key}="{escape(str(value), quote=True)}"')
    return (" " + " ".join(out)) if out else ""


def _text(value) -> str:
    return escape(str(value or ""), quote=False)


def node_to_html(node: dict) -> str:
    typ = node.get("type")
    if typ == "paragraph":
        return f"<p>{node.get('html') or ''}</p>"
    if typ == "heading":
        level = min(6, max(1, int(node.get("level") or 1)))
        return f"<h{level}>{node.get('html') or ''}</h{level}>"
    if typ == "blockquote":
        attrs = " expandable" if node.get("expandable") else ""
        credit = str(node.get("credit") or "")
        return f"<blockquote{attrs}>{node.get('html') or ''}" + (f"<cite>{_text(credit)}</cite>" if credit else "") + "</blockquote>"
    if typ == "pullquote":
        credit = str(node.get("credit") or "")
        return f"<aside>{node.get('html') or ''}" + (f"<cite>{_text(credit)}</cite>" if credit else "") + "</aside>"
    if typ == "details":
        attrs = " open" if node.get("open") else ""
        return f"<details{attrs}><summary>{node.get('summary_html') or ''}</summary>{node.get('html') or ''}</details>"
    if typ == "code":
        language = re.sub(r"[^A-Za-z0-9_+.-]", "", str(node.get("language") or ""))
        body = _text(node.get("text") or "")
        if language:
            return f'<pre><code class="language-{escape(language, quote=True)}">{body}</code></pre>'
        return f"<pre>{body}</pre>"
    if typ == "math":
        expression = _text(node.get("expression") or "")
        return f"<tg-math-block>{expression}</tg-math-block>" if node.get("display", True) else f"<p><tg-math>{expression}</tg-math></p>"
    if typ == "divider":
        return "<hr/>"
    if typ == "footer":
        return f"<footer>{node.get('html') or ''}</footer>"
    if typ == "anchor":
        return f'<a name="{escape(str(node.get("name") or ""), quote=True)}"></a>'
    if typ == "list":
        tag = "ol" if node.get("ordered") else "ul"
        items = []
        for item in node.get("items") or []:
            checked = item.get("checked") if isinstance(item, dict) else None
            checkbox = ""
            if checked is not None:
                checkbox = "<input type=\"checkbox\" checked>" if checked else "<input type=\"checkbox\">"
            html = item.get("html") if isinstance(item, dict) else _text(item)
            items.append(f"<li>{checkbox}{html or ''}</li>")
        return f"<{tag}>" + "".join(items) + f"</{tag}>"
    if typ == "table":
        attrs = _attrs({"bordered": bool(node.get("bordered")), "striped": bool(node.get("striped")), "compact": bool(node.get("compact"))})
        caption = str(node.get("caption") or "")
        rows = []
        for row in node.get("rows") or []:
            cells = []
            for cell in row:
                value = cell if isinstance(cell, dict) else {"text": cell}
                tag = "th" if value.get("header") else "td"
                cell_attrs = _attrs({
                    "colspan": value.get("colspan"),
                    "rowspan": value.get("rowspan"),
                    "align": value.get("align"),
                    "valign": value.get("valign"),
                })
                body = value.get("html") if value.get("html") is not None else _text(value.get("text") or "")
                cells.append(f"<{tag}{cell_attrs}>{body}</{tag}>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
        return f"<table{attrs}>" + (f"<caption>{_text(caption)}</caption>" if caption else "") + "".join(rows) + "</table>"
    if typ == "map":
        attrs = _attrs({"lat": node.get("latitude"), "long": node.get("longitude"), "zoom": node.get("zoom")})
        map_html = f"<tg-map{attrs}/>"
        caption = " · ".join(part for part in (str(node.get("name") or "").strip(), str(node.get("address") or "").strip()) if part)
        return f"<figure>{map_html}<figcaption>{_text(caption)}</figcaption></figure>" if caption else map_html
    if typ == "media":
        kind = str(node.get("kind") or "document").lower()
        source = str(node.get("url") or "")
        blob_id = str(node.get("blob_id") or "")
        if blob_id:
            if kind in {"photo", "image"}:
                source = f"tg://photo?id={blob_id}"
            elif kind in {"video", "animation"}:
                source = f"tg://video?id={blob_id}"
            elif kind in {"audio", "voice", "voice_note"}:
                source = f"tg://audio?id={blob_id}"
            else:
                source = f"tg://document?id={blob_id}"
        src = escape(source, quote=True)
        if kind in {"photo", "image"}:
            tag = f'<img src="{src}"/>'
        elif kind in {"video", "animation"}:
            tag = f'<video src="{src}"></video>'
        elif kind in {"audio", "voice", "voice_note"}:
            tag = f'<audio src="{src}"></audio>'
        else:
            tag = f'<tg-document src="{src}"></tg-document>'
        caption = str(node.get("caption") or "")
        credit = str(node.get("credit") or "")
        if caption or credit:
            return f"<figure>{tag}<figcaption>{_text(caption)}" + (f"<cite>{_text(credit)}</cite>" if credit else "") + "</figcaption></figure>"
        return tag
    if typ == "buttons":
        align = str(node.get("align") or "")
        attrs = _attrs({"align": align})
        rendered = []
        for button in node.get("items") or node.get("buttons") or []:
            if not isinstance(button, dict):
                continue
            button_type = str(button.get("type") or "url")
            values = {"type": button_type, "style": button.get("style")}
            if button_type in {"url", "web_app", "login_url"}:
                values["url"] = button.get("url")
            elif button_type == "callback_data":
                values["data"] = button.get("data")
            elif button_type == "copy_text":
                values["text"] = button.get("copy_text") or button.get("text")
            elif button_type.startswith("switch_inline_query"):
                values["query"] = button.get("query")
            label = button.get("html") or _text(button.get("label") or button.get("text") or "Botão")
            rendered.append(f"<tg-button{_attrs(values)}>{label}</tg-button>")
        return f"<tg-button-row{attrs}>" + "".join(rendered) + "</tg-button-row>"
    if typ == "raw_markdown":
        return str(node.get("raw") or "")
    return f"<p>{_text(node)}</p>"


def to_html(document: dict) -> str:
    return "\n".join(node_to_html(node) for node in document.get("nodes") or [])
