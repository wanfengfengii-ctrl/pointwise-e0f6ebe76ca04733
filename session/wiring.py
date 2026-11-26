from http_json import ApiError, identifier
from session.channels import Channel


def validate_wiring(sources, rows):
    if not isinstance(sources, list) or not isinstance(rows, list) or len(rows) < 2:
        raise ApiError("invalid_wiring")
    declared_sources = set()
    for source in sources:
        name = identifier(source, "invalid_wiring")
        if name in declared_sources:
            raise ApiError("invalid_wiring", reason="duplicate_source", source=name)
        declared_sources.add(name)

    channels = []
    seen = set()
    for position, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"channel", "source"}:
            raise ApiError("invalid_wiring")
        channel = identifier(row["channel"], "invalid_wiring")
        source = identifier(row["source"], "invalid_wiring")
        if channel in seen:
            raise ApiError("invalid_wiring", reason="duplicate_channel", channel=channel)
        if source not in declared_sources:
            raise ApiError("invalid_wiring", reason="unregistered_source", source=source)
        seen.add(channel)
        channels.append(Channel(channel, source, position))
    return channels
