from http_json import ApiError, identifier
from session.channels import list_channels
from sound.samples import read_sample


def route_samples(connection, hall, selection):
    if not isinstance(selection, dict):
        raise ApiError("invalid_selection")
    channels = [channel.name for channel in list_channels(connection, hall)]
    for channel in selection:
        if channel not in channels:
            raise ApiError("unknown_channel", 404, channel=channel)
    routed = {}
    for channel in channels:
        if channel not in selection:
            raise ApiError("missing_sample", 422, channel=channel)
        sample_id = identifier(selection[channel], "invalid_selection")
        frames = read_sample(connection, hall, channel, sample_id)
        if not frames:
            raise ApiError("missing_sample", 422, channel=channel, sample_id=sample_id)
        routed[channel] = frames
    return routed
