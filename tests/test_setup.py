from tests.support import TuningCase, evidence, opening


class SetupTests(TuningCase):
    def test_reference_mix(self):
        opened = self.open_hall()
        listening = self.listen()
        expected = {"L": 6, "R": 4}
        self.assertEqual(opened["levels"], expected)
        self.assertEqual(listening, {"hall": "main", "levels": expected, "mix": [10]})
        evidence("v1", {"initial": expected, "samples": {"L": [1], "R": [1]}},
                 expected, opened["levels"], [10], listening["mix"],
                 ["session/opening.py", "sound/monitor.py", "sound/mix.py"], "6×1 + 4×1 = 10")

    def test_channel_binding(self):
        self.open_hall()
        self.sample("R", [2])
        self.assertEqual(self.listen(), {"hall": "main", "levels": {"L": 6, "R": 4}, "mix": [14]})
        self.assertEqual(self.post("/sample", 404, hall="main", channel="X", sample_id="unit", frames=[1]),
                         {"error": "unknown_channel", "channel": "X"})
        self.assertEqual(self.post("/sample", 400, hall="main", channel="L", sample_id="unit", frames=[True]),
                         {"error": "invalid_sample"})
        self.assertEqual(self.listen()["mix"], [14])

    def test_vector_mix(self):
        self.open_hall()
        self.sample("L", [1, -2, 3])
        self.sample("R", [2, 1])
        listening = self.listen()
        self.assertEqual(listening["levels"], {"L": 6, "R": 4})
        self.assertEqual(listening["mix"], [14, -8, 18])
        evidence("v1.vector_mix", {"samples": {"L": [1, -2, 3], "R": [2, 1]}},
                 {"L": 6, "R": 4}, listening["levels"], [14, -8, 18], listening["mix"],
                 ["sound/routing.py", "sound/mix.py"], "6+8, -12+4, 18+0")

    def test_missing_sample(self):
        self.post("/open", **opening())
        self.sample("L", [1])
        selection = {"L": "unit", "R": "unit"}
        missing = {"error": "missing_sample", "channel": "R", "sample_id": "unit"}
        self.assertEqual(self.post("/listen", 422, hall="main", samples=selection), missing)
        self.sample("R", [])
        self.assertEqual(self.post("/listen", 422, hall="main", samples=selection), missing)
        self.assertEqual(self.post("/listen", 422, hall="main", samples={"L": "unit"}),
                         {"error": "missing_sample", "channel": "R"})

    def test_restart_preserves_modified_state(self):
        self.open_hall()
        self.sample("L", [2])
        receipt = self.manual("left-check", "L", 3)
        self.stack.restart()
        self.assertEqual(self.listen(), {"hall": "main", "levels": {"L": 3, "R": 4}, "mix": [10]})
        self.assertEqual(self.manual("left-check", "L", 3), receipt)
        self.assertEqual(self.post("/open", 409, **opening()), {"error": "session_conflict"})

    def test_bad_wiring(self):
        body = opening()
        body["wiring"][1]["channel"] = "L"
        error = self.post("/open", 400, **body)
        self.assertEqual(error, {"error": "invalid_wiring", "reason": "duplicate_channel", "channel": "L"})
        self.assert_unknown_hall()

    def test_duplicate_with_complete_channels(self):
        body = opening()
        body["wiring"].insert(1, {"channel": "L", "source": "right-feed"})
        error = self.post("/open", 400, **body)
        self.assertEqual(error["reason"], "duplicate_channel")
        self.assert_unknown_hall()

    def test_unregistered_source(self):
        body = opening()
        body["wiring"][1]["source"] = "spare"
        error = self.post("/open", 400, **body)
        self.assertEqual(error, {"error": "invalid_wiring", "reason": "unregistered_source", "source": "spare"})
        self.assert_unknown_hall()

    def test_invalid_initial(self):
        for value in (11, -1, 4.5, True):
            with self.subTest(value=value):
                self.assertEqual(self.post("/open", 400, **opening(left=value)), {"error": "invalid_gain"})
                self.assert_unknown_hall()
        body = opening()
        del body["initial"]["R"]
        self.assertEqual(self.post("/open", 400, **body), {"error": "invalid_initial"})
        self.assert_unknown_hall()
        self.open_hall()

    def test_open_conflict(self):
        self.open_hall()
        self.manual("preserve", "L", 3)
        self.assertEqual(self.post("/open", 409, **opening(left=9)), {"error": "session_conflict"})
        self.assertEqual(self.listen()["levels"], {"L": 3, "R": 4})
        self.assertEqual(self.listen()["mix"], [7])

    def assert_unknown_hall(self):
        error = self.post("/listen", 404, hall="main", samples={"L": "unit", "R": "unit"})
        self.assertEqual(error, {"error": "unknown_session"})
