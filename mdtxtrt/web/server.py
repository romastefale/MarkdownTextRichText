from __future__ import annotations

from mdtxtrt.appearance import appearance, normalize_accent

import hashlib
import json
import secrets
from pathlib import Path
from urllib.parse import quote

from aiohttp import web

from mdtxtrt.conversion.markdown import import_literal_text, import_markdown, looks_like_markdown
from mdtxtrt.domain.document import new_document
from mdtxtrt.services.conversion import apply_review, review
from mdtxtrt.services.imports import EncodingChoiceRequired, import_file, import_key_for_bytes, import_stored_blob
from mdtxtrt.storage.sqlite import Store
from mdtxtrt.telegram.bot import TelegramRuntime
from mdtxtrt.telegraph import TelegraphService
from mdtxtrt.web.auth import AuthError, init_data_from_request, validate_init_data


class Server:
    def __init__(self, settings):
        self.settings = settings
        self.store = Store(settings.database_path)
        self.telegram = TelegramRuntime(settings, self.store)
        self.telegraph = TelegraphService(self.store, settings.telegraph_aes_key)

    def _auth(self, request: web.Request, data: dict | None = None) -> dict:
        raw = init_data_from_request(request, data)
        return validate_init_data(
            self.settings.telegram_token,
            raw,
            ttl_seconds=self.settings.init_data_ttl_seconds,
        )

    async def _json_auth(self, request: web.Request) -> tuple[dict, dict]:
        try:
            data = await request.json()
        except Exception as exc:
            raise web.HTTPBadRequest(text=json.dumps({"ok": False, "error": "JSON inválido"}), content_type="application/json") from exc
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(text=json.dumps({"ok": False, "error": "Objeto JSON esperado"}), content_type="application/json")
        return data, self._auth(request, data)

    def _static(self, name: str) -> Path:
        path = (self.settings.static_path / name).resolve()
        root = self.settings.static_path.resolve()
        if root not in path.parents and path != root:
            raise web.HTTPNotFound()
        return path

    async def index(self, request: web.Request):
        return web.FileResponse(self._static("index.html"), headers={"Cache-Control": "no-store"})

    async def static_file(self, request: web.Request):
        name = request.match_info.get("name") or ""
        path = self._static(name)
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Cache-Control": "no-cache"})

    async def health(self, request: web.Request):
        return web.json_response(
            {
                "ok": True,
                "app": "mdtxtrt-rebuild",
                "architecture": "modular-direct",
                "document_schema": "mdtxtrt.document/v1",
                "bot": bool(self.settings.telegram_token),
                "bot_username": self.telegram.username or None,
                "init_data_ttl_seconds": self.settings.init_data_ttl_seconds,
                "telegraph_account_mode": "one_anonymous_account_per_telegram_user",
                "telegraph_token_encryption": "AES-256-GCM" if self.settings.telegraph_aes_key else "unavailable_missing_key",
            }
        )

    async def bootstrap(self, request: web.Request):
        data, user = await self._json_auth(request)
        user_id = int(user["id"])
        return web.json_response(
            {
                "ok": True,
                "user": {key: user.get(key) for key in ("id", "first_name", "last_name", "username")},
                "drafts": self.store.list_drafts(user_id, "active") + self.store.list_drafts(user_id, "import_review"),
                "archived": self.store.list_drafts(user_id, "archived"),
                "preferences": self.store.preferences(user_id),
                "appearance": appearance(self.store.preferences(user_id)),
                "pending_import": self.store.pending_action(user_id, "import"),
                "destinations": self.store.list_telegram_destinations(user_id),
                "requested_draft": data.get("draft"),
            }
        )

    async def draft_create(self, request: web.Request):
        data, user = await self._json_auth(request)
        draft = self.store.create_draft(
            int(user["id"]),
            data.get("document") if isinstance(data.get("document"), dict) else new_document(),
            name=data.get("name"),
            session=data.get("session"),
        )
        return web.json_response({"ok": True, "draft": draft})

    async def draft_load(self, request: web.Request):
        data, user = await self._json_auth(request)
        try:
            draft = self.store.load_draft(int(user["id"]), str(data.get("draft_id") or ""))
        except KeyError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)
        return web.json_response({"ok": True, "draft": draft})

    async def draft_revise(self, request: web.Request):
        data, user = await self._json_auth(request)
        user_id = int(user["id"])
        draft_id = str(data.get("draft_id") or "")
        try:
            current = self.store.load_draft(user_id, draft_id)
            expected = str(data.get("expected_revision_id") or "")
            if expected and expected != current["revision_id"]:
                return web.json_response(
                    {"ok": False, "error": "O servidor possui outra revisão atual. Escolha qual versão continuar; nenhuma mesclagem foi feita.", "conflict": True, "server": current},
                    status=409,
                )
            draft = self.store.revise(
                user_id,
                draft_id,
                data.get("document") if isinstance(data.get("document"), dict) else current["document"],
                data.get("session") if isinstance(data.get("session"), dict) else current["session"],
                event_type=str(data.get("event_type") or "edit"),
                group_key=str(data.get("group_key") or "") or None,
                parent_revision_id=current["revision_id"],
            )
            return web.json_response({"ok": True, "draft": draft})
        except (KeyError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def draft_recover_local(self, request: web.Request):
        data, user = await self._json_auth(request)
        if data.get("confirmed_choice") != "local":
            return web.json_response({"ok": False, "error": "A recuperação local exige escolha explícita da versão local."}, status=409)
        user_id = int(user["id"])
        draft_id = str(data.get("draft_id") or "")
        try:
            current = self.store.load_draft(user_id, draft_id)
            source_revision = str(data.get("source_revision_id") or current["revision_id"])
            draft = self.store.revise(
                user_id,
                draft_id,
                data.get("document") if isinstance(data.get("document"), dict) else current["document"],
                data.get("session") if isinstance(data.get("session"), dict) else current["session"],
                event_type="local_recovery",
                group_key="local_recovery",
                parent_revision_id=source_revision,
            )
            return web.json_response({"ok": True, "draft": draft, "branched_from": source_revision})
        except (KeyError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def draft_undo(self, request: web.Request):
        data, user = await self._json_auth(request)
        try:
            return web.json_response({"ok": True, "draft": self.store.undo(int(user["id"]), str(data.get("draft_id") or ""))})
        except KeyError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)

    async def draft_redo(self, request: web.Request):
        data, user = await self._json_auth(request)
        try:
            draft = self.store.redo(int(user["id"]), str(data.get("draft_id") or ""), str(data.get("revision_id") or "") or None)
            return web.json_response({"ok": True, "draft": draft})
        except (KeyError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def draft_rename(self, request: web.Request):
        data, user = await self._json_auth(request)
        name = str(data.get("name") or "").strip()
        if not name:
            return web.json_response({"ok": False, "error": "Nome vazio."}, status=400)
        try:
            draft = self.store.rename(int(user["id"]), str(data.get("draft_id") or ""), name)
            return web.json_response({"ok": True, "draft": draft})
        except KeyError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)

    async def draft_archive(self, request: web.Request):
        data, user = await self._json_auth(request)
        try:
            draft = self.store.set_status(int(user["id"]), str(data.get("draft_id") or ""), "archived", "archive")
            return web.json_response({"ok": True, "draft": draft})
        except KeyError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)

    async def draft_restore(self, request: web.Request):
        data, user = await self._json_auth(request)
        try:
            draft = self.store.set_status(int(user["id"]), str(data.get("draft_id") or ""), "active", "restore")
            return web.json_response({"ok": True, "draft": draft})
        except KeyError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)

    async def draft_delete(self, request: web.Request):
        data, user = await self._json_auth(request)
        if data.get("confirmed") is not True:
            return web.json_response({"ok": False, "error": "A exclusão definitiva exige confirmação explícita."}, status=409)
        try:
            self.store.permanent_delete(int(user["id"]), str(data.get("draft_id") or ""))
            return web.json_response({"ok": True})
        except KeyError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)

    async def draft_duplicate(self, request: web.Request):
        data, user = await self._json_auth(request)
        if data.get("confirmed") is not True:
            return web.json_response({"ok": False, "error": "Duplicar exige confirmação explícita; BLOBs podem ser compartilhados entre a cópia e o original."}, status=409)
        try:
            return web.json_response({"ok": True, "draft": self.store.duplicate_draft(int(user["id"]), str(data.get("draft_id") or ""))})
        except KeyError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)

    async def import_text(self, request: web.Request):
        data, user = await self._json_auth(request)
        text = str(data.get("text") or "")
        mode = str(data.get("mode") or "") or None
        if mode is None and looks_like_markdown(text):
            return web.json_response(
                {
                    "ok": False,
                    "requires_mode_choice": True,
                    "choices": ["markdown", "literal"],
                    "message": "O texto colado parece conter Markdown. Escolha como interpretar.",
                },
                status=409,
            )
        raw = text.encode("utf-8")
        unique = str(data.get("import_key") or "") or None
        key = import_key_for_bytes("paste", raw, unique)
        result = import_file(
            self.store,
            int(user["id"]),
            name="texto-colado.md" if mode == "markdown" else "texto-colado.txt",
            mime="text/markdown" if mode == "markdown" else "text/plain",
            raw=raw,
            import_key=key,
            mode=mode or "literal",
        )
        return web.json_response(result)

    async def import_file(self, request: web.Request):
        try:
            post = await request.post()
        except Exception as exc:
            return web.json_response({"ok": False, "error": "Upload inválido."}, status=400)
        try:
            user = self._auth(request, dict(post))
        except AuthError as exc:
            return self.auth_error(exc)
        upload = post.get("file")
        if upload is None or not hasattr(upload, "file"):
            return web.json_response({"ok": False, "error": "Arquivo ausente."}, status=400)
        raw = upload.file.read()
        name = getattr(upload, "filename", None) or "import.txt"
        mime = getattr(upload, "content_type", None) or "application/octet-stream"
        unique = str(post.get("import_key") or "") or None
        key = import_key_for_bytes("web", raw, unique)
        try:
            result = import_file(
                self.store,
                int(user["id"]),
                name=name,
                mime=mime,
                raw=raw,
                import_key=key,
                encoding=str(post.get("encoding") or "") or None,
                mode=str(post.get("mode") or "") or None,
            )
            return web.json_response(result)
        except EncodingChoiceRequired as exc:
            self.store.set_pending_action(int(user["id"]), "import", {"import_key": exc.import_key or key, "encoding_choices": exc.choices})
            return web.json_response({"ok": False, "requires_encoding_choice": True, "import_key": exc.import_key or key, "choices": exc.choices}, status=409)
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def import_resolve(self, request: web.Request):
        data, user = await self._json_auth(request)
        user_id = int(user["id"])
        key = str(data.get("import_key") or "")
        if not key:
            pending = self.store.pending_action(user_id, "import")
            key = str((pending or {}).get("payload", {}).get("import_key") or "")
        if not key:
            return web.json_response({"ok": False, "error": "Importação pendente não identificada."}, status=404)
        try:
            result = import_stored_blob(
                self.store,
                user_id,
                import_key=key,
                encoding=str(data.get("encoding") or "") or None,
                mode=str(data.get("mode") or "") or None,
            )
            if result.get("ok"):
                self.store.clear_pending_action(user_id, "import")
            return web.json_response(result)
        except EncodingChoiceRequired as exc:
            return web.json_response({"ok": False, "requires_encoding_choice": True, "import_key": key, "choices": exc.choices}, status=409)
        except (KeyError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def blob_upload(self, request: web.Request):
        try:
            post = await request.post()
        except Exception:
            return web.json_response({"ok": False, "error": "Upload inválido."}, status=400)
        try:
            user = self._auth(request, dict(post))
        except AuthError as exc:
            return self.auth_error(exc)
        upload = post.get("file")
        if upload is None or not hasattr(upload, "file"):
            return web.json_response({"ok": False, "error": "Arquivo ausente."}, status=400)
        raw = upload.file.read()
        if not raw:
            return web.json_response({"ok": False, "error": "Arquivo vazio."}, status=400)
        name = getattr(upload, "filename", None) or "arquivo.bin"
        mime = getattr(upload, "content_type", None) or "application/octet-stream"
        blob = self.store.put_blob(int(user["id"]), name, mime, raw)
        draft_id = str(post.get("draft_id") or "")
        if draft_id:
            try:
                self.store.attach_blob(int(user["id"]), draft_id, blob["id"], logical_name=name, relation=str(post.get("relation") or "media"))
            except KeyError as exc:
                return web.json_response({"ok": False, "error": str(exc)}, status=404)
        return web.json_response({"ok": True, "blob": blob})

    async def blob_download(self, request: web.Request):
        data, user = await self._json_auth(request)
        try:
            blob = self.store.get_blob(int(user["id"]), str(data.get("blob_id") or ""))
        except KeyError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)
        payload = bytes(blob["data"])
        actual = hashlib.sha256(payload).hexdigest()
        corrupt = actual != blob["sha256"]
        if corrupt and data.get("allow_corrupt") is not True:
            return web.json_response(
                {"ok": False, "error": "SHA-256 do BLOB diverge do hash registrado.", "sha256_expected": blob["sha256"], "sha256_actual": actual, "can_download_with_alert": True},
                status=409,
            )
        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(blob['name'])}",
            "X-MDTXTRT-SHA256": actual,
        }
        if corrupt:
            headers["X-MDTXTRT-Integrity-Warning"] = "sha256-mismatch-user-confirmed"
        return web.Response(body=payload, content_type=blob["mime"], headers=headers)

    async def blob_publish(self, request: web.Request):
        data, user = await self._json_auth(request)
        if data.get("confirmed") is not True:
            return web.json_response({"ok": False, "error": "Criar URL pública exige confirmação explícita."}, status=409)
        token = secrets.token_urlsafe(36)
        try:
            item = self.store.create_public_blob(int(user["id"]), str(data.get("blob_id") or ""), token)
        except KeyError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)
        origin = self.settings.web_app_url or str(request.url.origin())
        return web.json_response({"ok": True, "token": item["token"], "url": f"{origin.rstrip('/')}/b/{item['token']}"})

    async def blob_revoke(self, request: web.Request):
        data, user = await self._json_auth(request)
        return web.json_response({"ok": self.store.revoke_public_blob(int(user["id"]), str(data.get("token") or ""))})

    async def public_blob(self, request: web.Request):
        item = self.store.public_blob(str(request.match_info.get("token") or ""))
        if not item:
            raise web.HTTPNotFound(text="Arquivo indisponível")
        payload = bytes(item["data"])
        if hashlib.sha256(payload).hexdigest() != item["sha256"]:
            raise web.HTTPConflict(text="Integridade do arquivo não pôde ser confirmada")
        return web.Response(
            body=payload,
            content_type=item["mime"],
            headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(item['name'])}", "Cache-Control": "private, no-store"},
        )

    async def parse_text(self, request: web.Request):
        data, user = await self._json_auth(request)
        mode = str(data.get("mode") or "markdown")
        text = str(data.get("text") or "")
        try:
            if mode == "literal":
                document, report = import_literal_text(text)
            elif mode == "markdown":
                document, report = import_markdown(text)
            else:
                raise ValueError("Modo de parse desconhecido.")
            return web.json_response({"ok": True, "document": document, "report": report})
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def conversion_review(self, request: web.Request):
        data, user = await self._json_auth(request)
        try:
            draft = self.store.load_draft(int(user["id"]), str(data.get("draft_id") or ""))
            report = review(draft["document"], str(data.get("destination") or ""))
            original_markdown = review(draft["document"], "markdown")["projection"]
            return web.json_response({"ok": True, "draft_revision_id": draft["revision_id"], "original": draft["document"], "original_markdown": original_markdown, "review": report})
        except (KeyError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def conversion_apply(self, request: web.Request):
        data, user = await self._json_auth(request)
        user_id = int(user["id"])
        try:
            draft = self.store.load_draft(user_id, str(data.get("draft_id") or ""))
            if str(data.get("revision_id") or "") != draft["revision_id"]:
                return web.json_response({"ok": False, "error": "A revisão mudou desde a conversão. Revise novamente antes de aplicar ao documento."}, status=409)
            proposal = apply_review(draft["document"], str(data.get("converted") or ""), str(data.get("destination") or ""))
            if proposal["requires_confirmation"] and data.get("confirmed") is not True:
                return web.json_response({"ok": False, "requires_confirmation": True, **proposal}, status=409)
            updated = self.store.revise(
                user_id,
                draft["id"],
                proposal["proposed_document"],
                draft["session"],
                event_type="conversion_apply",
                parent_revision_id=draft["revision_id"],
            )
            return web.json_response({"ok": True, "draft": updated, "losses": proposal["losses"]})
        except (KeyError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def export_output(self, request: web.Request):
        data, user = await self._json_auth(request)
        try:
            draft = self.store.load_draft(int(user["id"]), str(data.get("draft_id") or ""))
            if str(data.get("revision_id") or "") != draft["revision_id"]:
                return web.json_response({"ok": False, "error": "A revisão mudou desde a revisão da exportação."}, status=409)
            destination = str(data.get("destination") or "markdown")
            report = review(draft["document"], destination)
            output = str(data.get("output_override")) if data.get("output_override") is not None else str(report["projection"])
            extension = "txt" if destination == "txt" else "md"
            return web.json_response({"ok": True, "filename": f"{draft['name']}.{extension}", "content": output, "manual_output": data.get("output_override") is not None})
        except (KeyError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def telegram_send(self, request: web.Request):
        data, user = await self._json_auth(request)
        user_id = int(user["id"])
        if self.telegram.bot is None:
            return web.json_response({"ok": False, "error": "Bot não iniciado."}, status=503)
        try:
            draft = self.store.load_draft(user_id, str(data.get("draft_id") or ""))
            if str(data.get("revision_id") or "") != draft["revision_id"]:
                return web.json_response({"ok": False, "error": "A revisão mudou depois da revisão Telegram. Revise novamente antes de enviar."}, status=409)
            report = review(draft["document"], "telegram")
            if report["warnings"] and data.get("confirmed") is not True:
                return web.json_response({"ok": False, "requires_confirmation": True, "review": report}, status=409)
            destination_id = str(data.get("destination_id") or "")
            if not destination_id:
                raise ValueError("Escolha um destino Telegram autorizado.")
            destination = self.store.telegram_destination(user_id, destination_id)
            chat_id_raw = str(destination["chat_id"])
            chat_id = int(chat_id_raw) if chat_id_raw.lstrip("-").isdigit() else chat_id_raw
            override = data.get("output_override")
            if override is None:
                sent = await self.telegram.send_document_to_chat(user_id, chat_id, draft["document"], format_mode=str(data.get("format") or "rich_markdown"))
            else:
                sent = await self.telegram.send_markdown_to_chat(chat_id, str(override))
            message_id = getattr(sent, "message_id", None)
            publication = self.store.add_publication(
                user_id,
                draft["id"],
                draft["revision_id"],
                "telegram",
                external_id=str(message_id) if message_id is not None else None,
                metadata={"destination_id": destination_id, "chat_id": chat_id, "message_id": message_id, "manual_output": override is not None},
            )
            return web.json_response({"ok": True, "message_id": message_id, "destination_id": destination_id, "chat_id": chat_id, "publication": publication})
        except (KeyError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=502)

    async def telegraph_publish(self, request: web.Request):
        data, user = await self._json_auth(request)
        user_id = int(user["id"])
        try:
            draft = self.store.load_draft(user_id, str(data.get("draft_id") or ""))
            if str(data.get("revision_id") or "") != draft["revision_id"]:
                return web.json_response({"ok": False, "error": "A revisão mudou depois da revisão Telegraph. Revise novamente."}, status=409)
            report = self.telegraph.review(draft["document"])
            needs_confirmation = bool(report["adaptations"] or report["unsupported"])
            if needs_confirmation and data.get("confirmed") is not True:
                return web.json_response({"ok": False, "requires_confirmation": True, "review": report}, status=409)
            result = await self.telegraph.publish_async(
                user_id,
                draft,
                str(data.get("title") or draft["name"]),
                update_existing=data.get("update_existing") is True,
                html_override=str(data.get("output_override")) if data.get("output_override") is not None else None,
            )
            return web.json_response({"ok": True, **result})
        except (KeyError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=502)

    async def map_request(self, request: web.Request):
        data, user = await self._json_auth(request)
        user_id = int(user["id"])
        draft_id = str(data.get("draft_id") or "")
        node_id = str(data.get("node_id") or "")
        try:
            self.store.load_draft(user_id, draft_id)
            item = self.store.create_map_request(user_id, draft_id, node_id)
            if self.telegram.bot is not None:
                await self.telegram.notify_map_request(user_id, draft_id)
            telegram_url = f"https://t.me/{self.telegram.username}" if self.telegram.username else None
            return web.json_response({"ok": True, "request": item, "telegram_url": telegram_url})
        except KeyError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)

    async def map_status(self, request: web.Request):
        data, user = await self._json_auth(request)
        try:
            item = self.store.map_request(int(user["id"]), str(data.get("request_id") or ""))
            return web.json_response({"ok": True, "request": item})
        except KeyError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)

    async def preference_set(self, request: web.Request):
        data, user = await self._json_auth(request)
        key = str(data.get("key") or "").strip()
        if not key:
            return web.json_response({"ok": False, "error": "Preferência sem chave."}, status=400)
        value = data.get("value")
        if key == "accent":
            try:
                value = normalize_accent(value)
            except ValueError as error:
                return web.json_response({"ok": False, "error": str(error)}, status=400)
        self.store.set_preference(int(user["id"]), key, value)
        return web.json_response({"ok": True, "preferences": self.store.preferences(int(user["id"]))})

    def auth_error(self, exc: AuthError):
        return web.json_response({"ok": False, "error": str(exc), "expired": exc.expired, "preserve_local_work": True}, status=401)

    @web.middleware
    async def errors(self, request: web.Request, handler):
        try:
            response = await handler(request)
        except AuthError as exc:
            response = self.auth_error(exc)
        except web.HTTPException:
            raise
        except Exception as exc:
            response = web.json_response({"ok": False, "error": str(exc)}, status=500)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
        if request.path == "/" or request.path.endswith(".js") or request.path.endswith(".css"):
            response.headers.setdefault("Content-Security-Policy", "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; img-src 'self' data: blob: https:; media-src 'self' blob: https:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'")
        return response

    async def startup(self, app: web.Application):
        await self.telegram.start()

    async def cleanup(self, app: web.Application):
        await self.telegram.stop()

    def app(self) -> web.Application:
        app = web.Application(client_max_size=0, middlewares=[self.errors])
        app.router.add_get("/", self.index)
        app.router.add_get("/static/{name}", self.static_file)
        app.router.add_get("/health", self.health)
        app.router.add_get("/b/{token}", self.public_blob)
        app.router.add_post("/api/bootstrap", self.bootstrap)
        app.router.add_post("/api/draft/create", self.draft_create)
        app.router.add_post("/api/draft/load", self.draft_load)
        app.router.add_post("/api/draft/revise", self.draft_revise)
        app.router.add_post("/api/draft/recover-local", self.draft_recover_local)
        app.router.add_post("/api/draft/undo", self.draft_undo)
        app.router.add_post("/api/draft/redo", self.draft_redo)
        app.router.add_post("/api/draft/rename", self.draft_rename)
        app.router.add_post("/api/draft/archive", self.draft_archive)
        app.router.add_post("/api/draft/restore", self.draft_restore)
        app.router.add_post("/api/draft/delete", self.draft_delete)
        app.router.add_post("/api/draft/duplicate", self.draft_duplicate)
        app.router.add_post("/api/import/text", self.import_text)
        app.router.add_post("/api/import/file", self.import_file)
        app.router.add_post("/api/import/resolve", self.import_resolve)
        app.router.add_post("/api/blob/upload", self.blob_upload)
        app.router.add_post("/api/blob/download", self.blob_download)
        app.router.add_post("/api/blob/publish", self.blob_publish)
        app.router.add_post("/api/blob/revoke", self.blob_revoke)
        app.router.add_post("/api/parse", self.parse_text)
        app.router.add_post("/api/conversion/review", self.conversion_review)
        app.router.add_post("/api/conversion/apply", self.conversion_apply)
        app.router.add_post("/api/export", self.export_output)
        app.router.add_post("/api/telegram/send", self.telegram_send)
        app.router.add_post("/api/telegraph/publish", self.telegraph_publish)
        app.router.add_post("/api/map/request", self.map_request)
        app.router.add_post("/api/map/status", self.map_status)
        app.router.add_post("/api/preference", self.preference_set)
        app.on_startup.append(self.startup)
        app.on_cleanup.append(self.cleanup)
        return app
