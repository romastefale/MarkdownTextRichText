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
        return validate_init_data(self.settings.telegram_token, raw, ttl_seconds=self.settings.init_data_ttl_seconds)

    async def _json_auth(self, request: web.Request) -> tuple[dict, dict]:
        try:
            data = await request.json()
        except Exception as exc:
            raise web.HTTPBadRequest(text=json.dumps({"ok": False, "error": "JSON inválido"}), content_type="application/json") from exc
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(text=json.dumps({"ok": False, "error": "Objeto JSON esperado"}), content_type="application/json")
        return data, self._auth(request, data)

    def _static(self, name: str) -> Path:
        path = (self.settings.static_path / name).resolve(); root = self.settings.static_path.resolve()
        if root not in path.parents and path != root: raise web.HTTPNotFound()
        return path

    def _upload_too_large(self):
        return web.json_response({"ok": False, "error": f"Arquivo excede o limite de {self.settings.max_upload_bytes} bytes."}, status=413)

    def _read_upload(self, upload) -> bytes:
        raw = upload.file.read(self.settings.max_upload_bytes + 1)
        if len(raw) > self.settings.max_upload_bytes:
            raise web.HTTPRequestEntityTooLarge(max_size=self.settings.max_upload_bytes, actual_size=len(raw))
        return raw

    async def index(self, request): return web.FileResponse(self._static("index.html"), headers={"Cache-Control":"no-store"})
    async def static_file(self, request):
        path=self._static(request.match_info.get("name") or "")
        if not path.is_file(): raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Cache-Control":"no-cache"})

    async def health(self, request):
        return web.json_response({"ok":True,"app":"mdtxtrt-rebuild","architecture":"modular-direct","document_schema":"mdtxtrt.document/v1","bot":bool(self.settings.telegram_token),"bot_username":self.telegram.username or None,"init_data_ttl_seconds":self.settings.init_data_ttl_seconds,"telegraph_account_mode":"one_anonymous_account_per_telegram_user","telegraph_token_encryption":"AES-256-GCM" if self.settings.telegraph_aes_key else "unavailable_missing_key","max_upload_bytes":self.settings.max_upload_bytes})

    async def bootstrap(self, request):
        data,user=await self._json_auth(request); uid=int(user["id"])
        return web.json_response({"ok":True,"user":{k:user.get(k) for k in ("id","first_name","last_name","username")},"drafts":self.store.list_drafts(uid,"active")+self.store.list_drafts(uid,"import_review"),"archived":self.store.list_drafts(uid,"archived"),"preferences":self.store.preferences(uid),"appearance":appearance(self.store.preferences(uid)),"pending_import":self.store.pending_action(uid,"import"),"destinations":self.store.list_telegram_destinations(uid),"requested_draft":data.get("draft")})

    async def draft_create(self, request):
        data,user=await self._json_auth(request); draft=self.store.create_draft(int(user["id"]),data.get("document") if isinstance(data.get("document"),dict) else new_document(),name=data.get("name"),session=data.get("session")); return web.json_response({"ok":True,"draft":draft})
    async def draft_load(self, request):
        data,user=await self._json_auth(request)
        try: draft=self.store.load_draft(int(user["id"]),str(data.get("draft_id") or "")); return web.json_response({"ok":True,"draft":draft})
        except KeyError as exc: return web.json_response({"ok":False,"error":str(exc)},status=404)
    async def draft_revise(self, request):
        data,user=await self._json_auth(request); uid=int(user["id"]); did=str(data.get("draft_id") or "")
        try:
            current=self.store.load_draft(uid,did); expected=str(data.get("expected_revision_id") or "")
            if expected and expected!=current["revision_id"]: return web.json_response({"ok":False,"error":"O servidor possui outra revisão atual. Escolha qual versão continuar; nenhuma mesclagem foi feita.","conflict":True,"server":current},status=409)
            draft=self.store.revise(uid,did,data.get("document") if isinstance(data.get("document"),dict) else current["document"],data.get("session") if isinstance(data.get("session"),dict) else current["session"],event_type=str(data.get("event_type") or "edit"),group_key=str(data.get("group_key") or "") or None,parent_revision_id=current["revision_id"]); return web.json_response({"ok":True,"draft":draft})
        except (KeyError,ValueError) as exc: return web.json_response({"ok":False,"error":str(exc)},status=400)
    async def draft_recover_local(self, request):
        data,user=await self._json_auth(request)
        if data.get("confirmed_choice")!="local": return web.json_response({"ok":False,"error":"A recuperação local exige escolha explícita da versão local."},status=409)
        uid=int(user["id"]); did=str(data.get("draft_id") or "")
        try:
            current=self.store.load_draft(uid,did); source=str(data.get("source_revision_id") or current["revision_id"]); draft=self.store.revise(uid,did,data.get("document") if isinstance(data.get("document"),dict) else current["document"],data.get("session") if isinstance(data.get("session"),dict) else current["session"],event_type="local_recovery",group_key="local_recovery",parent_revision_id=source); return web.json_response({"ok":True,"draft":draft,"branched_from":source})
        except (KeyError,ValueError) as exc:return web.json_response({"ok":False,"error":str(exc)},status=400)
    async def draft_undo(self,request):
        data,user=await self._json_auth(request)
        try:return web.json_response({"ok":True,"draft":self.store.undo(int(user["id"]),str(data.get("draft_id") or ""))})
        except KeyError as exc:return web.json_response({"ok":False,"error":str(exc)},status=404)
    async def draft_redo(self,request):
        data,user=await self._json_auth(request)
        try:return web.json_response({"ok":True,"draft":self.store.redo(int(user["id"]),str(data.get("draft_id") or ""),str(data.get("revision_id") or "") or None)})
        except (KeyError,ValueError) as exc:return web.json_response({"ok":False,"error":str(exc)},status=400)
    async def draft_rename(self,request):
        data,user=await self._json_auth(request); name=str(data.get("name") or "").strip()
        if not name:return web.json_response({"ok":False,"error":"Nome vazio."},status=400)
        try:return web.json_response({"ok":True,"draft":self.store.rename(int(user["id"]),str(data.get("draft_id") or ""),name)})
        except KeyError as exc:return web.json_response({"ok":False,"error":str(exc)},status=404)
    async def draft_archive(self,request):
        data,user=await self._json_auth(request)
        try:return web.json_response({"ok":True,"draft":self.store.set_status(int(user["id"]),str(data.get("draft_id") or ""),"archived","archive")})
        except KeyError as exc:return web.json_response({"ok":False,"error":str(exc)},status=404)
    async def draft_restore(self,request):
        data,user=await self._json_auth(request)
        try:return web.json_response({"ok":True,"draft":self.store.set_status(int(user["id"]),str(data.get("draft_id") or ""),"active","restore")})
        except KeyError as exc:return web.json_response({"ok":False,"error":str(exc)},status=404)
    async def draft_delete(self,request):
        data,user=await self._json_auth(request)
        if data.get("confirmed") is not True:return web.json_response({"ok":False,"error":"A exclusão definitiva exige confirmação explícita."},status=409)
        try:self.store.permanent_delete(int(user["id"]),str(data.get("draft_id") or ""));return web.json_response({"ok":True})
        except KeyError as exc:return web.json_response({"ok":False,"error":str(exc)},status=404)
    async def draft_duplicate(self,request):
        data,user=await self._json_auth(request)
        if data.get("confirmed") is not True:return web.json_response({"ok":False,"error":"Duplicar exige confirmação explícita; BLOBs podem ser compartilhados entre a cópia e o original."},status=409)
        try:return web.json_response({"ok":True,"draft":self.store.duplicate_draft(int(user["id"]),str(data.get("draft_id") or ""))})
        except KeyError as exc:return web.json_response({"ok":False,"error":str(exc)},status=404)

    async def import_text(self,request):
        data,user=await self._json_auth(request); text=str(data.get("text") or ""); mode=str(data.get("mode") or "") or None
        if mode is None and looks_like_markdown(text):return web.json_response({"ok":False,"requires_mode_choice":True,"choices":["markdown","literal"],"message":"O texto colado parece conter Markdown. Escolha como interpretar."},status=409)
        raw=text.encode("utf-8")
        if len(raw)>self.settings.max_upload_bytes:return self._upload_too_large()
        key=import_key_for_bytes("paste",raw,str(data.get("import_key") or "") or None); result=import_file(self.store,int(user["id"]),name="texto-colado.md" if mode=="markdown" else "texto-colado.txt",mime="text/markdown" if mode=="markdown" else "text/plain",raw=raw,import_key=key,mode=mode or "literal");return web.json_response(result)

    async def import_file(self,request):
        try:post=await request.post()
        except web.HTTPRequestEntityTooLarge:return self._upload_too_large()
        except Exception:return web.json_response({"ok":False,"error":"Upload inválido."},status=400)
        try:user=self._auth(request,dict(post))
        except AuthError as exc:return self.auth_error(exc)
        upload=post.get("file")
        if upload is None or not hasattr(upload,"file"):return web.json_response({"ok":False,"error":"Arquivo ausente."},status=400)
        try:raw=self._read_upload(upload)
        except web.HTTPRequestEntityTooLarge:return self._upload_too_large()
        name=getattr(upload,"filename",None) or "import.txt"; mime=getattr(upload,"content_type",None) or "application/octet-stream"; key=import_key_for_bytes("web",raw,str(post.get("import_key") or "") or None)
        try:
            result=import_file(self.store,int(user["id"]),name=name,mime=mime,raw=raw,import_key=key,encoding=str(post.get("encoding") or "") or None,mode=str(post.get("mode") or "") or None);return web.json_response(result)
        except EncodingChoiceRequired as exc:self.store.set_pending_action(int(user["id"]),"import",{"import_key":exc.import_key or key,"encoding_choices":exc.choices});return web.json_response({"ok":False,"requires_encoding_choice":True,"import_key":exc.import_key or key,"choices":exc.choices},status=409)
        except ValueError as exc:return web.json_response({"ok":False,"error":str(exc)},status=400)
    async def import_resolve(self,request):
        data,user=await self._json_auth(request);uid=int(user["id"]);key=str(data.get("import_key") or "")
        if not key:key=str((self.store.pending_action(uid,"import") or {}).get("payload",{}).get("import_key") or "")
        if not key:return web.json_response({"ok":False,"error":"Importação pendente não identificada."},status=404)
        try:
            result=import_stored_blob(self.store,uid,import_key=key,encoding=str(data.get("encoding") or "") or None,mode=str(data.get("mode") or "") or None)
            if result.get("ok"):self.store.clear_pending_action(uid,"import")
            return web.json_response(result)
        except EncodingChoiceRequired as exc:return web.json_response({"ok":False,"requires_encoding_choice":True,"import_key":key,"choices":exc.choices},status=409)
        except (KeyError,ValueError) as exc:return web.json_response({"ok":False,"error":str(exc)},status=400)
    async def blob_upload(self,request):
        try:post=await request.post()
        except web.HTTPRequestEntityTooLarge:return self._upload_too_large()
        except Exception:return web.json_response({"ok":False,"error":"Upload inválido."},status=400)
        try:user=self._auth(request,dict(post))
        except AuthError as exc:return self.auth_error(exc)
        upload=post.get("file")
        if upload is None or not hasattr(upload,"file"):return web.json_response({"ok":False,"error":"Arquivo ausente."},status=400)
        try:raw=self._read_upload(upload)
        except web.HTTPRequestEntityTooLarge:return self._upload_too_large()
        if not raw:return web.json_response({"ok":False,"error":"Arquivo vazio."},status=400)
        name=getattr(upload,"filename",None) or "arquivo.bin";mime=getattr(upload,"content_type",None) or "application/octet-stream";blob=self.store.put_blob(int(user["id"]),name,mime,raw);did=str(post.get("draft_id") or "")
        if did:
            try:self.store.attach_blob(int(user["id"]),did,blob["id"],logical_name=name,relation=str(post.get("relation") or "media"))
            except KeyError as exc:return web.json_response({"ok":False,"error":str(exc)},status=404)
        return web.json_response({"ok":True,"blob":blob})
    async def blob_download(self,request):
        data,user=await self._json_auth(request)
        try:blob=self.store.get_blob(int(user["id"]),str(data.get("blob_id") or ""))
        except KeyError as exc:return web.json_response({"ok":False,"error":str(exc)},status=404)
        payload=bytes(blob["data"]);actual=hashlib.sha256(payload).hexdigest();corrupt=actual!=blob["sha256"]
        if corrupt and data.get("allow_corrupt") is not True:return web.json_response({"ok":False,"error":"SHA-256 do BLOB diverge do hash registrado.","sha256_expected":blob["sha256"],"sha256_actual":actual,"can_download_with_alert":True},status=409)
        headers={"Content-Disposition":f"attachment; filename*=UTF-8''{quote(blob['name'])}","X-MDTXTRT-SHA256":actual}
        if corrupt:headers["X-MDTXTRT-Integrity-Warning"]="sha256-mismatch-user-confirmed"
        return web.Response(body=payload,content_type=blob["mime"],headers=headers)
    async def blob_publish(self,request):
        data,user=await self._json_auth(request)
        if data.get("confirmed") is not True:return web.json_response({"ok":False,"error":"Criar URL pública exige confirmação explícita."},status=409)
        token=secrets.token_urlsafe(36)
        try:item=self.store.create_public_blob(int(user["id"]),str(data.get("blob_id") or ""),token)
        except KeyError as exc:return web.json_response({"ok":False,"error":str(exc)},status=404)
        origin=self.settings.web_app_url or str(request.url.origin());return web.json_response({"ok":True,"token":item["token"],"url":f"{origin.rstrip('/')}/b/{item['token']}"})
    async def blob_revoke(self,request):
        data,user=await self._json_auth(request);return web.json_response({"ok":self.store.revoke_public_blob(int(user["id"]),str(data.get("token") or ""))})
    async def public_blob(self,request):
        item=self.store.public_blob(str(request.match_info.get("token") or ""))
        if not item:raise web.HTTPNotFound(text="Arquivo indisponível")
        payload=bytes(item["data"])
        if hashlib.sha256(payload).hexdigest()!=item["sha256"]:raise web.HTTPConflict(text="Integridade do arquivo não pôde ser confirmada")
        return web.Response(body=payload,content_type=item["mime"],headers={"Content-Disposition":f"inline; filename*=UTF-8''{quote(item['name'])}","Cache-Control":"private, no-store"})

    async def parse_text(self,request):
        data,user=await self._json_auth(request);mode=str(data.get("mode") or "markdown");text=str(data.get("text") or "")
        try:
            document,report=import_literal_text(text) if mode=="literal" else import_markdown(text) if mode=="markdown" else (_ for _ in ()).throw(ValueError("Modo de parse desconhecido."));return web.json_response({"ok":True,"document":document,"report":report})
        except ValueError as exc:return web.json_response({"ok":False,"error":str(exc)},status=400)
    async def conversion_review(self,request):
        data,user=await self._json_auth(request)
        try:draft=self.store.load_draft(int(user["id"]),str(data.get("draft_id") or ""));report=review(draft["document"],str(data.get("destination") or ""));return web.json_response({"ok":True,"draft_revision_id":draft["revision_id"],"original":draft["document"],"original_markdown":review(draft["document"],"markdown")["projection"],"review":report})
        except (KeyError,ValueError) as exc:return web.json_response({"ok":False,"error":str(exc)},status=400)
    async def conversion_apply(self,request):
        data,user=await self._json_auth(request);uid=int(user["id"])
        try:
            draft=self.store.load_draft(uid,str(data.get("draft_id") or ""))
            if str(data.get("revision_id") or "")!=draft["revision_id"]:return web.json_response({"ok":False,"error":"A revisão mudou desde a conversão. Revise novamente antes de aplicar ao documento."},status=409)
            proposal=apply_review(draft["document"],str(data.get("converted") or ""),str(data.get("destination") or ""))
            if proposal["requires_confirmation"] and data.get("confirmed") is not True:return web.json_response({"ok":False,"requires_confirmation":True,**proposal},status=409)
            updated=self.store.revise(uid,draft["id"],proposal["proposed_document"],draft["session"],event_type="conversion_apply",parent_revision_id=draft["revision_id"]);return web.json_response({"ok":True,"draft":updated,"losses":proposal["losses"]})
        except (KeyError,ValueError) as exc:return web.json_response({"ok":False,"error":str(exc)},status=400)
    async def export_output(self,request):
        data,user=await self._json_auth(request)
        try:
            draft=self.store.load_draft(int(user["id"]),str(data.get("draft_id") or ""))
            if str(data.get("revision_id") or "")!=draft["revision_id"]:return web.json_response({"ok":False,"error":"A revisão mudou desde a revisão da exportação."},status=409)
            dest=str(data.get("destination") or "markdown");report=review(draft["document"],dest);output=str(data.get("output_override")) if data.get("output_override") is not None else str(report["projection"]);return web.json_response({"ok":True,"filename":f"{draft['name']}.{'txt' if dest=='txt' else 'md'}","content":output,"manual_output":data.get("output_override") is not None})
        except (KeyError,ValueError) as exc:return web.json_response({"ok":False,"error":str(exc)},status=400)
    async def telegram_send(self,request):
        data,user=await self._json_auth(request);uid=int(user["id"])
        if self.telegram.bot is None:return web.json_response({"ok":False,"error":"Bot não iniciado."},status=503)
        try:
            draft=self.store.load_draft(uid,str(data.get("draft_id") or ""))
            if str(data.get("revision_id") or "")!=draft["revision_id"]:return web.json_response({"ok":False,"error":"A revisão mudou depois da revisão Telegram. Revise novamente antes de enviar."},status=409)
            report=review(draft["document"],"telegram")
            if report["warnings"] and data.get("confirmed") is not True:return web.json_response({"ok":False,"requires_confirmation":True,"review":report},status=409)
            did=str(data.get("destination_id") or "")
            if not did:raise ValueError("Escolha um destino Telegram autorizado.")
            destination=self.store.telegram_destination(uid,did);raw=str(destination["chat_id"]);chat=int(raw) if raw.lstrip("-").isdigit() else raw;override=data.get("output_override");sent=await (self.telegram.send_document_to_chat(uid,chat,draft["document"],format_mode=str(data.get("format") or "rich_markdown")) if override is None else self.telegram.send_markdown_to_chat(chat,str(override)));mid=getattr(sent,"message_id",None);publication=self.store.add_publication(uid,draft["id"],draft["revision_id"],"telegram",external_id=str(mid) if mid is not None else None,metadata={"destination_id":did,"chat_id":chat,"message_id":mid,"manual_output":override is not None});return web.json_response({"ok":True,"message_id":mid,"destination_id":did,"chat_id":chat,"publication":publication})
        except (KeyError,ValueError) as exc:return web.json_response({"ok":False,"error":str(exc)},status=400)
        except Exception as exc:return web.json_response({"ok":False,"error":str(exc)},status=502)
    async def telegraph_publish(self,request):
        data,user=await self._json_auth(request);uid=int(user["id"])
        try:
            draft=self.store.load_draft(uid,str(data.get("draft_id") or ""))
            if str(data.get("revision_id") or "")!=draft["revision_id"]:return web.json_response({"ok":False,"error":"A revisão mudou depois da revisão Telegraph. Revise novamente."},status=409)
            report=self.telegraph.review(draft["document"]);needs=bool(report["adaptations"] or report["unsupported"])
            if needs and data.get("confirmed") is not True:return web.json_response({"ok":False,"requires_confirmation":True,"review":report},status=409)
            result=await self.telegraph.publish_async(uid,draft,str(data.get("title") or draft["name"]),update_existing=data.get("update_existing") is True,html_override=str(data.get("output_override")) if data.get("output_override") is not None else None);return web.json_response({"ok":True,**result})
        except (KeyError,ValueError) as exc:return web.json_response({"ok":False,"error":str(exc)},status=400)
        except Exception as exc:return web.json_response({"ok":False,"error":str(exc)},status=502)
    async def map_request(self,request):
        data,user=await self._json_auth(request);uid=int(user["id"]);did=str(data.get("draft_id") or "");nid=str(data.get("node_id") or "")
        try:self.store.load_draft(uid,did);item=self.store.create_map_request(uid,did,nid);await self.telegram.notify_map_request(uid,did) if self.telegram.bot is not None else _noop();url=f"https://t.me/{self.telegram.username}" if self.telegram.username else None;return web.json_response({"ok":True,"request":item,"telegram_url":url})
        except KeyError as exc:return web.json_response({"ok":False,"error":str(exc)},status=404)
    async def map_status(self,request):
        data,user=await self._json_auth(request)
        try:return web.json_response({"ok":True,"request":self.store.map_request(int(user["id"]),str(data.get("request_id") or ""))})
        except KeyError as exc:return web.json_response({"ok":False,"error":str(exc)},status=404)
    async def preference_set(self,request):
        data,user=await self._json_auth(request);key=str(data.get("key") or "").strip()
        if not key:return web.json_response({"ok":False,"error":"Preferência sem chave."},status=400)
        value=data.get("value")
        if key=="accent":
            try:value=normalize_accent(value)
            except ValueError as exc:return web.json_response({"ok":False,"error":str(exc)},status=400)
        self.store.set_preference(int(user["id"]),key,value);return web.json_response({"ok":True,"preferences":self.store.preferences(int(user["id"]))})
    def auth_error(self,exc):return web.json_response({"ok":False,"error":str(exc),"expired":exc.expired,"preserve_local_work":True},status=401)
    @web.middleware
    async def errors(self,request,handler):
        try:response=await handler(request)
        except AuthError as exc:response=self.auth_error(exc)
        except web.HTTPRequestEntityTooLarge:response=self._upload_too_large()
        except web.HTTPException:raise
        except Exception as exc:response=web.json_response({"ok":False,"error":str(exc)},status=500)
        response.headers.setdefault("X-Content-Type-Options","nosniff");response.headers.setdefault("Referrer-Policy","no-referrer");response.headers.setdefault("Permissions-Policy","geolocation=(), camera=(), microphone=()")
        if request.path=="/" or request.path.endswith(".js") or request.path.endswith(".css"):response.headers.setdefault("Content-Security-Policy","default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; img-src 'self' data: blob: https:; media-src 'self' blob: https:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'")
        return response
    async def startup(self,app):await self.telegram.start()
    async def cleanup(self,app):await self.telegram.stop()
    def app(self):
        app=web.Application(client_max_size=self.settings.max_upload_bytes,middlewares=[self.errors])
        routes=[("get","/",self.index),("get","/static/{name}",self.static_file),("get","/health",self.health),("get","/b/{token}",self.public_blob),("post","/api/bootstrap",self.bootstrap),("post","/api/draft/create",self.draft_create),("post","/api/draft/load",self.draft_load),("post","/api/draft/revise",self.draft_revise),("post","/api/draft/recover-local",self.draft_recover_local),("post","/api/draft/undo",self.draft_undo),("post","/api/draft/redo",self.draft_redo),("post","/api/draft/rename",self.draft_rename),("post","/api/draft/archive",self.draft_archive),("post","/api/draft/restore",self.draft_restore),("post","/api/draft/delete",self.draft_delete),("post","/api/draft/duplicate",self.draft_duplicate),("post","/api/import/text",self.import_text),("post","/api/import/file",self.import_file),("post","/api/import/resolve",self.import_resolve),("post","/api/blob/upload",self.blob_upload),("post","/api/blob/download",self.blob_download),("post","/api/blob/publish",self.blob_publish),("post","/api/blob/revoke",self.blob_revoke),("post","/api/parse",self.parse_text),("post","/api/conversion/review",self.conversion_review),("post","/api/conversion/apply",self.conversion_apply),("post","/api/export",self.export_output),("post","/api/telegram/send",self.telegram_send),("post","/api/telegraph/publish",self.telegraph_publish),("post","/api/map/request",self.map_request),("post","/api/map/status",self.map_status),("post","/api/preference",self.preference_set)]
        for method,path,handler in routes:getattr(app.router,f"add_{method}")(path,handler)
        app.on_startup.append(self.startup);app.on_cleanup.append(self.cleanup);return app


async def _noop():
    return None
