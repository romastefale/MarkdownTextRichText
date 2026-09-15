from __future__ import annotations

from html import unescape
import re


def _visible_html(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text)


def apply_projection_corrections() -> None:
    """Keep canonical editor fields aligned with the Markdown projection used by Rich Message blocks."""
    from mdtxtrt.conversion import markdown as module

    original_node_to_markdown = module.node_to_markdown

    def node_to_markdown(node: dict) -> str:
        typ = node.get("type")
        if typ == "details":
            summary = module.inline_html_to_markdown(str(node.get("summary_html") or node.get("summary") or ""))
            if node.get("children"):
                body = "\n\n".join(node_to_markdown(child) for child in node.get("children") or [])
            else:
                body = module.inline_html_to_markdown(str(node.get("html") or ""))
            opened = " open" if node.get("open") else ""
            return f"<details{opened}>\n<summary>{summary}</summary>\n{body}\n</details>"
        if typ == "buttons":
            rows = node.get("rows")
            if not rows:
                items = node.get("items") or node.get("buttons") or []
                rows = [items] if items else []
            out = [f'<tg-button-row align="{module.escape(str(node.get("align") or "center"), quote=True)}">']
            for row in rows:
                for button in row if isinstance(row, list) else [row]:
                    if not isinstance(button, dict):
                        continue
                    attrs = []
                    typb = str(button.get("type") or "url")
                    attrs.append(f'type="{module.escape(typb, quote=True)}"')
                    for source, target in (("url", "url"), ("data", "data"), ("style", "style"), ("query", "query"), ("copy_text", "text")):
                        value = button.get(source)
                        if value not in (None, ""):
                            attrs.append(f'{target}="{module.escape(str(value), quote=True)}"')
                    label = module.inline_html_to_markdown(str(button.get("html") or button.get("text") or "Botão"))
                    out.append("<tg-button " + " ".join(attrs) + ">" + label + "</tg-button>")
            out.append("</tg-button-row>")
            return "\n".join(out)
        if typ == "table":
            rows = node.get("rows") or []
            if not rows:
                return ""
            def cell_text(cell):
                if isinstance(cell, dict):
                    value = cell.get("text")
                    if value in (None, "") and cell.get("html") not in (None, ""):
                        value = _visible_html(str(cell.get("html") or ""))
                else:
                    value = cell
                return str(value or "").replace("|", "\\|")
            first = rows[0]
            out = ["| " + " | ".join(cell_text(cell) for cell in first) + " |"]
            out.append("| " + " | ".join("---" for _ in first) + " |")
            out.extend("| " + " | ".join(cell_text(cell) for cell in row) + " |" for row in rows[1:])
            return "\n".join(out)
        return original_node_to_markdown(node)

    module.node_to_markdown = node_to_markdown
