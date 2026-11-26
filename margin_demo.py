"""HTTP demonstration of margin disconnection, reconnect and restart replay."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from demo import check
from http_json import json_request, query_path
from margin_fixture import routed_stack


HALL = "matinee"
OPENING = {
    "hall": HALL,
    "sources": ["feed-L", "feed-R"],
    "wiring": [
        {"channel": "L", "source": "feed-L"},
        {"channel": "R", "source": "feed-R"},
    ],
    "initial": {"L": 3, "R": 3},
    "margin": {"limit": 10, "local_channel": "L", "remote_channel": "R"},
}
SAMPLES = {"hall": HALL, "samples": {"L": "unit", "R": "unit"}}
REQUEST_PATH = query_path("/request", hall=HALL, request_id="R1")


def call(port, method, path, body=None):
    status, payload = json_request(port, method, path, body)
    if status != 200:
        raise AssertionError(f"{method} {path} -> {status}: {payload}")
    return payload


def expect_status(port, method, path, body, expected_status):
    status, payload = json_request(port, method, path, body)
    check(status, expected_status)
    return payload


def run(directory):
    report_path = None
    first_report = None
    with routed_stack(directory) as (desk_port, room_port, gate):
        opened = call(desk_port, "POST", "/open", OPENING)
        check(opened, {"hall": HALL, "status": "open",
                       "levels": {"L": 3, "R": 3}})
        for channel in ("L", "R"):
            binding = {"hall": HALL, "channel": channel,
                       "sample_id": "unit", "frames": [1]}
            check(call(desk_port, "POST", "/sample", binding),
                  {k: binding[k] for k in ("hall", "channel", "sample_id")})

        grant = call(desk_port, "POST", "/margin/grant",
                     {"hall": HALL, "grant_id": "G1", "steps": 2})
        check(grant, {"hall": HALL, "grant_id": "G1", "steps": 2,
                      "status": "granted"})
        print("发额成功:", json.dumps(grant, ensure_ascii=False))

        gate.offline.set()
        pending = call(desk_port, "POST", "/margin/raise",
                       {"hall": HALL, "request_id": "R1", "steps": 2})
        check(pending, {"hall": HALL, "request_id": "R1", "steps": 2,
                        "status": "pending"})
        print("断链后台端凭已证实额度接单:",
              json.dumps(pending, ensure_ascii=False))

        local5 = call(room_port, "POST", "/margin/local",
                      {"hall": HALL, "operation_id": "L5", "gain": 5})
        check(local5, {
            "hall": HALL, "operation_id": "L5", "channel": "L", "gain": 5,
            "status": "applied", "sequence": 1,
            "before": {"L": 3, "R": 3}, "after": {"L": 5, "R": 3},
        })
        print("断链期间厅端直连调音:",
              json.dumps(local5, ensure_ascii=False))

        rejected = expect_status(room_port, "POST", "/margin/local",
                                 {"hall": HALL, "operation_id": "L6", "gain": 6},
                                 422)
        print("第六格按总额度拒绝:",
              json.dumps({"status": 422, "body": rejected}, ensure_ascii=False))

        gate.offline.clear()
        applied = call(desk_port, "POST", "/margin/raise",
                       {"hall": HALL, "request_id": "R1", "steps": 2})
        check(applied, {
            "hall": HALL, "request_id": "R1", "steps": 2,
            "status": "applied", "sequence": 2,
            "before": {"L": 5, "R": 3}, "after": {"L": 5, "R": 5},
        })
        check(call(desk_port, "POST", "/margin/raise",
                   {"hall": HALL, "request_id": "R1", "steps": 2}), applied)
        print("重连后续送并只兑现一次:",
              json.dumps(applied, ensure_ascii=False))

        monitor = call(desk_port, "POST", "/listen", SAMPLES)
        check(monitor["mix"], [10])
        print("实际增益与混声:",
              json.dumps({"levels": monitor["levels"], "mix": monitor["mix"]},
                         ensure_ascii=False))

        closed = call(desk_port, "POST", "/close", {"hall": HALL})
        check(closed, {"hall": HALL, "status": "closed",
                       "report_id": f"review-{HALL}"})
        report_path = query_path("/report", hall=HALL,
                                 report_id=closed["report_id"])
        first_report = call(desk_port, "GET", report_path)
        check([entry["sequence"] for entry in first_report["operations"]], [1, 2])

    with routed_stack(directory) as (desk_port, room_port, gate):
        reopened_report = call(desk_port, "GET", report_path)
        check(reopened_report, first_report)
        receipt = call(desk_port, "GET", REQUEST_PATH)
        check(receipt["status"], "applied")
        check(receipt["sequence"], 2)
        print("原库重开后按报告号领取复盘:")
        print(json.dumps(reopened_report, ensure_ascii=False, indent=2))
        scene = {
            "case_id": "margin-drill-1",
            "input": {"initial": {"L": 3, "R": 3}, "limit": 10,
                      "grant": 2, "local_gain": 5, "remote_steps": 2},
            "expected": {
                "rejected_gain": 6,
                "operations": ["L5", "R1"],
                "before_R1": {"L": 5, "R": 3},
                "after_R1": {"L": 5, "R": 5},
                "mix": [10],
            },
            "actual": {
                "operations": [
                    entry.get("operation_id", entry.get("request_id"))
                    for entry in reopened_report["operations"]
                ],
                "before_R1": receipt["before"],
                "after_R1": receipt["after"],
                "mix": call(desk_port, "POST", "/listen", SAMPLES)["mix"],
            },
            "downstream_expected": {"report_id": f"review-{HALL}",
                                    "request_replay_sequence": 2},
            "downstream_actual": {"report_id": reopened_report["report_id"],
                                  "request_replay_sequence": receipt["sequence"]},
            "code_paths": [
                "room/margin.py", "desk/margin.py", "session/service.py",
                "desk/service.py", "review/reconcile.py",
            ],
            "oracle": "6 initial grids + 2 granted grids reserve 8; L=5 reaches "
                      "10 with the reservation, L=6 exceeds it. R1 lands after "
                      "L5, so sequences are 1 and 2 and unit samples mix to 10.",
        }
        print("POINTWISE_SCENARIO " + json.dumps(scene, ensure_ascii=False))


def main():
    with TemporaryDirectory(prefix="qingyu-margin-demo-") as temporary:
        run(Path(temporary))


if __name__ == "__main__":
    main()
