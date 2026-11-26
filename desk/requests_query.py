from desk.margin import query_margin_request
from desk.requests import get_request, record_terminal
from desk.room_link import LinkUnavailable
from http_json import ApiError


def query_request(database, room, hall, request_id):
    with database.read_snapshot() as connection:
        request = get_request(connection, hall, request_id)
    if request is None:
        margin_result = query_margin_request(database, room, hall, request_id)
        if margin_result is None:
            raise ApiError("unknown_request", 404)
        return margin_result
    if request.terminal is not None:
        return request.response()
    try:
        result = room.read_receipt(hall, request_id)
    except LinkUnavailable:
        result = None
    if result is None:
        with database.read_snapshot() as connection:
            return get_request(connection, hall, request_id).response()
    with database.write_transaction() as connection:
        return record_terminal(connection, request, result)
