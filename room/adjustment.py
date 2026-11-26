from dataclasses import dataclass

from http_json import ApiError, identifier


MIN_GAIN = 0
MAX_GAIN = 10


class GainRangeError(ApiError):
    def __init__(self):
        super().__init__("range_exceeded", 422)


def validate_gain(value):
    if type(value) is not int or not MIN_GAIN <= value <= MAX_GAIN:
        raise ApiError("invalid_gain")
    return value


@dataclass(frozen=True)
class GainChange:
    kind: str
    source: str
    target: str
    steps: int | None = None
    source_gain: int | None = None
    target_gain: int | None = None

    @classmethod
    def from_payload(cls, payload):
        if not isinstance(payload, dict):
            raise ApiError("invalid_change")
        kind = payload.get("kind")
        common = {"kind", "source", "target"}
        if kind == "transfer" and set(payload) == common | {"steps"}:
            amounts = {"steps": validate_gain(payload["steps"])}
        elif kind == "set" and set(payload) == common | {"source_gain", "target_gain"}:
            amounts = {
                "source_gain": validate_gain(payload["source_gain"]),
                "target_gain": validate_gain(payload["target_gain"]),
            }
        else:
            raise ApiError("invalid_change")
        source = identifier(payload["source"], "invalid_change")
        target = identifier(payload["target"], "invalid_change")
        if source == target:
            raise ApiError("invalid_change")
        return cls(kind, source, target, **amounts)

    def to_payload(self):
        payload = {"kind": self.kind, "source": self.source, "target": self.target}
        if self.kind == "transfer":
            return {**payload, "steps": self.steps}
        return {**payload, "source_gain": self.source_gain, "target_gain": self.target_gain}

    def require_channels(self, levels):
        for channel in (self.source, self.target):
            if channel not in levels:
                raise ApiError("unknown_channel", 404, channel=channel)


def project_levels(levels, change):
    change.require_channels(levels)
    if change.kind == "set":
        return {change.source: change.source_gain, change.target: change.target_gain}
    source_gain = levels[change.source] - change.steps
    target_gain = levels[change.target] + change.steps
    if not (MIN_GAIN <= source_gain <= MAX_GAIN and MIN_GAIN <= target_gain <= MAX_GAIN):
        raise GainRangeError()
    return {change.source: source_gain, change.target: target_gain}
