import json
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from app import create_app


class AuthChatTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"auth.sqlite3"
        self.app=create_app(self.path,worker=False)
        self.alice_id=self.app.state.auth.provision("alice","alice-password-12345")
        self.bob_id=self.app.state.auth.provision("bob","bob-password-12345")
        self.a=TestClient(self.app);self.b=TestClient(self.app)
        for c,name in [(self.a,"alice"),(self.b,"bob")]:
            res=c.post("/api/auth/login",json={"username":name,"password":name+"-password-12345"})
            self.assertEqual(res.status_code,200,res.text)
            self.assertIn("HttpOnly",res.headers["set-cookie"])
            c.headers["X-CSRF-Token"]=res.json()["csrf"]

    def tearDown(self):
        self.a.close();self.b.close();self.tmp.cleanup()

    def chat(self,c,typ,params):
        return c.post("/chatkit",json={"type":typ,"params":params})

    def new_thread(self):
        res=self.chat(self.a,"threads.create",{"input":{"content":[{"type":"input_text","text":"Status?"}],
                              "attachments":[],"inference_options":{}}})
        self.assertEqual(res.status_code,200,res.text)
        events=[json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]
        widgets=[e["item"] for e in events if e["type"]=="thread.item.done" and e["item"]["type"]=="widget"]
        self.assertTrue(widgets,res.text)
        return widgets[-1]

    def test_unauthenticated_and_csrf(self):
        with TestClient(self.app) as anon:
            self.assertEqual(anon.get("/api/runs/current").status_code,401)
            self.assertEqual(self.chat(anon,"threads.list",{}).status_code,401)
        self.a.headers.pop("X-CSRF-Token")
        self.assertEqual(self.a.post("/api/runs",json={}).status_code,403)
        self.assertEqual(self.chat(self.a,"threads.list",{}).status_code,403)

    def test_foreign_run_read_and_decision(self):
        run=self.a.get("/api/runs/current").json()
        self.assertEqual(self.b.get("/api/runs/"+run["id"]).status_code,404)
        decision=dict(type="approve",expected_version=1,idempotency_key="foreign-key",correlation_id="foreign-correlation")
        self.assertEqual(self.b.post("/api/runs/"+run["id"]+"/decision",json=decision).status_code,404)
        self.assertEqual(self.a.get("/api/runs/"+run["id"]).json()["approval"],"pending")

    def test_logout_revokes_session_and_expiry(self):
        token=self.a.cookies.get("aiko_session")
        self.assertEqual(self.a.post("/api/auth/logout",json={}).status_code,200)
        self.a.cookies.set("aiko_session",token)
        self.assertEqual(self.a.get("/api/auth/me").status_code,401)
        with self.app.state.store.tx() as db:
            db.execute("UPDATE sessions SET expires=0 WHERE owner=?",(self.bob_id,))
        self.assertEqual(self.b.get("/api/auth/me").status_code,401)

    def test_login_rate_limit(self):
        with TestClient(self.app) as c:
            for _ in range(3):
                self.assertEqual(c.post("/api/auth/login",json={"username":"nobody","password":"wrong"}).status_code,401)
            self.assertEqual(c.post("/api/auth/login",json={"username":"alice","password":"alice-password-12345"}).status_code,429)

    def test_actual_chatkit_stream_widget_action_and_thread_isolation(self):
        widget=self.new_thread();tid=widget["thread_id"]
        # Persisted native ChatKit card and button action.
        button=next(b for b in widget["widget"]["children"] if b["type"]=="Button")
        action=button["onClickAction"]
        rid=action["payload"]["run_id"]
        self.assertEqual(self.chat(self.b,"threads.get_by_id",{"thread_id":tid}).status_code,404)
        self.assertEqual(self.chat(self.b,"threads.custom_action",{"thread_id":tid,"item_id":widget["id"],
                            "action":{"type":action["type"],"payload":action["payload"]}}).status_code,404)
        self.assertEqual(self.chat(self.b,"threads.list",{}).json()["data"],[])
        params={"thread_id":tid,"item_id":widget["id"],"action":{"type":action["type"],"payload":action["payload"]}}
        res=self.chat(self.a,"threads.custom_action",params)
        self.assertEqual(res.status_code,200,res.text)
        self.assertIn("Beslutningen er lagret",res.text)
        self.assertEqual(self.a.get("/api/runs/"+rid).json()["approval"],"approved")
        # Same persisted widget action can retry without another domain event.
        self.assertEqual(self.chat(self.a,"threads.custom_action",params).status_code,200)
        self.assertEqual(len(self.a.get("/api/runs/"+rid).json()["events"]),4)
        # SQLite thread history is readable after recreating the application.
        fresh=create_app(self.path,worker=False)
        with TestClient(fresh) as c:
            c.cookies.set("aiko_session",self.a.cookies.get("aiko_session"))
            c.headers["X-CSRF-Token"]=self.a.headers["X-CSRF-Token"]
            self.assertEqual(self.chat(c,"threads.get_by_id",{"thread_id":tid}).status_code,200)

    def test_forged_widget_payload_cannot_change_run(self):
        widget=self.new_thread()
        button=next(b for b in widget["widget"]["children"] if b["type"]=="Button")
        action=button["onClickAction"];rid=action["payload"]["run_id"]
        action["payload"]["expected_version"]=999
        res=self.chat(self.a,"threads.custom_action",{"thread_id":widget["thread_id"],
                       "item_id":widget["id"],"action":{"type":action["type"],"payload":action["payload"]}})
        self.assertEqual(res.status_code,200,res.text)
        self.assertIn("Avvist",res.text)
        self.assertEqual(self.a.get("/api/runs/"+rid).json()["approval"],"pending")


if __name__=="__main__":
    unittest.main()
