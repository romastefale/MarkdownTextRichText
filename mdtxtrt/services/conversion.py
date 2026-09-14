from __future__ import annotations

from mdtxtrt.conversion.legacy_projection import CanonicalDocument
from mdtxtrt.conversion.markdown import to_markdown
from mdtxtrt.conversion.telegram_html import to_html
from mdtxtrt.conversion.traditional import (
    to_markdown_v2,
    to_traditional_html,
    traditional_compatibility,
)
from mdtxtrt.conversion.txt import to_txt


BLOCK_PREFERRED = {
    "heading", "details", "math", "table", "media", "map", "buttons", "anchor",
    "pullquote", "footer",
}


def select_telegram_mode(document: dict) -> str:
    """Select one effective Telegram renderer without conflating Rich and traditional parse modes."""
    for node in document.get("nodes") or []:
        typ = str(node.get("type") or "")
        if typ in BLOCK_PREFERRED:
            return "blocks"
        if typ == "blockquote" and node.get("expandable"):
            return "blocks"
        if typ == "list":
            if any(isinstance(item, dict) and item.get("checked") is not None for item in node.get("items") or []):
                return "blocks"
    return "rich_markdown"


def telegram_review(document: dict) -> dict:
    markdown = to_markdown(document)
    rich_markdown, _ = CanonicalDocument.from_markdown(markdown).telegram_markdown()
    mode = select_telegram_mode(document)
    warnings = []
    for node in document.get("nodes") or []:
        if node.get("type") == "raw_markdown":
            warnings.append({
                "node_id": node.get("id"),
                "type": "review",
                "message": "Trecho Markdown cru será revalidado pela Bot API antes do envio.",
            })
    traditional_ok, traditional_warnings = traditional_compatibility(document)
    alternatives = [
        {
            "id": "rich_markdown",
            "label": "Rich Message · Rich Markdown",
            "description": "InputRichMessage.markdown; indicado para texto Rich sem estrutura que exija Blocks.",
            "available": True,
        },
        {
            "id": "html",
            "label": "Rich Message · Rich HTML",
            "description": "InputRichMessage.html; usa o HTML Rich oficial da Bot API.",
            "available": True,
        },
        {
            "id": "blocks",
            "label": "Rich Message · Blocks",
            "description": "InputRichMessage.blocks; preserva estrutura explícita e é preferido para recursos avançados.",
            "available": True,
        },
    ]
    if traditional_ok:
        alternatives.extend([
            {
                "id": "traditional_html",
                "label": "Mensagem tradicional · HTML",
                "description": "sendMessage(parse_mode=HTML), somente para subconjunto compatível.",
                "available": True,
                "projection": to_traditional_html(document),
            },
            {
                "id": "markdown_v2",
                "label": "Mensagem tradicional · MarkdownV2",
                "description": "sendMessage(parse_mode=MarkdownV2), somente para subconjunto compatível.",
                "available": True,
                "projection": to_markdown_v2(document),
            },
        ])
    else:
        warnings.extend({"type": "traditional_fallback", "message": value} for value in traditional_warnings)

    label = {
        "blocks": "Rich Message · Blocks",
        "rich_markdown": "Rich Message · Rich Markdown",
        "html": "Rich Message · Rich HTML",
    }[mode]
    return {
        "destination": "telegram",
        "recommended": mode,
        "format_id": mode,
        "mechanism": label,
        "projection": to_html(document) if mode == "blocks" else rich_markdown,
        "preview_kind": "rich_html" if mode == "blocks" else "rich_markdown",
        "warnings": warnings,
        "alternatives": alternatives,
        "traditional_compatible": traditional_ok,
    }


def telegraph_review(document: dict) -> dict:
    markdown = to_markdown(document)
    projection = CanonicalDocument.from_markdown(markdown).telegraph()
    warnings = [{"type": "adaptation", "message": value} for value in projection.adaptations]
    warnings += [{"type": "incompatible", "message": value} for value in projection.unsupported]
    alternatives = []
    if any(node.get("type") == "table" for node in document.get("nodes") or []):
        alternatives.append({"id": "table_pre", "label": "Tabela preformatada", "recommended": True})
        alternatives.append({"id": "table_text", "label": "Tabela em texto"})
    return {
        "destination": "telegraph",
        "recommended": "telegraph_html",
        "mechanism": "Telegraph HTML",
        "projection": projection.html,
        "warnings": warnings,
        "alternatives": alternatives,
        "compatible": projection.compatible,
    }


def txt_review(document: dict) -> dict:
    text, warnings = to_txt(document)
    return {
        "destination": "txt",
        "recommended": "plain_text",
        "mechanism": "Texto literal",
        "projection": text,
        "warnings": warnings,
        "alternatives": [],
    }


def markdown_review(document: dict) -> dict:
    return {
        "destination": "markdown",
        "recommended": "markdown",
        "mechanism": "Markdown",
        "projection": to_markdown(document),
        "warnings": [],
        "alternatives": [],
    }


def review(document: dict, destination: str) -> dict:
    if destination == "telegram":
        return telegram_review(document)
    if destination == "telegraph":
        return telegraph_review(document)
    if destination == "txt":
        return txt_review(document)
    if destination == "markdown":
        return markdown_review(document)
    raise ValueError("Destino de conversão desconhecido.")


def proposed_document_from_output(converted: str, destination: str) -> tuple[dict, dict]:
    from mdtxtrt.conversion.markdown import import_literal_text, import_markdown
    from mdtxtrt.domain.document import make_node, new_document

    if destination in {"markdown", "telegram"}:
        return import_markdown(converted)
    if destination == "txt":
        return import_literal_text(converted)
    if destination == "telegraph":
        document = new_document()
        document["nodes"] = [
            make_node(
                "raw_markdown",
                raw=converted,
                reason="telegraph_html_reimport",
                suggestion="O HTML do Telegraph não é tratado como canônico Rich. Ele será preservado cru se aplicado ao documento principal.",
            )
        ]
        return document, {"partial": True, "warnings": ["Telegraph HTML preservado cru ao voltar para o canônico."]}
    raise ValueError("Destino de conversão desconhecido.")


def apply_review(original: dict, converted: str, destination: str) -> dict:
    proposed, report = proposed_document_from_output(converted, destination)
    original_types = [node.get("type") for node in original.get("nodes") or []]
    proposed_types = [node.get("type") for node in proposed.get("nodes") or []]
    missing = []
    counts = {kind: proposed_types.count(kind) for kind in set(proposed_types)}
    for kind in original_types:
        available = counts.get(kind, 0)
        if available:
            counts[kind] = available - 1
        else:
            missing.append(kind)
    losses = [
        {"type": kind, "message": f"Estrutura `{kind}` não reaparece como estrutura equivalente na proposta aplicada."}
        for kind in missing
    ]
    for warning in report.get("warnings") or []:
        losses.append({"type": "conversion", "message": str(warning)})
    return {"proposed_document": proposed, "losses": losses, "requires_confirmation": bool(losses)}
