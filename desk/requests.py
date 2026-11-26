import json
from dataclasses import dataclass

from http_json import ApiError
from room.adjustment import GainChange


@dataclass(frozen=True)
class DeskRequest:
    hall: str
    request_id: str
    change: GainChange
    terminal: dict | None = None

    def envelope(self):
        return {"hall": self.hall, "request_id": self.request_id, "change": self.change.to_payload()}

    def response(self):
        if self.terminal is not None:
            return self.terminal
        return {**self.envelope(), "status": "pending"}


def parse_adjustment(payload):
    return GainChange.from_payload(payload)


def get_request(connection, hall, request_id):
    row = connection.execute(
        "SELECT parameters, terminal FROM requests WHERE hall = ? AND request_id = ?",
        (hall, request_id),
    ).fetchone()
    if row is None:
        return None
    change = parse_adjustment(json.loads(row["parameters"]))
    terminal = None if row["terminal"] is None else json.loads(row["terminal"])
    return DeskRequest(hall, request_id, change, terminal)


def register_request(connection, request):
    previous = get_request(connection, request.hall, request.request_id)
    if previous is not None:
        if previous.change != request.change:
            raise ApiError("parameter_conflict", 409)
        return previous
    connection.execute(
        "INSERT INTO requests (hall, request_id, parameters) VALUES (?, ?, ?)",
        (request.hall, request.request_id, json.dumps(request.change.to_payload())),
    )
    return request


def _matches_receipt(request, result):
    if any(result.get(key) != value for key, value in request.envelope().items()):
        return False
    if result.get("status") == "rejected":
        return result.get("reason") == "range_exceeded"
    sequence = result.get("sequence")
    if result.get("status") != "applied" or type(sequence) is not int or sequence < 1:
        return False
    channels = {request.change.source, request.change.target}
    for field in ("before", "after"):
        pair = result.get(field)
        if not isinstance(pair, dict) or set(pair) != channels:
            return False
    return True


def record_terminal(connection, request, result):
    stored = get_request(connection, request.hall, request.request_id)
    if stored.terminal is not None or not _matches_receipt(stored, result):
        return stored.response()
    connection.execute(
        "UPDATE requests SET terminal = ? WHERE hall = ? AND request_id = ?",
        (json.dumps(result), request.hall, request.request_id),
    )
    return result


def has_pending_requests(connection, hall):
    row = connection.execute(
        "SELECT 1 FROM requests WHERE hall = ? AND terminal IS NULL LIMIT 1", (hall,)
    ).fetchone()
    return row is not None


def list_terminal_requests(connection, hall):
    rows = connection.execute(
        "SELECT terminal FROM requests WHERE hall = ? AND terminal IS NOT NULL ORDER BY request_id",
        (hall,),
    )
    return [json.loads(row["terminal"]) for row in rows]
