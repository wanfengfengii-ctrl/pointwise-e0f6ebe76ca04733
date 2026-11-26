from http_json import ApiError, identifier
from room.levels import register_initial_levels
from room.margin import parse_and_register_margin
from session.channels import register_channels
from session.store import insert_session
from session.wiring import validate_wiring


def open_session(database, body):
    hall = identifier(body.get("hall"))
    channels = validate_wiring(body.get("sources"), body.get("wiring"))
    raw_margin = body.get("margin")
    if "margin" in body and raw_margin is None:
        raise ApiError("invalid_margin")
    with database.write_transaction() as connection:
        insert_session(connection, hall)
        register_channels(connection, hall, channels)
        levels = register_initial_levels(connection, hall, channels, body.get("initial"))
        parse_and_register_margin(connection, hall, raw_margin, channels, levels)
    return {"hall": hall, "status": "open", "levels": levels}
