from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import sqlite3
import time
import uuid

from mdtxtrt.domain.document import normalize_document, suggested_name
from mdtxtrt.domain.session import normalize_session


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _ms() -> int:
    return int(time.time() * 1000)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA foreign_keys=ON")
        self._schema(con)
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _schema(self, con: sqlite3.Connection) -> None:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS drafts (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                current_revision_id TEXT,
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                import_key TEXT,
                UNIQUE(user_id, import_key)
            );
            CREATE INDEX IF NOT EXISTS idx_drafts_user ON drafts(user_id, updated_at_ms DESC);

            CREATE TABLE IF NOT EXISTS revisions (
                id TEXT PRIMARY KEY,
                draft_id TEXT NOT NULL,
                parent_revision_id TEXT,
                created_at_ms INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                group_key TEXT,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                document_json TEXT NOT NULL,
                session_json TEXT NOT NULL,
                FOREIGN KEY(draft_id) REFERENCES drafts(id) ON DELETE CASCADE,
                FOREIGN KEY(parent_revision_id) REFERENCES revisions(id)
            );
            CREATE INDEX IF NOT EXISTS idx_revisions_draft ON revisions(draft_id, created_at_ms);
            CREATE INDEX IF NOT EXISTS idx_revisions_parent ON revisions(parent_revision_id, created_at_ms);

            CREATE TABLE IF NOT EXISTS blobs (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                mime TEXT NOT NULL,
                size INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                data BLOB NOT NULL,
                created_at_ms INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_blobs_user ON blobs(user_id, created_at_ms DESC);

            CREATE TABLE IF NOT EXISTS draft_blobs (
                draft_id TEXT NOT NULL,
                blob_id TEXT NOT NULL,
                logical_name TEXT,
                relation TEXT NOT NULL DEFAULT 'attachment',
                created_at_ms INTEGER NOT NULL,
                PRIMARY KEY(draft_id, blob_id),
                FOREIGN KEY(draft_id) REFERENCES drafts(id) ON DELETE CASCADE,
                FOREIGN KEY(blob_id) REFERENCES blobs(id)
            );

            CREATE TABLE IF NOT EXISTS imports (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                import_key TEXT NOT NULL,
                draft_id TEXT,
                blob_id TEXT,
                status TEXT NOT NULL,
                report_json TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                UNIQUE(user_id, import_key)
            );

            CREATE TABLE IF NOT EXISTS map_requests (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                draft_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                status TEXT NOT NULL,
                latitude REAL,
                longitude REAL,
                name TEXT,
                address TEXT,
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_map_user_status ON map_requests(user_id, status, created_at_ms DESC);

            CREATE TABLE IF NOT EXISTS telegraph_accounts (
                user_id INTEGER PRIMARY KEY,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL,
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS telegram_destinations (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                chat_id TEXT NOT NULL,
                chat_type TEXT NOT NULL,
                title TEXT,
                username TEXT,
                source TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                UNIQUE(user_id, chat_id)
            );
            CREATE INDEX IF NOT EXISTS idx_telegram_destinations_user ON telegram_destinations(user_id, updated_at_ms DESC);

            CREATE TABLE IF NOT EXISTS publications (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                draft_id TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                destination TEXT NOT NULL,
                external_id TEXT,
                external_path TEXT,
                metadata_json TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_publications_draft ON publications(draft_id, created_at_ms DESC);

            CREATE TABLE IF NOT EXISTS preferences (
                user_id INTEGER NOT NULL,
                preference_key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                PRIMARY KEY(user_id, preference_key)
            );

            CREATE TABLE IF NOT EXISTS pending_actions (
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                PRIMARY KEY(user_id, action)
            );

            CREATE TABLE IF NOT EXISTS public_blobs (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                blob_id TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL,
                revoked_at_ms INTEGER,
                FOREIGN KEY(blob_id) REFERENCES blobs(id)
            );
            CREATE INDEX IF NOT EXISTS idx_public_blobs_blob ON public_blobs(blob_id, revoked_at_ms);
            """
        )

    def _revision_row(self, con: sqlite3.Connection, revision_id: str):
        return con.execute("SELECT * FROM revisions WHERE id=?", (revision_id,)).fetchone()

    def _snapshot(self, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        return {
            "revision_id": row["id"],
            "parent_revision_id": row["parent_revision_id"],
            "created_at_ms": row["created_at_ms"],
            "event_type": row["event_type"],
            "group_key": row["group_key"],
            "name": row["name"],
            "status": row["status"],
            "document": json.loads(row["document_json"]),
            "session": json.loads(row["session_json"]),
        }

    def create_draft(self, user_id: int, document: dict, *, name: str | None = None, import_key: str | None = None, status: str = "active", session: dict | None = None, event_type: str = "create") -> dict:
        document = normalize_document(document)
        session = normalize_session(session)
        now = _ms()
        with self.connect() as con:
            if import_key:
                existing = con.execute("SELECT id,current_revision_id FROM drafts WHERE user_id=? AND import_key=?", (user_id, import_key)).fetchone()
                if existing:
                    return self.load_draft(user_id, existing["id"])
            draft_id = _id("draft")
            revision_id = _id("rev")
            resolved_name = (name or "").strip() or suggested_name(document)
            con.execute(
                "INSERT INTO drafts(id,user_id,current_revision_id,created_at_ms,updated_at_ms,import_key) VALUES(?,?,?,?,?,?)",
                (draft_id, user_id, revision_id, now, now, import_key),
            )
            con.execute(
                "INSERT INTO revisions(id,draft_id,parent_revision_id,created_at_ms,event_type,group_key,name,status,document_json,session_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (revision_id, draft_id, None, now, event_type, None, resolved_name, status, _json(document), _json(session)),
            )
        return self.load_draft(user_id, draft_id)

    def load_draft(self, user_id: int, draft_id: str) -> dict:
        with self.connect() as con:
            draft = con.execute("SELECT * FROM drafts WHERE id=? AND user_id=?", (draft_id, user_id)).fetchone()
            if not draft:
                raise KeyError("Rascunho não encontrado.")
            snapshot = self._snapshot(self._revision_row(con, draft["current_revision_id"]))
            children = con.execute("SELECT id,created_at_ms,event_type,name,status FROM revisions WHERE parent_revision_id=? ORDER BY created_at_ms,id", (draft["current_revision_id"],)).fetchall()
            return {
                "id": draft["id"],
                "created_at_ms": draft["created_at_ms"],
                "updated_at_ms": draft["updated_at_ms"],
                "import_key": draft["import_key"],
                **(snapshot or {}),
                "redo_choices": [dict(row) for row in children],
            }

    def list_drafts(self, user_id: int, status: str | None = None) -> list[dict]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT d.id,d.created_at_ms,d.updated_at_ms,d.current_revision_id,r.name,r.status FROM drafts d JOIN revisions r ON r.id=d.current_revision_id WHERE d.user_id=? ORDER BY d.updated_at_ms DESC",
                (user_id,),
            ).fetchall()
            result = []
            for row in rows:
                if status and row["status"] != status:
                    continue
                result.append(dict(row))
            return result

    def revise(self, user_id: int, draft_id: str, document: dict, session: dict | None, *, event_type: str, group_key: str | None = None, parent_revision_id: str | None = None, name: str | None = None, status: str | None = None) -> dict:
        document = normalize_document(document)
        session = normalize_session(session)
        now = _ms()
        with self.connect() as con:
            draft = con.execute("SELECT * FROM drafts WHERE id=? AND user_id=?", (draft_id, user_id)).fetchone()
            if not draft:
                raise KeyError("Rascunho não encontrado.")
            current = self._revision_row(con, draft["current_revision_id"])
            base_id = parent_revision_id or draft["current_revision_id"]
            base = self._revision_row(con, base_id)
            if not base or base["draft_id"] != draft_id:
                raise ValueError("Revisão-base inválida.")
            resolved_name = current["name"] if name is None else str(name).strip() or current["name"]
            resolved_status = current["status"] if status is None else status
            doc_json = _json(document)
            session_json = _json(session)
            if current and current["document_json"] == doc_json and current["session_json"] == session_json and current["name"] == resolved_name and current["status"] == resolved_status:
                return self.load_draft(user_id, draft_id)
            revision_id = _id("rev")
            con.execute(
                "INSERT INTO revisions(id,draft_id,parent_revision_id,created_at_ms,event_type,group_key,name,status,document_json,session_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (revision_id, draft_id, base_id, now, event_type, group_key, resolved_name, resolved_status, doc_json, session_json),
            )
            con.execute("UPDATE drafts SET current_revision_id=?,updated_at_ms=? WHERE id=?", (revision_id, now, draft_id))
        return self.load_draft(user_id, draft_id)

    def move_pointer(self, user_id: int, draft_id: str, revision_id: str) -> dict:
        now = _ms()
        with self.connect() as con:
            draft = con.execute("SELECT id FROM drafts WHERE id=? AND user_id=?", (draft_id, user_id)).fetchone()
            target = self._revision_row(con, revision_id)
            if not draft or not target or target["draft_id"] != draft_id:
                raise KeyError("Revisão não encontrada.")
            con.execute("UPDATE drafts SET current_revision_id=?,updated_at_ms=? WHERE id=?", (revision_id, now, draft_id))
        return self.load_draft(user_id, draft_id)

    def undo(self, user_id: int, draft_id: str) -> dict:
        current = self.load_draft(user_id, draft_id)
        parent = current.get("parent_revision_id")
        if not parent:
            return current
        return self.move_pointer(user_id, draft_id, parent)

    def redo(self, user_id: int, draft_id: str, revision_id: str | None = None) -> dict:
        current = self.load_draft(user_id, draft_id)
        choices = current.get("redo_choices") or []
        if revision_id:
            if revision_id not in {item["id"] for item in choices}:
                raise ValueError("A revisão escolhida não é uma ramificação de Redo disponível.")
            return self.move_pointer(user_id, draft_id, revision_id)
        if len(choices) == 1:
            return self.move_pointer(user_id, draft_id, choices[0]["id"])
        if len(choices) > 1:
            return {**current, "redo_requires_choice": True}
        return current

    def rename(self, user_id: int, draft_id: str, name: str) -> dict:
        current = self.load_draft(user_id, draft_id)
        return self.revise(user_id, draft_id, current["document"], current["session"], event_type="rename", parent_revision_id=current["revision_id"], name=name)

    def set_status(self, user_id: int, draft_id: str, status: str, event_type: str) -> dict:
        if status not in {"active", "archived", "deleted", "import_review"}:
            raise ValueError("Estado de rascunho inválido.")
        current = self.load_draft(user_id, draft_id)
        return self.revise(user_id, draft_id, current["document"], current["session"], event_type=event_type, parent_revision_id=current["revision_id"], status=status)

    def permanent_delete(self, user_id: int, draft_id: str) -> None:
        with self.connect() as con:
            draft = con.execute("SELECT id FROM drafts WHERE id=? AND user_id=?", (draft_id, user_id)).fetchone()
            if not draft:
                raise KeyError("Rascunho não encontrado.")
            exclusive = con.execute(
                "SELECT db.blob_id FROM draft_blobs db WHERE db.draft_id=? AND NOT EXISTS(SELECT 1 FROM draft_blobs other WHERE other.blob_id=db.blob_id AND other.draft_id<>db.draft_id)",
                (draft_id,),
            ).fetchall()
            con.execute("DELETE FROM drafts WHERE id=?", (draft_id,))
            for row in exclusive:
                con.execute("DELETE FROM blobs WHERE id=?", (row["blob_id"],))

    def put_blob(self, user_id: int, name: str, mime: str, data: bytes) -> dict:
        blob_id = _id("blob")
        now = _ms()
        sha = hashlib.sha256(data).hexdigest()
        with self.connect() as con:
            con.execute(
                "INSERT INTO blobs(id,user_id,name,mime,size,sha256,data,created_at_ms) VALUES(?,?,?,?,?,?,?,?)",
                (blob_id, user_id, name or "arquivo.bin", mime or "application/octet-stream", len(data), sha, sqlite3.Binary(data), now),
            )
        return {"id": blob_id, "name": name or "arquivo.bin", "mime": mime or "application/octet-stream", "size": len(data), "sha256": sha, "created_at_ms": now}

    def get_blob(self, user_id: int, blob_id: str) -> dict:
        with self.connect() as con:
            row = con.execute("SELECT * FROM blobs WHERE id=? AND user_id=?", (blob_id, user_id)).fetchone()
            if not row:
                raise KeyError("Arquivo não encontrado.")
            return dict(row)

    def attach_blob(self, user_id: int, draft_id: str, blob_id: str, *, logical_name: str | None = None, relation: str = "attachment") -> None:
        now = _ms()
        with self.connect() as con:
            draft = con.execute("SELECT id FROM drafts WHERE id=? AND user_id=?", (draft_id, user_id)).fetchone()
            blob = con.execute("SELECT id FROM blobs WHERE id=? AND user_id=?", (blob_id, user_id)).fetchone()
            if not draft or not blob:
                raise KeyError("Rascunho ou arquivo não encontrado.")
            con.execute(
                "INSERT OR IGNORE INTO draft_blobs(draft_id,blob_id,logical_name,relation,created_at_ms) VALUES(?,?,?,?,?)",
                (draft_id, blob_id, logical_name, relation, now),
            )

    def duplicate_draft(self, user_id: int, draft_id: str) -> dict:
        original = self.load_draft(user_id, draft_id)
        duplicate = self.create_draft(user_id, original["document"], name=original["name"] + " — cópia", session=original["session"], event_type="duplicate")
        with self.connect() as con:
            blobs = con.execute("SELECT blob_id,logical_name,relation FROM draft_blobs WHERE draft_id=?", (draft_id,)).fetchall()
            for row in blobs:
                con.execute(
                    "INSERT OR IGNORE INTO draft_blobs(draft_id,blob_id,logical_name,relation,created_at_ms) VALUES(?,?,?,?,?)",
                    (duplicate["id"], row["blob_id"], row["logical_name"], row["relation"], _ms()),
                )
        return self.load_draft(user_id, duplicate["id"])

    def get_import(self, user_id: int, import_key: str) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM imports WHERE user_id=? AND import_key=?", (user_id, import_key)).fetchone()
            if not row:
                return None
            value = dict(row)
            value["report"] = json.loads(value.pop("report_json"))
            return value

    def import_record(self, user_id: int, import_key: str, *, status: str, report: dict, draft_id: str | None = None, blob_id: str | None = None) -> dict:
        now = _ms()
        import_id = _id("import")
        with self.connect() as con:
            existing = con.execute("SELECT * FROM imports WHERE user_id=? AND import_key=?", (user_id, import_key)).fetchone()
            if existing:
                return {**dict(existing), "report": json.loads(existing["report_json"])}
            con.execute(
                "INSERT INTO imports(id,user_id,import_key,draft_id,blob_id,status,report_json,created_at_ms,updated_at_ms) VALUES(?,?,?,?,?,?,?,?,?)",
                (import_id, user_id, import_key, draft_id, blob_id, status, _json(report), now, now),
            )
            return {"id": import_id, "user_id": user_id, "import_key": import_key, "draft_id": draft_id, "blob_id": blob_id, "status": status, "report": report, "created_at_ms": now, "updated_at_ms": now}

    def update_import(self, user_id: int, import_key: str, *, status: str, report: dict, draft_id: str | None = None, blob_id: str | None = None) -> None:
        with self.connect() as con:
            current = con.execute("SELECT draft_id,blob_id FROM imports WHERE user_id=? AND import_key=?", (user_id, import_key)).fetchone()
            if not current:
                raise KeyError("Importação não encontrada.")
            resolved_draft = current["draft_id"] if draft_id is None else draft_id
            resolved_blob = current["blob_id"] if blob_id is None else blob_id
            con.execute(
                "UPDATE imports SET draft_id=?,blob_id=?,status=?,report_json=?,updated_at_ms=? WHERE user_id=? AND import_key=?",
                (resolved_draft, resolved_blob, status, _json(report), _ms(), user_id, import_key),
            )

    def set_import_draft(self, user_id: int, import_key: str, draft_id: str, status: str, report: dict) -> None:
        self.update_import(user_id, import_key, status=status, report=report, draft_id=draft_id)

    def create_map_request(self, user_id: int, draft_id: str, node_id: str) -> dict:
        request_id = _id("map")
        now = _ms()
        with self.connect() as con:
            con.execute(
                "INSERT INTO map_requests(id,user_id,draft_id,node_id,status,created_at_ms,updated_at_ms) VALUES(?,?,?,?,?,?,?)",
                (request_id, user_id, draft_id, node_id, "pending", now, now),
            )
        return {"id": request_id, "draft_id": draft_id, "node_id": node_id, "status": "pending", "created_at_ms": now}

    def pending_map_request(self, user_id: int) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM map_requests WHERE user_id=? AND status='pending' ORDER BY created_at_ms DESC LIMIT 1", (user_id,)).fetchone()
            return dict(row) if row else None

    def complete_map_request(self, user_id: int, latitude: float, longitude: float, *, name: str | None = None, address: str | None = None) -> dict | None:
        now = _ms()
        with self.connect() as con:
            row = con.execute("SELECT * FROM map_requests WHERE user_id=? AND status='pending' ORDER BY created_at_ms DESC LIMIT 1", (user_id,)).fetchone()
            if not row:
                return None
            con.execute(
                "UPDATE map_requests SET status='received',latitude=?,longitude=?,name=?,address=?,updated_at_ms=? WHERE id=?",
                (latitude, longitude, name, address, now, row["id"]),
            )
            updated = con.execute("SELECT * FROM map_requests WHERE id=?", (row["id"],)).fetchone()
            return dict(updated)

    def map_request(self, user_id: int, request_id: str) -> dict:
        with self.connect() as con:
            row = con.execute("SELECT * FROM map_requests WHERE id=? AND user_id=?", (request_id, user_id)).fetchone()
            if not row:
                raise KeyError("Solicitação de mapa não encontrada.")
            return dict(row)

    def telegraph_account(self, user_id: int) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM telegraph_accounts WHERE user_id=?", (user_id,)).fetchone()
            return dict(row) if row else None

    def save_telegraph_account(self, user_id: int, nonce: bytes, ciphertext: bytes) -> None:
        now = _ms()
        with self.connect() as con:
            con.execute(
                "INSERT INTO telegraph_accounts(user_id,nonce,ciphertext,created_at_ms,updated_at_ms) VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET nonce=excluded.nonce,ciphertext=excluded.ciphertext,updated_at_ms=excluded.updated_at_ms",
                (user_id, sqlite3.Binary(nonce), sqlite3.Binary(ciphertext), now, now),
            )


    def remember_telegram_destination(self, user_id: int, chat_id: int | str, *, chat_type: str, title: str | None = None, username: str | None = None, source: str = "bot_update") -> dict:
        now = _ms()
        value = str(chat_id)
        with self.connect() as con:
            row = con.execute("SELECT id,created_at_ms FROM telegram_destinations WHERE user_id=? AND chat_id=?", (user_id, value)).fetchone()
            destination_id = row["id"] if row else _id("dest")
            created = int(row["created_at_ms"]) if row else now
            con.execute(
                "INSERT INTO telegram_destinations(id,user_id,chat_id,chat_type,title,username,source,created_at_ms,updated_at_ms) VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(user_id,chat_id) DO UPDATE SET chat_type=excluded.chat_type,title=excluded.title,username=excluded.username,source=excluded.source,updated_at_ms=excluded.updated_at_ms",
                (destination_id, user_id, value, chat_type or "unknown", title, username, source, created, now),
            )
            saved = con.execute("SELECT * FROM telegram_destinations WHERE user_id=? AND chat_id=?", (user_id, value)).fetchone()
            return dict(saved)

    def list_telegram_destinations(self, user_id: int) -> list[dict]:
        with self.connect() as con:
            rows = con.execute("SELECT id,chat_id,chat_type,title,username,source,created_at_ms,updated_at_ms FROM telegram_destinations WHERE user_id=? ORDER BY updated_at_ms DESC", (user_id,)).fetchall()
            return [dict(row) for row in rows]

    def telegram_destination(self, user_id: int, destination_id: str) -> dict:
        with self.connect() as con:
            row = con.execute("SELECT id,chat_id,chat_type,title,username,source,created_at_ms,updated_at_ms FROM telegram_destinations WHERE user_id=? AND id=?", (user_id, destination_id)).fetchone()
            if not row:
                raise KeyError("Destino Telegram não autorizado para este usuário.")
            return dict(row)

    def add_publication(self, user_id: int, draft_id: str, revision_id: str, destination: str, *, external_id: str | None = None, external_path: str | None = None, metadata: dict | None = None) -> dict:
        publication_id = _id("pub")
        now = _ms()
        with self.connect() as con:
            con.execute(
                "INSERT INTO publications(id,user_id,draft_id,revision_id,destination,external_id,external_path,metadata_json,created_at_ms) VALUES(?,?,?,?,?,?,?,?,?)",
                (publication_id, user_id, draft_id, revision_id, destination, external_id, external_path, _json(metadata or {}), now),
            )
        return {"id": publication_id, "destination": destination, "external_id": external_id, "external_path": external_path, "metadata": metadata or {}, "created_at_ms": now}

    def latest_publication(self, user_id: int, draft_id: str, destination: str) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM publications WHERE user_id=? AND draft_id=? AND destination=? ORDER BY created_at_ms DESC LIMIT 1", (user_id, draft_id, destination)).fetchone()
            if not row:
                return None
            value = dict(row)
            value["metadata"] = json.loads(value.pop("metadata_json"))
            return value

    def set_preference(self, user_id: int, key: str, value) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO preferences(user_id,preference_key,value_json,updated_at_ms) VALUES(?,?,?,?) ON CONFLICT(user_id,preference_key) DO UPDATE SET value_json=excluded.value_json,updated_at_ms=excluded.updated_at_ms",
                (user_id, key, _json(value), _ms()),
            )

    def preferences(self, user_id: int) -> dict:
        with self.connect() as con:
            rows = con.execute("SELECT preference_key,value_json FROM preferences WHERE user_id=?", (user_id,)).fetchall()
            return {row["preference_key"]: json.loads(row["value_json"]) for row in rows}

    def set_pending_action(self, user_id: int, action: str, payload: dict | None = None) -> dict:
        now = _ms()
        with self.connect() as con:
            con.execute(
                "INSERT INTO pending_actions(user_id,action,payload_json,created_at_ms,updated_at_ms) VALUES(?,?,?,?,?) ON CONFLICT(user_id,action) DO UPDATE SET payload_json=excluded.payload_json,updated_at_ms=excluded.updated_at_ms",
                (user_id, action, _json(payload or {}), now, now),
            )
            row = con.execute("SELECT * FROM pending_actions WHERE user_id=? AND action=?", (user_id, action)).fetchone()
            value = dict(row)
            value["payload"] = json.loads(value.pop("payload_json"))
            return value

    def pending_action(self, user_id: int, action: str) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM pending_actions WHERE user_id=? AND action=?", (user_id, action)).fetchone()
            if not row:
                return None
            value = dict(row)
            value["payload"] = json.loads(value.pop("payload_json"))
            return value

    def clear_pending_action(self, user_id: int, action: str) -> None:
        with self.connect() as con:
            con.execute("DELETE FROM pending_actions WHERE user_id=? AND action=?", (user_id, action))

    def create_public_blob(self, user_id: int, blob_id: str, token: str) -> dict:
        now = _ms()
        with self.connect() as con:
            blob = con.execute("SELECT id FROM blobs WHERE id=? AND user_id=?", (blob_id, user_id)).fetchone()
            if not blob:
                raise KeyError("Arquivo não encontrado.")
            con.execute("INSERT INTO public_blobs(token,user_id,blob_id,created_at_ms,revoked_at_ms) VALUES(?,?,?,?,NULL)", (token, user_id, blob_id, now))
        return {"token": token, "blob_id": blob_id, "created_at_ms": now}

    def public_blob(self, token: str) -> dict | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT p.token,p.user_id,p.blob_id,p.created_at_ms,p.revoked_at_ms,b.name,b.mime,b.size,b.sha256,b.data FROM public_blobs p JOIN blobs b ON b.id=p.blob_id WHERE p.token=? AND p.revoked_at_ms IS NULL",
                (token,),
            ).fetchone()
            return dict(row) if row else None

    def revoke_public_blob(self, user_id: int, token: str) -> bool:
        with self.connect() as con:
            cursor = con.execute("UPDATE public_blobs SET revoked_at_ms=? WHERE token=? AND user_id=? AND revoked_at_ms IS NULL", (_ms(), token, user_id))
            return cursor.rowcount > 0
