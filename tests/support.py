import json
import socket
import unittest
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread

from desk.service import serve_desk
from http_json import ApiError, JsonHandler, json_request, query_path
from session.service import serve_room


@dataclass
class Interruption:
    mode: str
    entered: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)


class RoomProxyHandler(JsonHandler):
    def do_GET(self):
        self.respond(self._forward_get)

    def _forward_get(self):
        return json_request(self.server.room_port, "GET", self.path)

    def do_POST(self):
        try:
            body = self.read_object()
            action = None
            if self.route == "/_room/execute":
                action = self.server.take_interruption()
            if action is not None:
                action.entered.set()
                if action.mode == "drop_before":
                    self._disconnect()
                    return
                if action.mode == "hold" and not action.release.wait(10):
                    raise ApiError("test_gate_timeout", 504)
            status, result = json_request(self.server.room_port, "POST", self.path, body)
            if action is not None and action.mode == "drop_after" and status == 200:
                self._disconnect()
                return
            self.send_json(status, result)
        except ApiError as exc:
            self.send_json(exc.status, exc.payload)

    def _disconnect(self):
        self.close_connection = True
        self.connection.shutdown(socket.SHUT_RDWR)


class RoomProxy(ThreadingHTTPServer):
    def __init__(self, room_port):
        super().__init__(("127.0.0.1", 0), RoomProxyHandler)
        self.room_port = room_port
        self.next_interruption = None
        self.lock = Lock()

    def arm(self, mode):
        if mode not in {"hold", "drop_before", "drop_after"}:
            raise ValueError(mode)
        with self.lock:
            if self.next_interruption is not None:
                raise RuntimeError("Interruption already armed")
            self.next_interruption = Interruption(mode)
            return self.next_interruption

    def take_interruption(self):
        with self.lock:
            action = self.next_interruption
            self.next_interruption = None
            return action


@contextmanager
def running(server):
    with server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()


class Stack:
    def __init__(self, directory):
        self.directory = directory

    def __enter__(self):
        self.restart()
        return self

    def __exit__(self, *exc):
        self.servers.close()

    def restart(self):
        if hasattr(self, "servers"):
            self.servers.close()
        with ExitStack() as starting:
            room = starting.enter_context(running(serve_room(self.directory / "room.sqlite3")))
            self.proxy = starting.enter_context(running(RoomProxy(room.server_port)))
            self.desk = starting.enter_context(running(serve_desk(
                self.directory / "desk.sqlite3", self.proxy.server_port,
            )))
            self.servers = starting.pop_all()

    def request(self, method, path, body=None):
        return json_request(self.desk.server_port, method, path, body)


def opening(hall="main", left=6, right=4):
    return {
        "hall": hall, "sources": ["left-feed", "right-feed"],
        "wiring": [{"channel": "L", "source": "left-feed"}, {"channel": "R", "source": "right-feed"}],
        "initial": {"L": left, "R": right},
    }


def transfer(steps=2):
    return {"kind": "transfer", "source": "L", "target": "R", "steps": steps}


def fixed():
    return {"kind": "set", "source": "L", "target": "R", "source_gain": 4, "target_gain": 6}


def evidence(case_id, inputs, expected, actual, downstream_expected, downstream_actual, paths, oracle):
    print("POINTWISE_SCENARIO " + json.dumps({
        "case_id": case_id, "input": inputs, "expected": expected, "actual": actual,
        "downstream_expected": downstream_expected, "downstream_actual": downstream_actual,
        "code_paths": paths, "oracle": oracle,
    }, ensure_ascii=False), flush=True)


class TuningCase(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.stack = self.enterContext(Stack(directory))

    def post(self, path, status=200, **body):
        actual_status, response = self.stack.request("POST", path, body)
        self.assertEqual(actual_status, status, response)
        return response

    def get(self, path, status=200, **parameters):
        actual_status, response = self.stack.request("GET", query_path(path, **parameters))
        self.assertEqual(actual_status, status, response)
        return response

    def open_hall(self, hall="main", left=6, right=4):
        opened = self.post("/open", **opening(hall, left, right))
        self.assertEqual(opened, {"hall": hall, "status": "open", "levels": {"L": left, "R": right}})
        for channel in ("L", "R"):
            self.sample(channel, [1], hall=hall)
        return opened

    def sample(self, channel, frames, sample_id="unit", hall="main"):
        result = self.post("/sample", hall=hall, channel=channel, sample_id=sample_id, frames=frames)
        self.assertEqual(result, {"hall": hall, "channel": channel, "sample_id": sample_id})

    def listen(self, hall="main"):
        return self.post("/listen", hall=hall, samples={"L": "unit", "R": "unit"})

    def manual(self, operation_id, channel, gain, hall="main"):
        return self.post("/manual", hall=hall, operation_id=operation_id, channel=channel, gain=gain)
