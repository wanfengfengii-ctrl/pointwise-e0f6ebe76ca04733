from dataclasses import dataclass

from http_json import ApiError


@dataclass(frozen=True)
class Channel:
    name: str
    source: str
    position: int


def initialize_channels(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            hall TEXT NOT NULL REFERENCES sessions (hall),
            name TEXT NOT NULL,
            source TEXT NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY (hall, name),
            UNIQUE (hall, position)
        )
    ''')


def register_channels(connection, hall, channels):
    connection.executemany(
        "INSERT INTO channels (hall, name, source, position) VALUES (?, ?, ?, ?)",
        [(hall, channel.name, channel.source, channel.position) for channel in channels],
    )


def list_channels(connection, hall):
    rows = connection.execute(
        "SELECT name, source, position FROM channels WHERE hall = ? ORDER BY position", (hall,)
    )
    return [Channel(row["name"], row["source"], row["position"]) for row in rows]


def get_channel(connection, hall, name):
    row = connection.execute(
        "SELECT name, source, position FROM channels WHERE hall = ? AND name = ?", (hall, name)
    ).fetchone()
    if row is None:
        raise ApiError("unknown_channel", 404, channel=name)
    return Channel(row["name"], row["source"], row["position"])
