from concurrent.futures import ThreadPoolExecutor

from tests.support import TuningCase, evidence, transfer


class ReviewTests(TuningCase):
    def test_closed_replay(self):
        self.open_hall()
        remote = self.post("/submit", hall="main", request_id="z-remote", change=transfer())
        onsite = self.manual("a-manual", "L", 3)
        close = self.post("/close", hall="main")
        self.assertEqual(close, {"hall": "main", "status": "closed", "report_id": "review-main"})
        expected = {"hall": "main", "report_id": "review-main", "operations": [
            {**remote, "origin": "remote"}, {**onsite, "origin": "manual"},
        ]}
        self.assertEqual(self.get("/report", hall="main", report_id="review-main"), expected)
        self.stack.restart()
        restarted = self.get("/report", hall="main", report_id="review-main")
        self.assertEqual(restarted, expected)
        self.assertEqual(self.post("/close", hall="main"), close)
        self.assertEqual(self.listen()["mix"], [9])
        self.assertEqual(self.get("/request", hall="main", request_id="z-remote"), remote)
        self.assertEqual(self.manual("a-manual", "L", 3), onsite)
        self.assertEqual(self.post("/manual", 409, hall="main", operation_id="new", channel="L", gain=1),
                         {"error": "closed_session"})
        self.assertEqual(self.post("/submit", 409, hall="main", request_id="new", change=transfer()),
                         {"error": "closed_session"})
        self.assertEqual(self.get("/report", 404, hall="other", report_id="review-main"), {"error": "unknown_report"})
        self.assertEqual(self.get("/report", 404, hall="main", report_id="other"), {"error": "unknown_report"})
        actual_after = [entry["after"] for entry in restarted["operations"]]
        self.assertEqual(actual_after, [{"L": 4, "R": 6}, {"L": 3, "R": 6}])
        evidence("v8", {"transfer": 2, "manual": {"L": 3}},
                 [{"L": 4, "R": 6}, {"L": 3, "R": 6}], actual_after,
                 ["remote", "manual"], [entry["origin"] for entry in restarted["operations"]],
                 ["session/closing.py", "review/reconcile.py", "review/report.py", "review/retrieve.py"],
                 "The transfer turns 6 and 4 into 4 and 6. The subsequent onsite change only sets L to 3.")

    def test_pending_close(self):
        self.open_hall()
        action = self.stack.proxy.arm("hold")
        with ThreadPoolExecutor(max_workers=1) as workers:
            submitted = workers.submit(self.post, "/submit", hall="main", request_id="remote", change=transfer())
            try:
                self.assertTrue(action.entered.wait(8), "Request did not arrive at the HTTP gate")
                self.assertEqual(self.manual("onsite", "L", 5)["sequence"], 1)
                self.assertEqual(self.get("/request", hall="main", request_id="remote")["status"], "pending")
                self.assertEqual(self.post("/close", 409, hall="main"), {"error": "pending_requests"})
                self.assertEqual(self.get("/report", 404, hall="main", report_id="review-main"), {"error": "unknown_report"})
                self.assertEqual(self.listen()["levels"], {"L": 5, "R": 4})
            finally:
                action.release.set()
            receipt = submitted.result(timeout=20)
        self.assertEqual(receipt["sequence"], 2)
        self.assertEqual(receipt["before"], {"L": 5, "R": 4})
        self.assertEqual(receipt["after"], {"L": 3, "R": 6})
        closed = self.post("/close", hall="main")
        report = self.get("/report", hall="main", report_id=closed["report_id"])
        self.assertEqual([row["origin"] for row in report["operations"]], ["manual", "remote"])
        self.assertEqual([row["sequence"] for row in report["operations"]], [1, 2])

    def test_commit_order(self):
        self.open_hall()
        self.post("/submit", hall="main", request_id="z-remote", change=transfer())
        self.manual("a-manual", "L", 3)
        number = self.post("/close", hall="main")["report_id"]
        self.stack.restart()
        first, second = self.get("/report", hall="main", report_id=number)["operations"]
        self.assertEqual((first["request_id"], second["operation_id"]), ("z-remote", "a-manual"))
        self.assertEqual((first["sequence"], second["sequence"]), (1, 2))
        self.assertEqual((first["before"], first["after"]), ({"L": 6, "R": 4}, {"L": 4, "R": 6}))
        self.assertEqual((second["before"], second["after"]), ({"L": 4, "R": 6}, {"L": 3, "R": 6}))
