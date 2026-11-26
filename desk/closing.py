from desk.margin import (
    finish_close,
    has_pending_margin_requests,
    list_terminal_margin_requests,
    start_close,
)
from desk.requests import has_pending_requests, list_terminal_requests
from http_json import ApiError


def close_with_desk_status(database, room, hall):
    with database.write_transaction() as connection:
        if (has_pending_requests(connection, hall)
                or has_pending_margin_requests(connection, hall)):
            raise ApiError("pending_requests", 409)
        terminal = [
            *list_terminal_requests(connection, hall),
            *list_terminal_margin_requests(connection, hall),
        ]
        # Persist the admission fence before any network close attempt. This
        # transaction is committed before the HTTP call so a held close reply
        # cannot block a late grant receipt from recording its evidence.
        start_close(connection, hall)

    result = room.call("POST", "/_room/close", {"hall": hall, "terminal": terminal})

    with database.write_transaction() as connection:
        finish_close(connection, hall, result)
    return result
