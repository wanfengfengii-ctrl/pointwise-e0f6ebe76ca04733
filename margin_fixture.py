import argparse
import socket
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock

from demo import call, check
from desk.service import DeskHandler, serve_desk
from http_json import ApiError, JsonHandler, json_request, query_path
from session.service import serve_room
from tests.support import Interruption, opening, running, transfer


class GateHandler(JsonHandler):
    def do_GET(self):
        self.relay("GET")

    def do_POST(self):
        self.relay("POST")

    def relay(self, method):
        try:
            body = self.read_object() if method == "POST" else None
            if self.server.offline.is_set():
                self.disconnect()
                return
            action = self.server.take(method, self.route)
            if action is not None and action.mode == "drop_before":
                action.entered.set()
                self.disconnect()
                return
            reply = json_request(self.server.room_port, method, self.path, body)
            if action is not None:
                action.entered.set()
                if action.mode == "drop_after":
                    self.disconnect()
                    return
                if not action.release.wait(8):
                    raise ApiError("test_gate_timeout", 504)
            self.send_json(*reply)
        except ApiError as error:
            self.send_json(error.status, error.payload)

    def disconnect(self):
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


class RouteGate(ThreadingHTTPServer):
    def __init__(self, room_port):
        super().__init__(("127.0.0.1", 0), GateHandler)
        self.room_port = room_port
        self.offline = Event()
        self.actions = {}
        self.lock = Lock()

    def arm(self, method, route, mode):
        if mode not in {"drop_before", "drop_after", "hold_after"}:
            raise ValueError(mode)
        key = (method, route)
        with self.lock:
            if key in self.actions:
                raise RuntimeError(f"Interruption already armed for {key}")
            action = Interruption(mode)
            self.actions[key] = action
            return action

    def take(self, method, route):
        with self.lock:
            return self.actions.pop((method, route), None)


@contextmanager
def routed_stack(directory):
    with running(serve_room(directory / "room.sqlite3")) as room:
        with running(RouteGate(room.server_port)) as gate:
            with running(serve_desk(directory / "desk.sqlite3", gate.server_port)) as desk:
                yield desk.server_port, room.server_port, gate


class LaunchHandler(DeskHandler):
    def _get(self):
        if self.route == "/_health":
            return {"status": "ready"}
        return super()._get()


def serve(directory, port):
    with running(serve_room(directory / "room.sqlite3")) as room:
        with serve_desk(directory / "desk.sqlite3", room.server_port, port) as desk:
            desk.RequestHandlerClass = LaunchHandler
            print(desk.server_port, flush=True)
            desk.serve_forever()


def check_gate(directory):
    hall = "fixture"
    submit = {"hall": hall, "request_id": "remote", "change": transfer()}
    onsite = {"hall": hall, "operation_id": "local", "channel": "L", "gain": 6}
    levels_path = query_path("/_room/levels", hall=hall)
    report_id = f"review-{hall}"
    report_path = query_path("/report", hall=hall, report_id=report_id)
    with routed_stack(directory) as (desk, room, gate):
        call(desk, "POST", "/open", opening(hall, 3, 3))
        gate.offline.set()
        check(json_request(desk, "POST", "/submit", submit), (503, {"error": "room_unavailable"}))
        manual = call(room, "POST", "/manual", onsite)
        check(manual["after"], {"L": 6, "R": 3})
        gate.offline.clear()
        for fault, expected in (("drop_before", {"L": 6, "R": 3}),
                                ("drop_after", {"L": 4, "R": 5})):
            gate.arm("POST", "/_room/execute", fault)
            check(call(desk, "POST", "/submit", submit), {**submit, "status": "pending"})
            check(call(room, "GET", levels_path)["levels"], expected)
    with routed_stack(directory) as (desk, room, gate):
        receipt = call(desk, "GET", query_path("/request", hall=hall, request_id="remote"))
        check(receipt, {**submit, "status": "applied", "sequence": 2,
                        "before": {"L": 6, "R": 3}, "after": {"L": 4, "R": 5}})
        action = gate.arm("POST", "/_room/close", "hold_after")
        with ThreadPoolExecutor(max_workers=1) as workers:
            close = workers.submit(call, desk, "POST", "/close", {"hall": hall})
            try:
                if not action.entered.wait(5):
                    raise AssertionError("Room close did not reach the reply gate")
                report = call(room, "GET", report_path)
                check(report["operations"], [{**manual, "origin": "manual"},
                                             {**receipt, "origin": "remote"}])
            finally:
                action.release.set()
            check(close.result(timeout=20), {"hall": hall, "status": "closed", "report_id": report_id})
        check(call(desk, "GET", report_path), report)
        print(report)


def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_subparsers(dest="mode", required=True)
    modes.add_parser("check")
    launch = modes.add_parser("serve")
    launch.add_argument("--host", choices=["127.0.0.1"], required=True)
    launch.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="qingyu-margin-") as workspace:
        directory = Path(workspace)
        if args.mode == "serve":
            serve(directory, args.port)
        else:
            check_gate(directory)


if __name__ == "__main__":
    main()
