from http_json import ApiError, identifier
from room.adjustment import validate_gain
from room.history import append_operation, find_manual_result
from room.levels import read_levels, write_levels
from session.channels import get_channel
from session.store import get_session


def apply_manual(database, hall, body):
    operation_id = identifier(body.get("operation_id"))
    channel = identifier(body.get("channel"))
    gain = validate_gain(body.get("gain"))
    with database.write_transaction() as connection:
        previous = find_manual_result(connection, hall, operation_id)
        if previous is not None:
            if previous["channel"] != channel or previous["gain"] != gain:
                raise ApiError("parameter_conflict", 409)
            return previous
        if get_session(connection, hall)["status"] != "open":
            raise ApiError("closed_session", 409)
        get_channel(connection, hall, channel)
        before = read_levels(connection, hall)
        write_levels(connection, hall, {channel: gain})
        return append_operation(connection, hall, "manual", operation_id, {
            "hall": hall, "operation_id": operation_id, "channel": channel, "gain": gain,
            "status": "applied", "before": before, "after": {**before, channel: gain},
        })
