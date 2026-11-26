import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from queue import Empty, Queue
from tempfile import TemporaryDirectory
from threading import Thread

from http_json import json_request, query_path


@contextmanager
def service(module, database, *arguments):
    command = [sys.executable, "-B", "-m", module, "--db", str(database), "--port", "0", *arguments]
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as process:
        started = Queue()
        reader = Thread(target=lambda: started.put(process.stdout.readline()), daemon=True)
        reader.start()
        try:
            try:
                line = started.get(timeout=15)
            except Empty as exc:
                raise RuntimeError(f"{module} did not announce an HTTP port") from exc
            if not line.strip().isdigit():
                raise RuntimeError(f"{module} failed to start")
            yield int(line)
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            reader.join()


@contextmanager
def calibration_services(directory):
    with service("session.service", directory / "room.sqlite3") as room_port:
        with service("desk.service", directory / "desk.sqlite3", "--room-port", str(room_port)) as desk_port:
            yield desk_port


def call(port, method, path, body=None):
    status, result = json_request(port, method, path, body)
    if status != 200:
        raise RuntimeError(f"{method} {path} returned {status}: {result}")
    return result


def check(actual, expected):
    if actual != expected:
        raise AssertionError(f"Expected {expected!r}, received {actual!r}")


def main():
    hall = "qingyu"
    initial = {"L": 6, "R": 4}
    change = {"kind": "transfer", "source": "L", "target": "R", "steps": 2}
    selection = {"hall": hall, "samples": {"L": "unit", "R": "unit"}}
    with TemporaryDirectory(prefix="qingyu-") as directory:
        directory = Path(directory)
        with calibration_services(directory) as desk:
            opened = call(desk, "POST", "/open", {
                "hall": hall, "sources": ["feed-L", "feed-R"], "initial": initial,
                "wiring": [{"channel": "L", "source": "feed-L"}, {"channel": "R", "source": "feed-R"}],
            })
            check(opened, {"hall": hall, "status": "open", "levels": initial})
            for channel in ("L", "R"):
                binding = {"hall": hall, "channel": channel, "sample_id": "unit"}
                check(call(desk, "POST", "/sample", {**binding, "frames": [1]}), binding)
            baseline = call(desk, "POST", "/listen", selection)
            check(baseline, {"hall": hall, "levels": initial, "mix": [10]})
            preview = call(desk, "POST", "/preview", {"hall": hall, "change": change})
            check(preview, {"hall": hall, "before": initial, "after": {"L": 4, "R": 6}})
            check(call(desk, "POST", "/listen", selection), baseline)
            parameters = {"hall": hall, "request_id": "z-remote", "change": change}
            receipt = call(desk, "POST", "/submit", parameters)
            check(receipt, {**parameters, "status": "applied", "sequence": 1,
                            "before": initial, "after": {"L": 4, "R": 6}})
            manual = {"hall": hall, "operation_id": "a-manual", "channel": "L", "gain": 3}
            onsite = call(desk, "POST", "/manual", manual)
            check(onsite, {**manual, "status": "applied", "sequence": 2,
                           "before": {"L": 4, "R": 6}, "after": {"L": 3, "R": 6}})
            current = call(desk, "POST", "/listen", selection)
            check(current, {"hall": hall, "levels": {"L": 3, "R": 6}, "mix": [9]})
            request_path = query_path("/request", hall=hall, request_id="z-remote")
            check(call(desk, "GET", request_path), receipt)
            closed = call(desk, "POST", "/close", {"hall": hall})
            check(closed["status"], "closed")
            report_path = query_path("/report", hall=hall, report_id=closed["report_id"])
            report = call(desk, "GET", report_path)
            check(report["operations"], [{**receipt, "origin": "remote"}, {**onsite, "origin": "manual"}])
        with calibration_services(directory) as desk:
            restarted = call(desk, "GET", report_path)
            check(restarted, report)
            check(call(desk, "GET", request_path), receipt)
            check(call(desk, "POST", "/listen", selection), current)
    scene = {
        "case_id": "v8", "input": {"initial": initial, "change": change, "manual": manual},
        "expected": [{"L": 4, "R": 6}, {"L": 3, "R": 6}],
        "actual": [entry["after"] for entry in restarted["operations"]],
        "downstream_expected": {"mix": [9], "order": ["remote", "manual"]},
        "downstream_actual": {"mix": current["mix"], "order": [entry["origin"] for entry in restarted["operations"]]},
        "code_paths": ["room/execute.py", "room/manual.py", "sound/mix.py", "session/closing.py", "review/retrieve.py"],
        "oracle": "6−2=4, 4+2=6, onsite L=3, unit samples give 3+6=9.",
    }
    print(json.dumps({"baseline": baseline, "preview": preview, "current": current, "report": restarted}, indent=2))
    print("POINTWISE_SCENARIO " + json.dumps(scene, ensure_ascii=False))


if __name__ == "__main__":
    main()
