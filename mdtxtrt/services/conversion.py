from __future__ import annotations

from mdtxtrt.conversion.legacy_projection import CanonicalDocument
from mdtxtrt.conversion.markdown import to_markdown
from mdtxtrt.conversion.telegram_html import to_html
from mdtxtrt.conversion.txt import to_txt


def telegram_review(document: dict) -> dict:
    markdown = to_markdown(document)
    rich_markdown, _ = CanonicalDocument.from_markdown(markdown).telegram_markdown()
    warnings = []
    for node in document.get("nodes") or []:
        if node.get("type") == "raw_markdown":
            warnings.append({"node_id": node.get("id"), "type": "review", "message": "Trecho Markdown cru será revalidado pela Bot API antes do envio."})
    return {
        "destination": "telegram",
        "recommended": "rich_markdown",
        "projection": rich_markdown,
        "warnings": warnings,
        "alternatives": [
            {"id": "html", "label": "HTML", "description": "Rich HTML oficial da Bot API.", "projection": to_html(document)},
            {"id": "blocks", "label": "Blocks", "description": "Blocos explícitos oficiais; a prévia técnica é produzida no servidor no momento do envio."},
        ],
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
        "projection": text,
        "warnings": warnings,
        "alternatives": [],
    }


def markdown_review(document: dict) -> dict:
    return {
        "destination": "markdown",
        "recommended": "markdown",
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


def proposed_document_from_output(converted: str, destination: str) -> tuple[dict, list[dict]]:
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
    losses = [{"type": kind, "message": f"Estrutura `{kind}` não reaparece como estrutura equivalente na proposta aplicada."} for kind in missing]
    for warning in report.get("warnings") or []:
        losses.append({"type": "conversion", "message": str(warning)})
    return {"proposed_document": proposed, "losses": losses, "requires_confirmation": bool(losses)}
