from desk.margin import get_hall
from desk.requests import DeskRequest, get_request, parse_adjustment, record_terminal, register_request
from desk.room_link import LinkUnavailable
from http_json import ApiError, identifier


def submit_adjustment(database, room, body):
    hall = identifier(body.get("hall"))
    request_id = identifier(body.get("request_id"))
    change = parse_adjustment(body.get("change"))
    with database.read_snapshot() as connection:
        previous = get_request(connection, hall, request_id)
        hall_row = get_hall(connection, hall)

    if hall_row is not None and hall_row["mode"] == "margin":
        raise ApiError("not_margin_session", 409)

    if previous is None:
        snapshot = room.read_levels(hall)
        if snapshot["status"] != "open":
            raise ApiError("closed_session", 409)
        if snapshot.get("margin") is not None:
            raise ApiError("not_margin_session", 409)
        change.require_channels(snapshot["levels"])

    with database.write_transaction() as connection:
        request = register_request(connection, DeskRequest(hall, request_id, change))
    return dispatch_request(database, room, request)


def dispatch_request(database, room, request):
    if request.terminal is not None:
        return request.response()
    try:
        result = room.send_adjustment(request)
    except LinkUnavailable:
        with database.read_snapshot() as connection:
            return get_request(connection, request.hall, request.request_id).response()
    with database.write_transaction() as connection:
        return record_terminal(connection, request, result)
