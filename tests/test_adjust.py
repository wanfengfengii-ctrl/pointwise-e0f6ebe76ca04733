from concurrent.futures import ThreadPoolExecutor

from tests.support import TuningCase, evidence, fixed, transfer


class AdjustTests(TuningCase):
    def test_preview_has_no_effect(self):
        self.open_hall()
        preview = self.post("/preview", hall="main", change=transfer())
        self.assertEqual(preview, {"hall": "main", "before": {"L": 6, "R": 4}, "after": {"L": 4, "R": 6}})
        self.assertEqual(self.listen()["levels"], {"L": 6, "R": 4})
        self.assertEqual(self.get("/request", 404, hall="main", request_id="preview-only"),
                         {"error": "unknown_request"})
        closed = self.post("/close", hall="main")
        self.assertEqual(self.get("/report", hall="main", report_id=closed["report_id"])["operations"], [])

    def test_invalid_preview(self):
        self.open_hall(left=1, right=8)
        self.assertEqual(self.post("/preview", 422, hall="main", change=transfer()), {"error": "range_exceeded"})
        self.assertEqual(self.post("/preview", 400, hall="main", change=transfer(True)), {"error": "invalid_gain"})
        self.assertEqual(self.listen()["levels"], {"L": 1, "R": 8})
        closed = self.post("/close", hall="main")
        self.assertEqual(self.get("/report", hall="main", report_id=closed["report_id"])["operations"], [])

    def test_same_preview_two_intents(self):
        cases = [("fixed", fixed(), {"L": 4, "R": 6}, [10]),
                 ("relative", transfer(), {"L": 1, "R": 10}, [11])]
        observed = {}
        for hall, change, expected, mix in cases:
            with self.subTest(hall=hall):
                self.open_hall(hall)
                preview = self.post("/preview", hall=hall, change=change)
                self.assertEqual(preview["after"], {"L": 4, "R": 6})
                action = self.stack.proxy.arm("hold")
                with ThreadPoolExecutor(max_workers=1) as workers:
                    submitted = workers.submit(self.post, "/submit", hall=hall, request_id="adjust", change=change)
                    try:
                        self.assertTrue(action.entered.wait(8), "Request did not arrive at the HTTP gate")
                        self.manual("onsite-left", "L", 3, hall)
                        self.manual("onsite-right", "R", 8, hall)
                        self.assertEqual(self.listen(hall)["levels"], {"L": 3, "R": 8})
                    finally:
                        action.release.set()
                    receipt = submitted.result(timeout=20)
                listening = self.listen(hall)
                self.assertEqual(listening["levels"], expected, "LIVE_GAIN_MISMATCH")
                self.assertEqual(listening["mix"], mix)
                self.assertEqual(receipt["status"], "applied")
                self.assertEqual(receipt["before"], {"L": 3, "R": 8})
                self.assertEqual(receipt["after"], expected)
                self.assertEqual(receipt["sequence"], 3)
                self.assertEqual(self.get("/request", hall=hall, request_id="adjust"), receipt)
                observed[hall] = listening
        if len(observed) == len(cases):
            evidence("v4", {"preview": {"L": 4, "R": 6}, "live_at_delivery": {"L": 3, "R": 8},
                            "changes": {"fixed": fixed(), "relative": transfer()}},
                     {"fixed": {"L": 4, "R": 6}, "relative": {"L": 1, "R": 10}},
                     {hall: result["levels"] for hall, result in observed.items()},
                     {"fixed": [10], "relative": [11]}, {hall: result["mix"] for hall, result in observed.items()},
                     ["desk/dispatch.py", "room/execute.py", "sound/monitor.py"],
                     "Fixed targets remain 4 and 6. Transfer gives 3−2 and 8+2. Unit frames add the gains.")

    def test_stable_range_rejection(self):
        self.open_hall(left=1, right=8)
        parameters = {"hall": "main", "request_id": "range", "change": transfer()}
        receipt = self.post("/submit", **parameters)
        self.assertEqual(receipt, {**parameters, "status": "rejected", "reason": "range_exceeded"})
        self.assertEqual(self.listen()["levels"], {"L": 1, "R": 8})
        onsite = self.manual("restore-range", "L", 3)
        self.assertEqual(onsite["sequence"], 1)
        self.stack.restart()
        self.assertEqual(self.post("/submit", **parameters), receipt)
        self.assertEqual(self.get("/request", hall="main", request_id="range"), receipt)
        self.assertEqual(self.listen()["levels"], {"L": 3, "R": 8})
        closed = self.post("/close", hall="main")
        operations = self.get("/report", hall="main", report_id=closed["report_id"])["operations"]
        self.assertEqual(operations, [{**onsite, "origin": "manual"}])

    def test_target_range_rejection_survives_reply_loss(self):
        self.open_hall(left=4, right=9)
        parameters = {"hall": "main", "request_id": "overflow", "change": transfer()}
        self.stack.proxy.arm("drop_after")
        self.assertEqual(self.post("/submit", **parameters), {**parameters, "status": "pending"})
        self.assertEqual(self.listen()["levels"], {"L": 4, "R": 9})
        self.manual("restore-right", "R", 8)
        self.stack.restart()
        rejection = {**parameters, "status": "rejected", "reason": "range_exceeded"}
        self.assertEqual(self.get("/request", hall="main", request_id="overflow"), rejection)
        self.assertEqual(self.post("/submit", **parameters), rejection)
        self.assertEqual(self.listen()["levels"], {"L": 4, "R": 8})

    def test_lost_reply_after_commit(self):
        self.open_hall(left=3, right=8)
        parameters = {"hall": "main", "request_id": "once", "change": transfer()}
        before, after = {"L": 3, "R": 8}, {"L": 1, "R": 10}
        self.stack.proxy.arm("drop_after")
        self.assertEqual(self.post("/submit", **parameters), {**parameters, "status": "pending"})
        self.assertEqual(self.listen()["levels"], after)
        self.manual("back-left", "L", 3)
        self.manual("back-right", "R", 8)
        self.stack.restart()
        receipt = self.post("/submit", **parameters)
        expected = {**parameters, "status": "applied", "before": before, "after": after, "sequence": 1}
        self.assertEqual(receipt, expected)
        self.assertEqual(self.get("/request", hall="main", request_id="once"), expected)
        current = self.listen()
        self.assertEqual(current, {"hall": "main", "levels": before, "mix": [11]})
        closed = self.post("/close", hall="main")
        operations = self.get("/report", hall="main", report_id=closed["report_id"])["operations"]
        self.assertEqual([entry for entry in operations if entry["origin"] == "remote"],
                         [{**expected, "origin": "remote"}])
        evidence("v6", {"request": parameters, "reply": "dropped_after_commit", "restored_levels": before},
                 expected, receipt, before, current["levels"], ["desk/dispatch.py", "room/execute.py", "room/history.py"],
                 "The first transfer is 3−2 and 8+2. Only the later onsite operations restore 3 and 8.")

    def test_loss_before_commit(self):
        self.open_hall(left=3, right=8)
        parameters = {"hall": "main", "request_id": "once", "change": transfer()}
        pending = {**parameters, "status": "pending"}
        self.stack.proxy.arm("drop_before")
        self.assertEqual(self.post("/submit", **parameters), pending)
        self.stack.restart()
        self.assertEqual(self.get("/request", hall="main", request_id="once"), pending)
        self.assertEqual(self.listen()["levels"], {"L": 3, "R": 8})
        receipt = self.post("/submit", **parameters)
        self.assertEqual(receipt, {**parameters, "status": "applied", "sequence": 1,
                                   "before": {"L": 3, "R": 8}, "after": {"L": 1, "R": 10}})
        self.assertEqual(self.post("/submit", **parameters), receipt)
        self.assertEqual(self.listen()["levels"], {"L": 1, "R": 10})

    def test_query_recovers_committed_receipt(self):
        self.open_hall()
        parameters = {"hall": "main", "request_id": "query", "change": transfer()}
        self.stack.proxy.arm("drop_after")
        self.assertEqual(self.post("/submit", **parameters)["status"], "pending")
        self.manual("left-in-room", "L", 5)
        self.stack.restart()
        self.assertEqual(self.get("/request", hall="main", request_id="query"),
                         {**parameters, "status": "applied", "sequence": 1,
                          "before": {"L": 6, "R": 4}, "after": {"L": 4, "R": 6}})
        self.assertEqual(self.listen()["levels"], {"L": 5, "R": 6})

    def test_parameter_conflict(self):
        self.open_hall()
        original = {"hall": "main", "request_id": "stable", "change": transfer()}
        conflicting = {**original, "change": fixed()}
        self.stack.proxy.arm("drop_before")
        self.assertEqual(self.post("/submit", **original)["status"], "pending")
        self.assertEqual(self.post("/submit", 409, **conflicting), {"error": "parameter_conflict"})
        self.assertEqual(self.listen()["levels"], {"L": 6, "R": 4})
        receipt = self.post("/submit", **original)
        self.assertEqual(receipt["after"], {"L": 4, "R": 6})
        self.assertEqual(self.post("/submit", 409, **conflicting), {"error": "parameter_conflict"})
        self.assertEqual(self.get("/request", hall="main", request_id="stable"), receipt)
