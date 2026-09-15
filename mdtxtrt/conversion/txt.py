from __future__ import annotations

import re

from mdtxtrt.conversion.markdown import _unchanged_source, inline_html_to_markdown
from mdtxtrt.domain.document import normalize_document


def _plain_inline(value: str) -> str:
    markdown = inline_html_to_markdown(value or "")
    markdown = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", markdown)
    markdown = re.sub(r"[*_~=`|]+", "", markdown)
    markdown = re.sub(r"</?(?:u|sub|sup)>", "", markdown)
    return markdown


def _ascii_table(rows: list) -> str:
    if not rows:
        return ""
    matrix = []
    width = max(len(row) for row in rows)
    for row in rows:
        values = []
        for cell in row:
            text = cell.get("text") if isinstance(cell, dict) else cell
            values.append(str(text or "").replace("\n", " "))
        values += [""] * (width - len(values))
        matrix.append(values)
    sizes = [max(len(row[index]) for row in matrix) for index in range(width)]
    rule = "+" + "+".join("-" * (size + 2) for size in sizes) + "+"
    out = [rule]
    for idx, row in enumerate(matrix):
        out.append("|" + "|".join(" " + row[col].ljust(sizes[col]) + " " for col in range(width)) + "|")
        if idx == 0:
            out.append(rule)
    if out[-1] != rule:
        out.append(rule)
    return "\n".join(out)


def to_txt(document: dict) -> tuple[str, list[dict]]:
    original = _unchanged_source(document, "literal")
    if original is not None:
        return original, []
    value = normalize_document(document)
    out: list[str] = []
    warnings: list[dict] = []
    for node in value.get("nodes") or []:
        typ = node.get("type")
        if typ in {"paragraph", "heading", "blockquote", "pullquote", "footer"}:
            out.append(_plain_inline(str(node.get("html") or "")))
        elif typ == "code":
            out.append(str(node.get("text") or ""))
        elif typ == "math":
            out.append(str(node.get("expression") or ""))
        elif typ == "divider":
            out.append("-" * 40)
        elif typ == "list":
            for idx, item in enumerate(node.get("items") or [], 1):
                prefix = f"{idx}." if node.get("ordered") else "-"
                checked = item.get("checked") if isinstance(item, dict) else None
                marker = ""
                if checked is not None:
                    marker = "[x] " if checked else "[ ] "
                out.append(f"{prefix} {marker}{_plain_inline(str(item.get('html') or ''))}")
        elif typ == "table":
            out.append(_ascii_table(node.get("rows") or []))
            warnings.append({"node_id": node.get("id"), "type": "adaptation", "message": "Tabela convertida para ASCII no TXT.", "recommended": "ascii"})
        elif typ == "map":
            name = str(node.get("name") or "").strip()
            address = str(node.get("address") or "").strip()
            coords = f"{node.get('latitude')}, {node.get('longitude')}"
            out.append(" — ".join(part for part in [name, address, coords] if part))
            warnings.append({"node_id": node.get("id"), "type": "adaptation", "message": "Mapa convertido para nome/endereço/coordenadas.", "recommended": "text_coordinates"})
        elif typ == "media":
            name = str(node.get("name") or node.get("caption") or "Mídia")
            url = str(node.get("url") or "")
            out.append(name + (f" — {url}" if url else ""))
            if not url:
                warnings.append({"node_id": node.get("id"), "type": "requires_confirmation", "message": "Mídia sem URL pública; TXT preserva apenas o nome até o usuário autorizar uma URL.", "recommended": "name_only"})
        elif typ == "buttons":
            links = []
            for row in node.get("rows") or []:
                for button in row if isinstance(row, list) else [row]:
                    label = _plain_inline(str(button.get("html") or button.get("text") or "Botão"))
                    url = str(button.get("url") or "")
                    links.append(label + (f": {url}" if url else ""))
            out.extend(links)
            warnings.append({"node_id": node.get("id"), "type": "adaptation", "message": "Botões convertidos para links/texto.", "recommended": "links"})
        elif typ == "details":
            out.append(_plain_inline(str(node.get("summary_html") or node.get("summary") or "")))
            nested, nested_warnings = to_txt({"nodes": node.get("children") or []})
            if nested:
                out.append(nested)
            warnings.extend(nested_warnings)
            warnings.append({"node_id": node.get("id"), "type": "adaptation", "message": "Details convertido expandido no TXT.", "recommended": "expanded"})
        elif typ == "raw_markdown":
            out.append(str(node.get("raw") or ""))
            warnings.append({"node_id": node.get("id"), "type": "incompatible", "message": "Trecho cru preservado literalmente; revisão necessária antes da saída TXT.", "recommended": "preserve_raw"})
    return "\n\n".join(part for part in out if part != ""), warnings
