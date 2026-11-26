import json

from http_json import ApiError, identifier
from session.channels import get_channel


def initialize_samples(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS samples (
            hall TEXT NOT NULL,
            channel TEXT NOT NULL,
            sample_id TEXT NOT NULL,
            frames TEXT NOT NULL,
            PRIMARY KEY (hall, channel, sample_id),
            FOREIGN KEY (hall, channel) REFERENCES channels (hall, name)
        )
    ''')


def bind_sample(connection, hall, body):
    channel = identifier(body.get("channel"))
    sample_id = identifier(body.get("sample_id"), "invalid_sample")
    frames = body.get("frames")
    if not isinstance(frames, list) or any(type(frame) is not int for frame in frames):
        raise ApiError("invalid_sample")
    get_channel(connection, hall, channel)
    connection.execute('''
        INSERT INTO samples (hall, channel, sample_id, frames) VALUES (?, ?, ?, ?)
        ON CONFLICT (hall, channel, sample_id) DO UPDATE SET frames = excluded.frames
    ''', (hall, channel, sample_id, json.dumps(frames)))
    return {"hall": hall, "channel": channel, "sample_id": sample_id}


def read_sample(connection, hall, channel, sample_id):
    row = connection.execute('''
        SELECT frames FROM samples WHERE hall = ? AND channel = ? AND sample_id = ?
    ''', (hall, channel, sample_id)).fetchone()
    return None if row is None else json.loads(row["frames"])
