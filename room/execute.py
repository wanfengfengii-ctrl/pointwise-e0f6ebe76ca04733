from http_json import ApiError, identifier
from room.adjustment import GainChange, GainRangeError, project_levels
from room.history import append_operation, find_remote_result, record_remote_result
from room.levels import read_levels, write_levels
from room.margin import execute_margin_raise, get_margin_config
from session.store import get_session


def execute_adjustment(database, hall, body):
    if body.get("margin") is True:
        return execute_margin_raise(database, hall, body)
    request_id = identifier(body.get("request_id"))
    change = GainChange.from_payload(body.get("change"))
    parameters = change.to_payload()
    with database.write_transaction() as connection:
        if get_margin_config(connection, hall) is not None:
            raise ApiError("not_margin_session", 409)
        previous = find_remote_result(connection, hall, request_id)
        if previous is not None:
            if previous["change"] != parameters:
                raise ApiError("parameter_conflict", 409)
            return previous

        if get_session(connection, hall)["status"] != "open":
            raise ApiError("closed_session", 409)
        levels = read_levels(connection, hall)
        identity = {"hall": hall, "request_id": request_id, "change": parameters}
        try:
            after = project_levels(levels, change)
        except GainRangeError as error:
            result = {**identity, "status": "rejected", "reason": error.code}
        else:
            before = {channel: levels[channel] for channel in after}
            write_levels(connection, hall, after)
            result = append_operation(connection, hall, "remote", request_id, {
                **identity, "status": "applied", "before": before, "after": after,
            })
        record_remote_result(connection, hall, request_id, result)
        return result
