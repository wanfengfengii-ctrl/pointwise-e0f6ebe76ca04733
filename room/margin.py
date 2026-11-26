"""Margin-session accounting and room-side operations."""
from http_json import ApiError, identifier
from room.adjustment import validate_gain
from room.history import (
    append_operation,
    find_manual_result,
    find_remote_result,
    record_remote_result,
)
from room.levels import read_levels, write_levels
from session.store import get_session


MARGIN_CHANNELS = ("local_channel", "remote_channel")


def initialize_margin_tables(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS margin_config (
            hall TEXT PRIMARY KEY REFERENCES sessions (hall),
            "limit" INTEGER NOT NULL CHECK ("limit" BETWEEN 1 AND 10),
            local_channel TEXT NOT NULL,
            remote_channel TEXT NOT NULL,
            CHECK (local_channel <> remote_channel)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS margin_grants (
            hall TEXT NOT NULL REFERENCES sessions (hall),
            grant_id TEXT NOT NULL,
            steps INTEGER NOT NULL CHECK (steps > 0),
            position INTEGER NOT NULL,
            PRIMARY KEY (hall, grant_id)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS margin_fulfillments (
            hall TEXT NOT NULL REFERENCES sessions (hall),
            request_id TEXT NOT NULL,
            steps INTEGER NOT NULL CHECK (steps > 0),
            PRIMARY KEY (hall, request_id)
        )
    ''')


def validate_steps(value):
    if type(value) is not int or value <= 0:
        raise ApiError("invalid_steps")
    return value


def parse_and_register_margin(connection, hall, raw, channels, levels):
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != {"limit", *MARGIN_CHANNELS}:
        raise ApiError("invalid_margin")

    limit = raw["limit"]
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ApiError("invalid_margin", reason="invalid_limit")
    local_channel = identifier(raw["local_channel"], "invalid_margin")
    remote_channel = identifier(raw["remote_channel"], "invalid_margin")
    channel_names = {channel.name for channel in channels}
    if (local_channel == remote_channel or len(channels) != 2
            or channel_names != {local_channel, remote_channel}):
        raise ApiError("invalid_margin", reason="invalid_channels")
    if sum(levels.values()) > limit:
        raise ApiError("invalid_margin", 400, reason="initial_exceeds_limit")

    connection.execute('''
        INSERT INTO margin_config (hall, "limit", local_channel, remote_channel)
        VALUES (?, ?, ?, ?)
    ''', (hall, limit, local_channel, remote_channel))
    return get_margin_config(connection, hall)


def get_margin_config(connection, hall):
    row = connection.execute(
        'SELECT hall, "limit", local_channel, remote_channel '
        'FROM margin_config WHERE hall = ?',
        (hall,),
    ).fetchone()
    if row is None:
        return None
    return {
        "hall": row["hall"],
        "limit": row["limit"],
        "local_channel": row["local_channel"],
        "remote_channel": row["remote_channel"],
    }


def require_margin_config(connection, hall):
    config = get_margin_config(connection, hall)
    if config is None:
        raise ApiError("not_margin_session", 409)
    return config


def _grant_total(connection, hall):
    return connection.execute(
        "SELECT COALESCE(SUM(steps), 0) FROM margin_grants WHERE hall = ?",
        (hall,),
    ).fetchone()[0]


def _fulfilled_total(connection, hall):
    return connection.execute(
        "SELECT COALESCE(SUM(steps), 0) FROM margin_fulfillments WHERE hall = ?",
        (hall,),
    ).fetchone()[0]


def outstanding_grant_steps(connection, hall):
    """Granted room capacity not yet consumed by a landed remote operation."""
    return _grant_total(connection, hall) - _fulfilled_total(connection, hall)


def _room_available(connection, config, levels):
    reserved = outstanding_grant_steps(connection, config["hall"])
    return config["limit"] - sum(levels.values()) - reserved


def _grant_public(row):
    return {
        "hall": row["hall"],
        "grant_id": row["grant_id"],
        "steps": row["steps"],
        "status": "granted",
    }


def _grant_evidence(connection, hall, current):
    rows = connection.execute('''
        SELECT hall, grant_id, steps FROM margin_grants
        WHERE hall = ? ORDER BY position
    ''', (hall,)).fetchall()
    grants = [{"grant_id": row["grant_id"], "steps": row["steps"]} for row in rows]
    return {**current, "evidence": {"hall": hall, "grants": grants}}


def grant_margin(database, hall, body):
    grant_id = identifier(body.get("grant_id"))
    steps = validate_steps(body.get("steps"))
    with database.write_transaction() as connection:
        session = get_session(connection, hall)
        config = require_margin_config(connection, hall)
        row = connection.execute(
            "SELECT hall, grant_id, steps FROM margin_grants WHERE hall = ? AND grant_id = ?",
            (hall, grant_id),
        ).fetchone()
        if row is not None:
            if row["steps"] != steps:
                raise ApiError("parameter_conflict", 409)
            public = _grant_public(row)
            return _grant_evidence(connection, hall, public)

        if session["status"] != "open":
            raise ApiError("closed_session", 409)
        levels = read_levels(connection, hall)
        if steps > _room_available(connection, config, levels):
            raise ApiError("margin_exceeded", 422)

        position = connection.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM margin_grants WHERE hall = ?",
            (hall,),
        ).fetchone()[0]
        connection.execute('''
            INSERT INTO margin_grants (hall, grant_id, steps, position)
            VALUES (?, ?, ?, ?)
        ''', (hall, grant_id, steps, position))
        public = {"hall": hall, "grant_id": grant_id, "steps": steps, "status": "granted"}
        return _grant_evidence(connection, hall, public)


def apply_margin_local(database, hall, body):
    operation_id = identifier(body.get("operation_id"))
    gain = validate_gain(body.get("gain"))
    with database.write_transaction() as connection:
        session = get_session(connection, hall)
        config = require_margin_config(connection, hall)
        previous = find_manual_result(connection, hall, operation_id)
        if previous is not None:
            if previous.get("gain") != gain:
                raise ApiError("parameter_conflict", 409)
            return previous

        if session["status"] != "open":
            raise ApiError("closed_session", 409)

        channel = config["local_channel"]
        before = read_levels(connection, hall)
        after = {**before, channel: gain}
        if sum(after.values()) + outstanding_grant_steps(connection, hall) > config["limit"]:
            raise ApiError("margin_exceeded", 422)

        write_levels(connection, hall, after)
        return append_operation(connection, hall, "manual", operation_id, {
            "hall": hall,
            "operation_id": operation_id,
            "channel": channel,
            "gain": gain,
            "status": "applied",
            "before": before,
            "after": after,
        })


def execute_margin_raise(database, hall, body):
    request_id = identifier(body.get("request_id"))
    steps = validate_steps(body.get("steps"))
    with database.write_transaction() as connection:
        session = get_session(connection, hall)
        config = require_margin_config(connection, hall)
        previous = find_remote_result(connection, hall, request_id)
        if previous is not None:
            if previous.get("steps") != steps:
                raise ApiError("parameter_conflict", 409)
            return previous

        if session["status"] != "open":
            raise ApiError("closed_session", 409)

        channel = config["remote_channel"]
        before = read_levels(connection, hall)
        if type(before.get(channel)) is not int:
            raise ApiError("unknown_channel", 404, channel=channel)
        after = {**before, channel: before[channel] + steps}
        reserved = outstanding_grant_steps(connection, hall)
        if steps > reserved or after[channel] > 10 or after[channel] < 0:
            raise ApiError("margin_exceeded", 422)
        if sum(after.values()) + reserved - steps > config["limit"]:
            raise ApiError("margin_exceeded", 422)

        write_levels(connection, hall, after)
        result = append_operation(connection, hall, "remote", request_id, {
            "hall": hall,
            "request_id": request_id,
            "steps": steps,
            "status": "applied",
            "before": before,
            "after": after,
        })
        record_remote_result(connection, hall, request_id, result)
        connection.execute('''
            INSERT INTO margin_fulfillments (hall, request_id, steps)
            VALUES (?, ?, ?)
        ''', (hall, request_id, steps))
        return result
