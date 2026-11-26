"""Desk-side margin grants, commitments, evidence and close fencing."""
import json

from desk.room_link import LinkUnavailable
from http_json import ApiError, identifier
from room.margin import validate_steps


INTERNAL_GRANT_ROUTE = "/_room/margin/grant"
# Reuse the established execution path as one supported wire route. The body's
# margin marker selects the quota-aware executor; aliases are exposed by room.
INTERNAL_RAISE_ROUTES = ("/_room/execute", "/_room/margin/raise", "/_room/margin/execute")
INTERNAL_RAISE_ROUTE = INTERNAL_RAISE_ROUTES[0]


def initialize_desk_margin_tables(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS desk_halls (
            hall TEXT PRIMARY KEY,
            mode TEXT NOT NULL DEFAULT 'unknown'
                CHECK (mode IN ('unknown', 'ordinary', 'margin')),
            close_started INTEGER NOT NULL DEFAULT 0
                CHECK (close_started IN (0, 1)),
            close_result TEXT
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS margin_grants (
            hall TEXT NOT NULL,
            grant_id TEXT NOT NULL,
            steps INTEGER NOT NULL CHECK (steps > 0),
            status TEXT NOT NULL CHECK (status IN ('pending', 'granted')),
            receipt TEXT,
            PRIMARY KEY (hall, grant_id)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS margin_requests (
            hall TEXT NOT NULL,
            request_id TEXT NOT NULL,
            steps INTEGER NOT NULL CHECK (steps > 0),
            terminal TEXT,
            PRIMARY KEY (hall, request_id)
        )
    ''')


def note_opened_hall(connection, hall, margin_requested):
    mode = "margin" if margin_requested else "ordinary"
    connection.execute('''
        INSERT INTO desk_halls (hall, mode, close_started, close_result)
        VALUES (?, ?, 0, NULL)
        ON CONFLICT (hall) DO UPDATE SET
            mode = excluded.mode,
            close_started = 0,
            close_result = NULL
    ''', (hall, mode))


def note_room_mode(connection, hall, mode):
    connection.execute('''
        INSERT INTO desk_halls (hall, mode)
        VALUES (?, ?)
        ON CONFLICT (hall) DO UPDATE SET mode = excluded.mode
    ''', (hall, mode))


def get_hall(connection, hall):
    row = connection.execute(
        "SELECT hall, mode, close_started, close_result FROM desk_halls WHERE hall = ?",
        (hall,),
    ).fetchone()
    return None if row is None else dict(row)


def start_close(connection, hall):
    connection.execute('''
        INSERT INTO desk_halls (hall, close_started)
        VALUES (?, 1)
        ON CONFLICT (hall) DO UPDATE SET close_started = 1
    ''', (hall,))


def finish_close(connection, hall, result):
    connection.execute('''
        INSERT INTO desk_halls (hall, close_started, close_result)
        VALUES (?, 1, ?)
        ON CONFLICT (hall) DO UPDATE SET close_started = 1, close_result = ?
    ''', (hall, json.dumps(result), json.dumps(result)))


def get_grant(connection, hall, grant_id):
    return connection.execute('''
        SELECT hall, grant_id, steps, status, receipt
        FROM margin_grants WHERE hall = ? AND grant_id = ?
    ''', (hall, grant_id)).fetchone()


def _grant_receipt(row):
    if row["receipt"]:
        return json.loads(row["receipt"])
    return {
        "hall": row["hall"],
        "grant_id": row["grant_id"],
        "steps": row["steps"],
        "status": "granted" if row["status"] == "granted" else "pending",
    }


def pending_grant(hall, grant_id, steps):
    return {"hall": hall, "grant_id": grant_id, "steps": steps, "status": "pending"}


def _public_grant(result):
    return {
        "hall": result["hall"],
        "grant_id": result["grant_id"],
        "steps": result["steps"],
        "status": "granted",
    }


def record_grant_evidence(connection, hall, result):
    note_room_mode(connection, hall, "margin")
    evidence = result.get("evidence")
    items = []
    if isinstance(evidence, dict) and evidence.get("hall") == hall:
        raw_items = evidence.get("grants")
        if isinstance(raw_items, list):
            for item in raw_items:
                if (isinstance(item, dict) and isinstance(item.get("grant_id"), str)
                        and type(item.get("steps")) is int and item["steps"] > 0):
                    items.append((item["grant_id"], item["steps"]))
    current = (result.get("grant_id"), result.get("steps"))
    if (isinstance(current[0], str) and type(current[1]) is int and current[1] > 0
            and current not in items):
        items.append(current)

    for grant_id, steps in items:
        row = get_grant(connection, hall, grant_id)
        receipt = json.dumps({
            "hall": hall, "grant_id": grant_id, "steps": steps, "status": "granted",
        })
        if row is None:
            connection.execute('''
                INSERT INTO margin_grants (hall, grant_id, steps, status, receipt)
                VALUES (?, ?, ?, 'granted', ?)
            ''', (hall, grant_id, steps, receipt))
        elif row["steps"] != steps:
            raise ApiError("parameter_conflict", 409)
        else:
            connection.execute('''
                UPDATE margin_grants SET status = 'granted', receipt = ?
                WHERE hall = ? AND grant_id = ?
            ''', (receipt, hall, grant_id))


def submit_grant(database, room, body):
    hall = identifier(body.get("hall"))
    grant_id = identifier(body.get("grant_id"))
    steps = validate_steps(body.get("steps"))

    with database.write_transaction() as connection:
        row = get_grant(connection, hall, grant_id)
        if row is not None and row["steps"] != steps:
            raise ApiError("parameter_conflict", 409)
        if row is None:
            connection.execute('''
                INSERT INTO margin_grants (hall, grant_id, steps, status)
                VALUES (?, ?, ?, 'pending')
            ''', (hall, grant_id, steps))
            row = get_grant(connection, hall, grant_id)
        already_granted = row["status"] == "granted"

    if already_granted:
        with database.read_snapshot() as connection:
            return _public_grant(_grant_receipt(get_grant(connection, hall, grant_id)))

    try:
        result = room.call("POST", INTERNAL_GRANT_ROUTE, {
            "hall": hall, "grant_id": grant_id, "steps": steps,
        })
    except LinkUnavailable:
        return pending_grant(hall, grant_id, steps)
    except ApiError as exc:
        if exc.code == "not_margin_session":
            with database.write_transaction() as connection:
                note_room_mode(connection, hall, "ordinary")
        raise

    with database.write_transaction() as connection:
        record_grant_evidence(connection, hall, result)
        row = get_grant(connection, hall, grant_id)
        return _public_grant(_grant_receipt(row))


def get_margin_request(connection, hall, request_id):
    return connection.execute('''
        SELECT hall, request_id, steps, terminal
        FROM margin_requests WHERE hall = ? AND request_id = ?
    ''', (hall, request_id)).fetchone()


def pending_raise(hall, request_id, steps):
    return {"hall": hall, "request_id": request_id, "steps": steps, "status": "pending"}


def confirmed_grant_steps(connection, hall):
    return connection.execute('''
        SELECT COALESCE(SUM(steps), 0) FROM margin_grants
        WHERE hall = ? AND status = 'granted'
    ''', (hall,)).fetchone()[0]


def committed_raise_steps(connection, hall):
    return connection.execute(
        "SELECT COALESCE(SUM(steps), 0) FROM margin_requests WHERE hall = ?",
        (hall,),
    ).fetchone()[0]


def available_commitment(connection, hall):
    return confirmed_grant_steps(connection, hall) - committed_raise_steps(connection, hall)


def has_pending_margin_requests(connection, hall):
    row = connection.execute('''
        SELECT 1 FROM margin_requests WHERE hall = ? AND terminal IS NULL LIMIT 1
    ''', (hall,)).fetchone()
    return row is not None


def list_terminal_margin_requests(connection, hall):
    rows = connection.execute('''
        SELECT terminal FROM margin_requests
        WHERE hall = ? AND terminal IS NOT NULL
    ''', (hall,)).fetchall()
    return [json.loads(row["terminal"]) for row in rows]


def submit_raise(database, room, body):
    hall = identifier(body.get("hall"))
    request_id = identifier(body.get("request_id"))
    steps = validate_steps(body.get("steps"))

    with database.read_snapshot() as connection:
        hall_row = get_hall(connection, hall)
        existing = get_margin_request(connection, hall, request_id)

    if hall_row is None and existing is None:
        # A proven grant always records desk_halls. This preflight gives the
        # conventional 404/409 for halls opened directly at the room service.
        try:
            snapshot = room.read_levels(hall)
        except LinkUnavailable:
            snapshot = None
        if snapshot is not None:
            if snapshot.get("status") != "open":
                raise ApiError("closed_session", 409)
            if snapshot.get("margin") is None:
                with database.write_transaction() as connection:
                    note_room_mode(connection, hall, "ordinary")
                raise ApiError("not_margin_session", 409)
            with database.write_transaction() as connection:
                note_room_mode(connection, hall, "margin")

    with database.write_transaction() as connection:
        row = get_margin_request(connection, hall, request_id)
        if row is not None:
            if row["steps"] != steps:
                raise ApiError("parameter_conflict", 409)
            if row["terminal"] is not None:
                return json.loads(row["terminal"])
        else:
            hall_row = get_hall(connection, hall)
            if hall_row is not None and hall_row["close_started"]:
                raise ApiError("closed_session", 409)
            if hall_row is not None and hall_row["mode"] == "ordinary":
                raise ApiError("not_margin_session", 409)
            if steps > available_commitment(connection, hall):
                # Deliberately before insertion: an insufficient commitment does
                # not occupy its request number.
                raise ApiError("margin_exceeded", 422)
            connection.execute('''
                INSERT INTO margin_requests (hall, request_id, steps)
                VALUES (?, ?, ?)
            ''', (hall, request_id, steps))

    try:
        result = room.call("POST", INTERNAL_RAISE_ROUTE, {
            "hall": hall, "request_id": request_id, "steps": steps, "margin": True,
        })
    except LinkUnavailable:
        return pending_raise(hall, request_id, steps)

    with database.write_transaction() as connection:
        row = get_margin_request(connection, hall, request_id)
        if row is None or row["steps"] != steps:
            # Should be impossible; do not overwrite a conflicting identity.
            raise ApiError("parameter_conflict", 409)
        terminal = result if result.get("status") in {"applied", "rejected"} else None
        if terminal is not None:
            connection.execute('''
                UPDATE margin_requests SET terminal = ?
                WHERE hall = ? AND request_id = ? AND terminal IS NULL
            ''', (json.dumps(terminal), hall, request_id))
        return terminal if terminal is not None else pending_raise(hall, request_id, steps)


def query_margin_request(database, room, hall, request_id):
    with database.read_snapshot() as connection:
        row = get_margin_request(connection, hall, request_id)
        if row is None:
            return None
        steps = row["steps"]
        if row["terminal"] is not None:
            return json.loads(row["terminal"])

    try:
        receipt = room.read_receipt(hall, request_id)
    except LinkUnavailable:
        receipt = None
    if receipt is None:
        return pending_raise(hall, request_id, steps)

    with database.write_transaction() as connection:
        current = get_margin_request(connection, hall, request_id)
        if current is None:
            return pending_raise(hall, request_id, steps)
        if current["terminal"] is None and receipt.get("status") in {"applied", "rejected"}:
            connection.execute(
                "UPDATE margin_requests SET terminal = ? WHERE hall = ? AND request_id = ?",
                (json.dumps(receipt), hall, request_id),
            )
        return receipt
