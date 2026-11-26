from tests.support import TuningCase, evidence, opening, transfer


class RoomTests(TuningCase):
    def test_manual_mix(self):
        self.open_hall()
        receipt = self.manual("onsite", "L", 3)
        listening = self.listen()
        self.assertEqual(receipt, {"hall": "main", "operation_id": "onsite", "status": "applied",
                                   "channel": "L", "gain": 3, "sequence": 1,
                                   "before": {"L": 6, "R": 4}, "after": {"L": 3, "R": 4}})
        self.assertEqual(listening, {"hall": "main", "levels": {"L": 3, "R": 4}, "mix": [7]})
        evidence("v7", {"initial": {"L": 6, "R": 4}, "manual": {"L": 3}},
                 {"L": 3, "R": 4}, receipt["after"], [7], listening["mix"],
                 ["room/manual.py", "room/levels.py", "sound/monitor.py"], "3×1 + 4×1 = 7")

    def test_manual_identity(self):
        self.open_hall()
        opening_receipt = self.manual("same-name", "L", 3)
        remote = self.post("/submit", hall="main", request_id="same-name", change=transfer())
        self.assertEqual(remote["sequence"], 2)
        self.assertEqual(self.manual("same-name", "L", 3), opening_receipt)
        self.assertEqual(self.listen()["levels"], {"L": 1, "R": 6})
        self.assertEqual(self.post("/manual", 409, hall="main", operation_id="same-name", channel="L", gain=7),
                         {"error": "parameter_conflict"})
        self.assertEqual(self.post("/manual", 400, hall="main", operation_id="too-high", channel="L", gain=11),
                         {"error": "invalid_gain"})
        self.assertEqual(self.post("/manual", 404, hall="main", operation_id="unknown", channel="X", gain=3),
                         {"error": "unknown_channel", "channel": "X"})
        self.assertEqual(self.manual("next", "L", 2)["sequence"], 3)

    def test_multichannel_listening_after_two_channel_transfer(self):
        body = opening()
        body["sources"].append("center-feed")
        body["wiring"].append({"channel": "C", "source": "center-feed"})
        body["initial"]["C"] = 5
        self.post("/open", **body)
        for channel in ("L", "R", "C"):
            self.sample(channel, [2] if channel == "C" else [1])
        receipt = self.post("/submit", hall="main", request_id="pair", change=transfer())
        self.assertEqual(receipt["after"], {"L": 4, "R": 6})
        self.assertEqual(self.post("/listen", hall="main", samples={"L": "unit", "R": "unit", "C": "unit"}),
                         {"hall": "main", "levels": {"L": 4, "R": 6, "C": 5}, "mix": [20]})
