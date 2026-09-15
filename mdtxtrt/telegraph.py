from __future__ import annotations

import asyncio
import os
from functools import partial

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from telegraph import Telegraph

from mdtxtrt.conversion.markdown import to_markdown
from mdtxtrt.conversion.legacy_projection import CanonicalDocument


class TelegraphService:
    def __init__(self, store, aes_key: bytes | None):
        self.store = store
        self.aes_key = aes_key

    def _cipher(self) -> AESGCM:
        if self.aes_key is None:
            raise RuntimeError("KEY ausente; publicação editável no Telegraph está indisponível.")
        return AESGCM(self.aes_key)

    def _encrypt(self, token: str, user_id: int) -> tuple[bytes, bytes]:
        nonce = os.urandom(12)
        ciphertext = self._cipher().encrypt(nonce, token.encode("utf-8"), str(user_id).encode("ascii"))
        return nonce, ciphertext

    def _decrypt(self, account: dict, user_id: int) -> str:
        raw = self._cipher().decrypt(bytes(account["nonce"]), bytes(account["ciphertext"]), str(user_id).encode("ascii"))
        return raw.decode("utf-8")

    def _token_for_user(self, user_id: int) -> str:
        existing = self.store.telegraph_account(user_id)
        if existing:
            return self._decrypt(existing, user_id)
        client = Telegraph()
        created = client.create_account(short_name="MDTXTRT")
        token = str(created.get("access_token") or "")
        if not token:
            raise RuntimeError("Telegraph não retornou access_token.")
        nonce, ciphertext = self._encrypt(token, user_id)
        self.store.save_telegraph_account(user_id, nonce, ciphertext)
        return token

    def review(self, document: dict) -> dict:
        markdown = to_markdown(document)
        projection = CanonicalDocument.from_markdown(markdown).telegraph()
        return {
            "html": projection.html,
            "adaptations": list(projection.adaptations),
            "unsupported": list(projection.unsupported),
            "compatible": projection.compatible,
        }

    def publish(self, user_id: int, draft: dict, title: str, *, update_existing: bool = False, html_override: str | None = None) -> dict:
        projection = self.review(draft["document"])
        token = self._token_for_user(user_id)
        client = Telegraph(access_token=token)
        title = (title or draft.get("name") or "Sem título").strip()[:256] or "Sem título"
        html_content = projection["html"] if html_override is None else str(html_override)
        previous = self.store.latest_publication(user_id, draft["id"], "telegraph")
        if update_existing and previous and previous.get("external_path"):
            page = client.edit_page(path=previous["external_path"], title=title, html_content=html_content)
        else:
            page = client.create_page(title=title, html_content=html_content)
        path = page.get("path")
        url = page.get("url")
        publication = self.store.add_publication(
            user_id,
            draft["id"],
            draft["revision_id"],
            "telegraph",
            external_id=url,
            external_path=path,
            metadata={"title": title, "adaptations": projection["adaptations"], "unsupported": projection["unsupported"], "manual_output": html_override is not None},
        )
        return {"url": url, "path": path, "title": title, "publication": publication, "html": html_content, "manual_output": html_override is not None, **{key: value for key, value in projection.items() if key != "html"}}

    async def publish_async(self, user_id: int, draft: dict, title: str, *, update_existing: bool = False, html_override: str | None = None) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(self.publish, user_id, draft, title, update_existing=update_existing, html_override=html_override))
