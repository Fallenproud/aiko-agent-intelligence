import json
import uuid
from datetime import datetime, timezone
from pydantic import TypeAdapter
from chatkit.store import Store as ChatStore, NotFoundError
from chatkit.server import ChatKitServer, stream_widget
from chatkit.types import Page, ThreadMetadata, ThreadItem
from chatkit.widgets import Card, Text, Button, ActionConfig
from store import Conflict


class SQLiteChatStore(ChatStore[dict]):
    def __init__(self, domain):
        self.domain = domain
        with domain.tx() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS chat_threads(id TEXT PRIMARY KEY,owner TEXT NOT NULL,
              run_id TEXT NOT NULL,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chat_items(seq INTEGER PRIMARY KEY AUTOINCREMENT,
              id TEXT UNIQUE NOT NULL,thread_id TEXT NOT NULL,data TEXT NOT NULL);
            """)

    def owned(self, db, tid, context):
        row = db.execute("SELECT * FROM chat_threads WHERE id=? AND owner=?",
                         (tid,context["owner"])).fetchone()
        if row is None:
            raise NotFoundError("Thread not found")
        return row

    def run_id(self, tid, context):
        with self.domain.tx() as db:
            return self.owned(db,tid,context)["run_id"]

    async def load_thread(self, thread_id, context):
        with self.domain.tx() as db:
            return ThreadMetadata.model_validate_json(self.owned(db,thread_id,context)["data"])

    async def save_thread(self, thread, context):
        with self.domain.tx() as db:
            row = db.execute("SELECT * FROM chat_threads WHERE id=?",(thread.id,)).fetchone()
            if row:
                self.owned(db,thread.id,context)
                db.execute("UPDATE chat_threads SET data=? WHERE id=?",
                           (thread.model_dump_json(),thread.id))
                return
        run = self.domain.current(context["owner"]) or self.domain.create(context["owner"])
        with self.domain.tx() as db:
            db.execute("INSERT INTO chat_threads VALUES(?,?,?,?)",
                       (thread.id,context["owner"],run["id"],thread.model_dump_json()))

    def page(self, rows, after, limit):
        if not 1 <= limit <= 100:
            raise ValueError("Page limit must be 1–100.")
        if after:
            positions = [i for i,r in enumerate(rows) if r["id"]==after]
            if not positions:
                raise NotFoundError("Cursor not found")
            rows = rows[positions[0]+1:]
        more = len(rows)>limit
        return rows[:limit], more

    async def load_threads(self, limit, after, order, context):
        with self.domain.tx() as db:
            rows = list(db.execute("SELECT * FROM chat_threads WHERE owner=? ORDER BY rowid",
                                   (context["owner"],)))
        if order=="desc":
            rows.reverse()
        rows,more = self.page(rows,after,limit)
        data = [ThreadMetadata.model_validate_json(r["data"]) for r in rows]
        return Page(data=data,has_more=more,after=data[-1].id if more and data else None)

    async def load_thread_items(self, thread_id, after, limit, order, context):
        with self.domain.tx() as db:
            self.owned(db,thread_id,context)
            rows = list(db.execute("SELECT * FROM chat_items WHERE thread_id=? ORDER BY seq",
                                   (thread_id,)))
        if order=="desc":
            rows.reverse()
        rows,more = self.page(rows,after,limit)
        data = [TypeAdapter(ThreadItem).validate_json(r["data"]) for r in rows]
        return Page(data=data,has_more=more,after=data[-1].id if more and data else None)

    async def add_thread_item(self, thread_id, item, context):
        await self.save_item(thread_id,item,context)

    async def save_item(self, thread_id, item, context):
        with self.domain.tx() as db:
            self.owned(db,thread_id,context)
            if item.thread_id != thread_id:
                raise NotFoundError("Item thread mismatch")
            existing = db.execute("SELECT thread_id FROM chat_items WHERE id=?",(item.id,)).fetchone()
            if existing and existing["thread_id"]!=thread_id:
                raise NotFoundError("Item not found")
            db.execute("INSERT INTO chat_items(id,thread_id,data) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                       (item.id,thread_id,item.model_dump_json()))

    async def load_item(self, thread_id, item_id, context):
        with self.domain.tx() as db:
            self.owned(db,thread_id,context)
            row = db.execute("SELECT data FROM chat_items WHERE id=? AND thread_id=?",
                             (item_id,thread_id)).fetchone()
            if not row:
                raise NotFoundError("Item not found")
            return TypeAdapter(ThreadItem).validate_json(row["data"])

    async def delete_thread(self, thread_id, context):
        with self.domain.tx() as db:
            self.owned(db,thread_id,context)
            db.execute("DELETE FROM chat_items WHERE thread_id=?",(thread_id,))
            db.execute("DELETE FROM chat_threads WHERE id=?",(thread_id,))

    async def delete_thread_item(self, thread_id, item_id, context):
        with self.domain.tx() as db:
            self.owned(db,thread_id,context)
            db.execute("DELETE FROM chat_items WHERE thread_id=? AND id=?",(thread_id,item_id))

    async def save_attachment(self, attachment, context):
        raise NotImplementedError("Attachments are disabled")

    async def load_attachment(self, attachment_id, context):
        raise NotFoundError("Attachments are disabled")

    async def delete_attachment(self, attachment_id, context):
        raise NotFoundError("Attachments are disabled")


class AikoChatServer(ChatKitServer[dict]):
    def card(self, thread, context, message=None):
        rid = self.store.run_id(thread.id,context)
        run = self.store.domain.get(rid,context["owner"])
        children = [Text(value=message or "Sophie-X · Fast statussvar, ingen LLM"),
                    Text(value=rid+" · "+run["status"]),
                    Text(value="evidence.validate · demo/evidence/* · simulert verktøy")]
        if run["approval"]=="pending":
            for typ,label in [("approve","Godkjenn"),("reject","Avvis")]:
                children.append(Button(label=label,onClickAction=ActionConfig(
                    type="run."+typ,payload={"run_id":rid,"expected_version":run["version"],
                        "idempotency_key":uuid.uuid4().hex,"correlation_id":uuid.uuid4().hex})))
        return Card(children=children)

    async def respond(self, thread, input, context):
        # Deterministic status assistant. Real ChatKit protocol/widgets; no inference.
        async for event in stream_widget(thread,self.card(thread,context),
                generate_id=lambda typ:self.store.generate_item_id(typ,thread,context)):
            yield event

    async def action(self, thread, action, sender, context):
        from models import WidgetDecision
        from pydantic import ValidationError
        message = None
        try:
            if action.type not in ("run.approve","run.reject") or sender is None:
                raise ValueError("Ukjent eller ubundet handling.")
            body = WidgetDecision.model_validate(action.payload)
            rid = self.store.run_id(thread.id,context)
            if body.run_id!=rid:
                raise ValueError("Handlingen gjelder en annen kjøring.")
            # Bind the submitted payload to a persisted widget, not browser claims.
            stored = await self.store.load_item(thread.id,sender.id,context)
            allowed = [b.onClickAction for b in stored.widget.children if isinstance(b,Button)]
            if not any(a and a.type==action.type and a.payload==action.payload for a in allowed):
                raise ValueError("Handlingen samsvarer ikke med godkjenningskortet.")
            payload = body.model_dump(exclude={"run_id"})
            payload["type"] = action.type.split(".")[1]
            self.store.domain.decide(rid,payload,context["owner"])
            message = "Beslutningen er lagret."
        except (Conflict, ValueError, ValidationError) as exc:
            message = "Avvist: "+str(exc)
        async for event in stream_widget(thread,self.card(thread,context,message),
                generate_id=lambda typ:self.store.generate_item_id(typ,thread,context)):
            yield event
