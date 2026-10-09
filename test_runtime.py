import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from fastapi.testclient import TestClient
from app import create_app
from store import Conflict, Store


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.sqlite3"
        self.store = Store(self.path)
        self.owner="test-owner"
        self.rid = self.store.create(self.owner)["id"]

    def tearDown(self):
        self.temp.cleanup()

    def action(self, typ="approve", key="decision-key"):
        return dict(type=typ, expected_version=1, idempotency_key=key, correlation_id="correlation-001")

    def test_persistence_and_restart_recovery(self):
        self.store.decide(self.rid, self.action(), self.owner)
        restarted = Store(self.path)
        self.assertEqual(restarted.current(self.owner)["status"], "running")
        self.assertEqual(restarted.tick(), 1)
        self.assertEqual(restarted.tick(), 0)
        self.assertEqual(restarted.current(self.owner)["status"], "completed")
        self.assertEqual(len(restarted.current(self.owner)["events"]), 6)

    def test_duplicate_receipt_and_payload_binding(self):
        result = self.store.decide(self.rid, self.action(), self.owner)
        self.store.tick()
        self.assertEqual(self.store.decide(self.rid, self.action(), self.owner), result)
        with self.assertRaises(Conflict):
            self.store.decide(self.rid, self.action("reject"), self.owner)
        self.assertEqual(len(self.store.get(self.rid,self.owner)["events"]), 6)

    def test_rejection_never_executes(self):
        self.store.decide(self.rid, self.action("reject"), self.owner)
        self.assertEqual(self.store.tick(), 0)
        self.assertEqual(self.store.get(self.rid,self.owner)["status"], "rejected")

    def test_concurrent_conflicting_decisions(self):
        def attempt(typ):
            try:
                self.store.decide(self.rid, self.action(typ, "key-" + typ), self.owner)
                return True
            except Conflict:
                return False
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(attempt, ["approve", "reject"]))
        self.assertEqual(sum(results), 1)
        self.assertEqual(len(self.store.get(self.rid,self.owner)["events"]), 4)

    def test_new_run_preserves_old_history(self):
        new = self.store.create(self.owner)
        self.assertNotEqual(new["id"], self.rid)
        self.assertEqual(len(self.store.get(self.rid,self.owner)["events"]), 3)

    def test_api_validation_and_local_boundary(self):
        with TestClient(create_app(self.path, worker=False)) as c:
            self.assertEqual(c.get("/").status_code, 200)
            app=c.app
            uid=app.state.auth.provision("operator", "test-password-12345")
            login=c.post("/api/auth/login",json={"username":"operator","password":"test-password-12345"}).json()
            c.headers["X-CSRF-Token"]=login["csrf"]
            self.rid=c.get("/api/runs/current").json()["id"]
            self.assertEqual(c.get("/api/runs/current").json()["id"], self.rid)
            url = f"/api/runs/{self.rid}/decision"
            self.assertEqual(c.post(url, json=self.action(), headers={"Origin": "https://evil.invalid"}).status_code, 403)
            stale = self.action(); stale["expected_version"] = 9
            self.assertEqual(c.post(url, json=stale).status_code, 409)
            invalid = self.action(); invalid["type"] = "anything"
            self.assertEqual(c.post(url, json=invalid).status_code, 422)
            self.assertEqual(c.post(url, json=self.action()).status_code, 200)
            self.assertEqual(c.post(url, json=self.action()).status_code, 200)
            self.assertEqual(c.get("/api/runs/missing").status_code, 404)


if __name__ == "__main__":
    unittest.main()
