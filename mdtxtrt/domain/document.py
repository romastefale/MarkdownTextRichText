from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import re
import uuid
from zoneinfo import ZoneInfo

from mdtxtrt.domain.sanitize import sanitize_inline_html

SCHEMA = "mdtxtrt.document/v1"
NODE_TYPES = {
    "paragraph", "heading", "blockquote", "pullquote", "details", "code", "math",
    "list", "table", "media", "map", "buttons", "divider", "footer", "anchor",
    "raw_markdown",
}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def utc_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def new_document() -> dict:
    now = utc_ms()
    return {
        "schema": SCHEMA,
        "id": new_id("doc"),
        "created_at_ms": now,
        "updated_at_ms": now,
        "nodes": [],
        "metadata": {},
    }


def make_node(kind: str, **values) -> dict:
    if kind not in NODE_TYPES:
        kind = "raw_markdown"
    node = {"id": new_id("node"), "type": kind}
    node.update(values)
    return node


def normalize_document(value: dict | None) -> dict:
    source = deepcopy(value) if isinstance(value, dict) else new_document()
    source["schema"] = SCHEMA
    source.setdefault("id", new_id("doc"))
    source.setdefault("created_at_ms", utc_ms())
    source["updated_at_ms"] = utc_ms()
    source.setdefault("metadata", {})
    nodes = source.get("nodes")
    if not isinstance(nodes, list):
        nodes = []
    normalized = []
    for raw in nodes:
        if not isinstance(raw, dict):
            normalized.append(make_node("paragraph", html=str(raw)))
            continue
        item = deepcopy(raw)
        item.setdefault("id", new_id("node"))
        if item.get("type") not in NODE_TYPES:
            original = deepcopy(item)
            item = make_node("raw_markdown", raw=str(original), reason="unknown_node_type")
        for key in ("html", "summary_html", "caption_html"):
            if key in item:
                item[key] = sanitize_inline_html(str(item.get(key) or ""))
        if item.get("type") == "list":
            for entry in item.get("items") or []:
                if isinstance(entry, dict) and "html" in entry:
                    entry["html"] = sanitize_inline_html(str(entry.get("html") or ""))
        if item.get("type") == "buttons":
            for button in item.get("items") or item.get("buttons") or []:
                if isinstance(button, dict) and "html" in button:
                    button["html"] = sanitize_inline_html(str(button.get("html") or ""))
        normalized.append(item)
    source["nodes"] = normalized
    return source


def plain_text(document: dict) -> str:
    out: list[str] = []
    for node in document.get("nodes") or []:
        typ = node.get("type")
        if typ in {"paragraph", "heading", "footer", "blockquote", "pullquote"}:
            text = re.sub(r"<[^>]+>", "", str(node.get("html") or node.get("text") or ""))
            if text.strip():
                out.append(text.strip())
        elif typ == "code":
            out.append(str(node.get("text") or ""))
        elif typ == "math":
            out.append(str(node.get("expression") or ""))
        elif typ == "map":
            name = str(node.get("name") or "").strip()
            lat = node.get("latitude")
            lon = node.get("longitude")
            out.append((name + " " if name else "") + f"{lat}, {lon}")
        elif typ == "media":
            out.append(str(node.get("name") or node.get("caption") or node.get("kind") or "Mídia"))
        elif typ == "table":
            for row in node.get("rows") or []:
                out.append(" ".join(str(cell.get("text") if isinstance(cell, dict) else cell) for cell in row))
        elif typ == "raw_markdown":
            out.append(str(node.get("raw") or ""))
    return "\n".join(part for part in out if part)


def suggested_name(document: dict) -> str:
    nodes = document.get("nodes") or []
    if not nodes:
        return datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")
    first = nodes[0]
    typ = first.get("type")
    if typ in {"media", "map", "table", "buttons", "details", "code", "math"}:
        labels = {
            "media": "Mídia", "map": "Mapa", "table": "Tabela", "buttons": "Botões",
            "details": "Detalhes", "code": "Código", "math": "Matemática",
        }
        return labels[typ]
    text = plain_text({"nodes": [first]}).strip()
    if not text:
        return datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")
    compact = re.sub(r"\s+", " ", text)
    if len(compact) <= 40:
        return compact
    candidate = compact[:40]
    if " " in candidate:
        candidate = candidate.rsplit(" ", 1)[0]
    return candidate or compact[:40]
