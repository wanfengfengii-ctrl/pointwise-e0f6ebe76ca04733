import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from http_json import json_request, query_path
from margin_fixture import check_gate, routed_stack


def http(port, method, path, body=None):
    return json_request(port, method, path, body)


def call(testcase, port, method, path, body=None, status=200):
    actual, payload = http(port, method, path, body)
    testcase.assertEqual(actual, status, payload)
    return payload


def margin_open(hall="matinee", **initial):
    levels = {"L": 3, "R": 3}
    levels.update(initial)
    return {
        "hall": hall,
        "sources": ["feed-L", "feed-R"],
        "wiring": [
            {"channel": "L", "source": "feed-L"},
            {"channel": "R", "source": "feed-R"},
        ],
        "initial": levels,
        "margin": {"limit": 10, "local_channel": "L", "remote_channel": "R"},
    }


def unit_samples(testcase, desk, hall):
    for channel in ("L", "R"):
        call(testcase, desk, "POST", "/sample", {
            "hall": hall, "channel": channel,
            "sample_id": "unit", "frames": [1],
        })


class MarginDrillOneTests(unittest.TestCase):
    def test_disconnected_local_reconnect_and_restart_report(self):
        hall = "matinee"
        report_path = query_path("/report", hall=hall, report_id=f"review-{hall}")
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with routed_stack(directory) as (desk, room, gate):
                opened = call(self, desk, "POST", "/open", margin_open())
                self.assertEqual(opened, {
                    "hall": hall, "status": "open",
                    "levels": {"L": 3, "R": 3},
                })
                unit_samples(self, desk, hall)
                grant = call(self, desk, "POST", "/margin/grant", {
                    "hall": hall, "grant_id": "G1", "steps": 2,
                })
                self.assertEqual(grant, {
                    "hall": hall, "grant_id": "G1", "steps": 2,
                    "status": "granted",
                })

                gate.offline.set()
                pending = call(self, desk, "POST", "/margin/raise", {
                    "hall": hall, "request_id": "R1", "steps": 2,
                })
                self.assertEqual(pending, {
                    "hall": hall, "request_id": "R1", "steps": 2,
                    "status": "pending",
                })

                local5 = call(self, room, "POST", "/margin/local", {
                    "hall": hall, "operation_id": "L5", "gain": 5,
                })
                self.assertEqual(local5, {
                    "hall": hall, "operation_id": "L5", "channel": "L",
                    "gain": 5, "status": "applied", "sequence": 1,
                    "before": {"L": 3, "R": 3},
                    "after": {"L": 5, "R": 3},
                })
                call(self, room, "POST", "/margin/local", {
                    "hall": hall, "operation_id": "L6", "gain": 6,
                }, status=422)
                gate.offline.clear()

                applied = call(self, desk, "POST", "/margin/raise", {
                    "hall": hall, "request_id": "R1", "steps": 2,
                })
                self.assertEqual(applied, {
                    "hall": hall, "request_id": "R1", "steps": 2,
                    "status": "applied", "sequence": 2,
                    "before": {"L": 5, "R": 3},
                    "after": {"L": 5, "R": 5},
                })
                self.assertEqual(call(self, desk, "POST", "/margin/raise", {
                    "hall": hall, "request_id": "R1", "steps": 2,
                }), applied)
                monitor = call(self, desk, "POST", "/listen", {
                    "hall": hall,
                    "samples": {"L": "unit", "R": "unit"},
                })
                self.assertEqual(monitor["mix"], [10])

                closed = call(self, desk, "POST", "/close", {"hall": hall})
                self.assertEqual(closed["report_id"], f"review-{hall}")
                report = call(self, desk, "GET", report_path)
                self.assertEqual(
                    [entry.get("operation_id", entry.get("request_id"))
                     for entry in report["operations"]],
                    ["L5", "R1"],
                )

            with routed_stack(directory) as (desk, room, gate):
                restarted_report = call(self, desk, "GET", report_path)
                self.assertEqual(restarted_report, report)
                receipt = call(self, desk, "GET", query_path(
                    "/request", hall=hall, request_id="R1"))
                self.assertEqual(receipt, applied)


class MarginEvidenceAndOrderTests(unittest.TestCase):
    def test_held_reply_independent_grant_reverse_delivery_and_reused_number(self):
        hall = "second"
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with routed_stack(directory) as (desk, room, gate):
                call(self, desk, "POST", "/open", margin_open(hall))
                action = gate.arm("POST", "/_room/margin/grant", "hold_after")
                with ThreadPoolExecutor(max_workers=1) as pool:
                    g1 = pool.submit(call, self, desk, "POST", "/margin/grant",
                                     {"hall": hall, "grant_id": "G1", "steps": 2})
                    self.assertTrue(action.entered.wait(5))
                    g2 = call(self, desk, "POST", "/margin/grant",
                              {"hall": hall, "grant_id": "G2", "steps": 1})
                    self.assertEqual(g2["status"], "granted")

                    gate.offline.set()
                    first = call(self, desk, "POST", "/margin/raise",
                                 {"hall": hall, "request_id": "RA", "steps": 1})
                    self.assertEqual(first["status"], "pending")
                    action.release.set()
                    self.assertEqual(g1.result(timeout=10)["status"], "granted")

                gate.offline.clear()
                for grant_id, steps in (("G1", 2), ("G2", 1)):
                    self.assertEqual(call(self, desk, "POST", "/margin/grant", {
                        "hall": hall, "grant_id": grant_id, "steps": steps,
                    })["status"], "granted")

                rb = call(self, desk, "POST", "/margin/raise",
                           {"hall": hall, "request_id": "RB", "steps": 2})
                self.assertEqual(rb["status"], "applied")
                call(self, desk, "POST", "/margin/raise",
                     {"hall": hall, "request_id": "FOURTH", "steps": 1}, status=422)

                gate.arm("POST", "/_room/margin/raise", "drop_before")
                self.assertEqual(call(self, desk, "POST", "/margin/raise", {
                    "hall": hall, "request_id": "RA", "steps": 1,
                })["status"], "pending")
                rb_replay = call(self, desk, "POST", "/margin/raise",
                                 {"hall": hall, "request_id": "RB", "steps": 2})
                self.assertEqual(rb_replay["sequence"], 1)
                ra = call(self, desk, "POST", "/margin/raise",
                          {"hall": hall, "request_id": "RA", "steps": 1})
                self.assertEqual(ra["sequence"], 2)
                self.assertEqual(ra["before"], {"L": 3, "R": 5})
                self.assertEqual(ra["after"], {"L": 3, "R": 6})

                local4 = call(self, room, "POST", "/margin/local",
                              {"hall": hall, "operation_id": "L4", "gain": 4})
                self.assertEqual(local4["after"], {"L": 4, "R": 6})
                call(self, room, "POST", "/margin/local",
                     {"hall": hall, "operation_id": "L5", "gain": 5}, status=422)
                local3 = call(self, room, "POST", "/margin/local",
                              {"hall": hall, "operation_id": "L3", "gain": 3})
                self.assertEqual(local3["after"], {"L": 3, "R": 6})

                call(self, desk, "POST", "/margin/grant",
                     {"hall": hall, "grant_id": "G3", "steps": 1})
                reused = call(self, desk, "POST", "/margin/raise",
                              {"hall": hall, "request_id": "FOURTH", "steps": 1})
                self.assertEqual(reused["status"], "applied")
                call(self, desk, "POST", "/margin/raise",
                     {"hall": hall, "request_id": "FOURTH", "steps": 2}, status=409)


class MarginFaultAndCloseTests(unittest.TestCase):
    def test_query_before_landing_is_pending_and_does_not_apply(self):
        hall = "before"
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with routed_stack(directory) as (desk, room, gate):
                call(self, desk, "POST", "/open", margin_open(hall))
                unit_samples(self, desk, hall)
                call(self, desk, "POST", "/margin/grant",
                     {"hall": hall, "grant_id": "G", "steps": 1})
                gate.arm("POST", "/_room/margin/raise", "drop_before")
                pending = call(self, desk, "POST", "/margin/raise",
                               {"hall": hall, "request_id": "R", "steps": 1})
                self.assertEqual(pending["status"], "pending")

            with routed_stack(directory) as (desk, room, gate):
                queried = call(self, desk, "GET", query_path(
                    "/request", hall=hall, request_id="R"))
                self.assertEqual(queried["status"], "pending")
                monitor = call(self, desk, "POST", "/listen", {
                    "hall": hall, "samples": {"L": "unit", "R": "unit"},
                })
                self.assertEqual(monitor["levels"], {"L": 3, "R": 3})
                self.assertEqual(monitor["mix"], [6])
                applied = call(self, desk, "POST", "/margin/raise",
                               {"hall": hall, "request_id": "R", "steps": 1})
                self.assertEqual(applied["sequence"], 1)

    def test_query_after_commit_recovers_same_first_execution(self):
        hall = "after"
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with routed_stack(directory) as (desk, room, gate):
                call(self, desk, "POST", "/open", margin_open(hall))
                call(self, desk, "POST", "/margin/grant",
                     {"hall": hall, "grant_id": "G", "steps": 2})
                gate.arm("POST", "/_room/margin/raise", "drop_after")
                pending = call(self, desk, "POST", "/margin/raise",
                               {"hall": hall, "request_id": "R", "steps": 2})
                self.assertEqual(pending["status"], "pending")
                levels = call(self, room, "GET", query_path(
                    "/_room/levels", hall=hall))["levels"]
                self.assertEqual(levels, {"L": 3, "R": 5})

            with routed_stack(directory) as (desk, room, gate):
                receipt = call(self, desk, "GET", query_path(
                    "/request", hall=hall, request_id="R"))
                self.assertEqual(receipt, {
                    "hall": hall, "request_id": "R", "steps": 2,
                    "status": "applied", "sequence": 1,
                    "before": {"L": 3, "R": 3},
                    "after": {"L": 3, "R": 5},
                })

    def test_lost_close_request_can_resume_after_restart(self):
        hall = "lost-close"
        report_path = query_path("/report", hall=hall, report_id=f"review-{hall}")
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with routed_stack(directory) as (desk, room, gate):
                call(self, desk, "POST", "/open", margin_open(hall))
                gate.arm("POST", "/_room/close", "drop_before")
                call(self, desk, "POST", "/close", {"hall": hall}, status=503)

            with routed_stack(directory) as (desk, room, gate):
                closed = call(self, desk, "POST", "/close", {"hall": hall})
                self.assertEqual(closed["status"], "closed")
                report = call(self, desk, "GET", report_path)
                self.assertEqual(report["operations"], [])

    def test_pending_blocks_close_and_late_evidence_cannot_reopen_admissions(self):
        hall = "close-fault"
        report_path = query_path("/report", hall=hall, report_id=f"review-{hall}")
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with routed_stack(directory) as (desk, room, gate):
                call(self, desk, "POST", "/open", margin_open(hall))
                call(self, desk, "POST", "/margin/grant",
                     {"hall": hall, "grant_id": "G1", "steps": 1})
                gate.offline.set()
                self.assertEqual(call(self, desk, "POST", "/margin/raise", {
                    "hall": hall, "request_id": "R1", "steps": 1,
                })["status"], "pending")
                call(self, desk, "POST", "/close", {"hall": hall}, status=409)
                gate.offline.clear()
                self.assertEqual(call(self, desk, "POST", "/margin/raise", {
                    "hall": hall, "request_id": "R1", "steps": 1,
                })["status"], "applied")

                grant_gate = gate.arm("POST", "/_room/margin/grant", "hold_after")
                with ThreadPoolExecutor(max_workers=1) as pool:
                    late_grant = pool.submit(
                        call, self, desk, "POST", "/margin/grant",
                        {"hall": hall, "grant_id": "G2", "steps": 1})
                    self.assertTrue(grant_gate.entered.wait(5))
                    close_gate = gate.arm("POST", "/_room/close", "drop_after")
                    close_status, close_payload = http(
                        desk, "POST", "/close", {"hall": hall})
                    self.assertTrue(close_gate.entered.wait(5))
                    self.assertEqual(close_status, 503)
                    self.assertEqual(close_payload["error"], "room_unavailable")
                    grant_gate.release.set()
                    self.assertEqual(late_grant.result(timeout=10)["status"], "granted")

                call(self, desk, "POST", "/margin/raise",
                     {"hall": hall, "request_id": "R2", "steps": 1}, status=409)

            with routed_stack(directory) as (desk, room, gate):
                call(self, desk, "POST", "/margin/grant",
                     {"hall": hall, "grant_id": "G2", "steps": 1})
                call(self, desk, "POST", "/margin/raise",
                     {"hall": hall, "request_id": "R3", "steps": 1}, status=409)
                closed = call(self, desk, "POST", "/close", {"hall": hall})
                self.assertEqual(closed, {
                    "hall": hall, "status": "closed",
                    "report_id": f"review-{hall}",
                })
                report = call(self, desk, "GET", report_path)
                self.assertEqual([row["request_id"] for row in report["operations"]], ["R1"])
                call(self, desk, "POST", "/margin/raise",
                     {"hall": hall, "request_id": "R4", "steps": 1}, status=409)
                self.assertEqual(call(self, desk, "GET", report_path), report)


class MarginSessionTypeTests(unittest.TestCase):
    def test_cross_kind_entries_conflict(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with routed_stack(directory) as (desk, room, gate):
                call(self, desk, "POST", "/open", {
                    "hall": "ordinary",
                    "sources": ["a", "b"],
                    "wiring": [{"channel": "L", "source": "a"},
                               {"channel": "R", "source": "b"}],
                    "initial": {"L": 3, "R": 3},
                })
                call(self, desk, "POST", "/margin/grant", {
                    "hall": "ordinary", "grant_id": "G", "steps": 1,
                }, status=409)
                call(self, desk, "POST", "/margin/raise", {
                    "hall": "ordinary", "request_id": "R", "steps": 1,
                }, status=409)
                call(self, room, "POST", "/margin/local", {
                    "hall": "ordinary", "operation_id": "L", "gain": 4,
                }, status=409)
                # Grants themselves do not block ordinary close.
                call(self, desk, "POST", "/close", {"hall": "ordinary"})

                call(self, desk, "POST", "/open", margin_open("quota"))
                old_change = {
                    "kind": "transfer", "source": "L", "target": "R", "steps": 1,
                }
                call(self, desk, "POST", "/submit", {
                    "hall": "quota", "request_id": "old", "change": old_change,
                }, status=409)
                call(self, desk, "POST", "/manual", {
                    "hall": "quota", "operation_id": "old-local",
                    "channel": "L", "gain": 4,
                }, status=409)
                call(self, room, "POST", "/_room/execute", {
                    "hall": "quota", "request_id": "old-room",
                    "change": old_change,
                }, status=409)
                # The rejected old submission created no pending desk request.
                call(self, desk, "POST", "/close", {"hall": "quota"})


class MarginFixtureCheckTests(unittest.TestCase):
    def test_provided_ordinary_fixture_check(self):
        with TemporaryDirectory() as temporary:
            check_gate(Path(temporary))


if __name__ == "__main__":
    unittest.main()
