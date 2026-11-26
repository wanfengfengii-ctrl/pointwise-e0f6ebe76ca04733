from http_json import identifier
from room.levels import register_initial_levels
from session.channels import register_channels
from session.store import insert_session
from session.wiring import validate_wiring


def open_session(database, body):
    hall = identifier(body.get("hall"))
    channels = validate_wiring(body.get("sources"), body.get("wiring"))
    with database.write_transaction() as connection:
        insert_session(connection, hall)
        register_channels(connection, hall, channels)
        levels = register_initial_levels(connection, hall, channels, body.get("initial"))
    return {"hall": hall, "status": "open", "levels": levels}
