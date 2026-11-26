from desk.requests import parse_adjustment
from http_json import ApiError, identifier
from room.adjustment import project_levels


def preview_adjustment(room, body):
    hall = identifier(body.get("hall"))
    change = parse_adjustment(body.get("change"))
    snapshot = room.read_levels(hall)
    if snapshot["status"] != "open":
        raise ApiError("closed_session", 409)
    levels = snapshot["levels"]
    after = project_levels(levels, change)
    before = {channel: levels[channel] for channel in after}
    return {"hall": hall, "before": before, "after": after}
