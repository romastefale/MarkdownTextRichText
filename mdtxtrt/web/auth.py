from __future__ import annotations

from datetime import datetime, timezone

from aiogram.utils.web_app import safe_parse_webapp_init_data


class AuthError(PermissionError):
    def __init__(self, message: str, *, expired: bool = False):
        super().__init__(message)
        self.expired = expired


def validate_init_data(token: str, init_data: str, *, ttl_seconds: int = 3600) -> dict:
    if not token:
        raise AuthError("TOKEN ausente no servidor.")
    raw = (init_data or "").strip()
    if not raw:
        raise AuthError("Abra o Web App pelo Telegram para validar a sessão.")
    try:
        parsed = safe_parse_webapp_init_data(token=token, init_data=raw)
    except ValueError as exc:
        raise AuthError("Sessão Telegram inválida.") from exc
    user = parsed.user
    if user is None or not user.id:
        raise AuthError("Sessão Telegram sem usuário.")
    if parsed.auth_date is not None:
        age = abs((datetime.now(timezone.utc) - parsed.auth_date).total_seconds())
        if age > ttl_seconds:
            raise AuthError("Sessão Telegram expirada. Reinicialize o Web App; o trabalho local será preservado.", expired=True)
    return user.model_dump()


def init_data_from_request(request, data: dict | None = None) -> str:
    body = data or {}
    raw = body.get("init_data") or body.get("initData") or ""
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    header = (request.headers.get("X-Telegram-Init-Data") or "").strip()
    if header:
        return header
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("tma "):
        return auth[4:].strip()
    return ""
