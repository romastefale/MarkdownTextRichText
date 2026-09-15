from __future__ import annotations

import hashlib
import mimetypes

from mdtxtrt.conversion.markdown import import_literal_text, import_markdown, looks_like_markdown


class EncodingChoiceRequired(ValueError):
    def __init__(self, choices: list[str], *, import_key: str | None = None):
        super().__init__("O arquivo não é UTF-8. Escolha o encoding antes de importar; nenhum encoding foi adivinhado.")
        self.choices = choices
        self.import_key = import_key


def decode_text(raw: bytes, encoding: str | None = None) -> tuple[str, str]:
    if encoding:
        try:
            return raw.decode(encoding, errors="strict"), encoding
        except (LookupError, UnicodeDecodeError) as exc:
            raise ValueError(f"Não foi possível decodificar o arquivo como {encoding}.") from exc
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="strict"), "utf-8-sig"
    try:
        return raw.decode("utf-8", errors="strict"), "utf-8"
    except UnicodeDecodeError as exc:
        raise EncodingChoiceRequired(["windows-1252", "iso-8859-1", "utf-16", "utf-16-le", "utf-16-be"]) from exc


def import_text(text: str, mode: str | None = None) -> tuple[dict, dict]:
    if mode == "literal":
        return import_literal_text(text)
    if mode == "markdown":
        return import_markdown(text)
    if looks_like_markdown(text):
        report = {
            "requires_mode_choice": True,
            "choices": ["markdown", "literal"],
            "message": "O texto colado parece conter Markdown. Escolha interpretar como Markdown ou manter literalmente.",
        }
        return {}, report
    return import_literal_text(text)


def _metadata(blob: dict) -> dict:
    return {key: blob[key] for key in ("id", "name", "mime", "size", "sha256")}


def import_stored_blob(store, user_id: int, *, import_key: str, encoding: str | None = None, mode: str | None = None) -> dict:
    record = store.get_import(user_id, import_key)
    if not record or not record.get("blob_id"):
        raise KeyError("Importação original não encontrada.")
    if record.get("draft_id"):
        return {
            "ok": True,
            "draft": store.load_draft(user_id, record["draft_id"]),
            "report": record.get("report") or {},
            "idempotent": True,
        }
    blob = store.get_blob(user_id, record["blob_id"])
    try:
        text, used_encoding = decode_text(bytes(blob["data"]), encoding)
    except EncodingChoiceRequired as exc:
        report = {
            **(record.get("report") or {}),
            "requires_encoding_choice": True,
            "encoding_choices": exc.choices,
            "original_blob": _metadata(blob),
        }
        store.update_import(user_id, import_key, status="encoding_choice", report=report)
        raise EncodingChoiceRequired(exc.choices, import_key=import_key) from exc
    suffix = (blob["name"].rsplit(".", 1)[-1].lower() if "." in blob["name"] else "")
    interpreted_mode = mode
    if interpreted_mode is None:
        interpreted_mode = "markdown" if suffix == "md" else "literal"
    document, report = import_text(text, interpreted_mode)
    report = {**report, "encoding": used_encoding, "original_blob": _metadata(blob)}
    if report.get("requires_mode_choice"):
        store.update_import(user_id, import_key, status="mode_choice", report=report)
        return {"ok": False, "requires_mode_choice": True, "report": report, "encoding": used_encoding, "import_key": import_key}
    status = "import_review" if report.get("partial") else "active"
    draft = store.create_draft(user_id, document, import_key=import_key, status=status, event_type="import")
    store.attach_blob(user_id, draft["id"], blob["id"], logical_name=blob["name"], relation="original_import")
    store.set_import_draft(user_id, import_key, draft["id"], status, report)
    return {"ok": True, "draft": store.load_draft(user_id, draft["id"]), "report": report, "idempotent": False}


def import_file(store, user_id: int, *, name: str, mime: str, raw: bytes, import_key: str, encoding: str | None = None, mode: str | None = None) -> dict:
    suffix = (name.rsplit(".", 1)[-1].lower() if "." in name else "")
    if suffix not in {"md", "txt"}:
        raise ValueError("Importação atual aceita somente arquivos .md e .txt.")
    existing = store.get_import(user_id, import_key)
    if existing and existing.get("draft_id"):
        return {
            "ok": True,
            "draft": store.load_draft(user_id, existing["draft_id"]),
            "report": existing.get("report") or {},
            "idempotent": True,
        }
    if existing and existing.get("blob_id"):
        return import_stored_blob(store, user_id, import_key=import_key, encoding=encoding, mode=mode)
    blob = store.put_blob(user_id, name or "import.txt", mime or mimetypes.guess_type(name)[0] or "text/plain", raw)
    initial_report = {"original_blob": _metadata(blob)}
    store.import_record(user_id, import_key, status="stored", report=initial_report, blob_id=blob["id"])
    return import_stored_blob(store, user_id, import_key=import_key, encoding=encoding, mode=mode)


def import_key_for_bytes(prefix: str, raw: bytes, unique: str | None = None) -> str:
    if unique:
        return f"{prefix}:{unique}"
    return f"{prefix}:{hashlib.sha256(raw).hexdigest()}:{len(raw)}"
