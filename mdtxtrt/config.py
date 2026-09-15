from __future__ import annotations

from dataclasses import dataclass
import base64
import os
from pathlib import Path


DEFAULT_MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    web_app_url: str
    port: int
    database_path: Path
    init_data_ttl_seconds: int
    telegraph_aes_key: bytes | None
    static_path: Path
    max_upload_bytes: int


def _token(raw: str) -> str:
    value = (raw or "").strip().strip('"').strip("'")
    if value.startswith("bot") and len(value) > 3 and value[3].isdigit():
        value = value[3:]
    return value


def _telegraph_key() -> bytes | None:
    encoded = (os.environ.get("KEY") or "").strip()
    if not encoded:
        return None
    try:
        key = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise RuntimeError("KEY precisa ser Base64 válido.") from exc
    if len(key) != 32:
        raise RuntimeError("KEY precisa decodificar exatamente 32 bytes.")
    return key


def _max_upload_bytes() -> int:
    raw = (os.environ.get("MDTXTRT_MAX_UPLOAD_BYTES") or str(DEFAULT_MAX_UPLOAD_BYTES)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("MDTXTRT_MAX_UPLOAD_BYTES precisa ser um inteiro positivo.") from exc
    if value <= 0:
        raise RuntimeError("MDTXTRT_MAX_UPLOAD_BYTES precisa ser um inteiro positivo.")
    return value


def load_settings() -> Settings:
    package = Path(__file__).resolve().parent
    return Settings(
        telegram_token=_token(os.environ.get("TOKEN", "")),
        web_app_url=(os.environ.get("WEB_APP_URL") or "").strip().rstrip("/"),
        port=int(os.environ.get("PORT", "8080")),
        database_path=Path(os.environ.get("MDTXTRT_DB", "/data/mdtxtrt.sqlite3")),
        init_data_ttl_seconds=3600,
        telegraph_aes_key=_telegraph_key(),
        static_path=package / "static",
        max_upload_bytes=_max_upload_bytes(),
    )
