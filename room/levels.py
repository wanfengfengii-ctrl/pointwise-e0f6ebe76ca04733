from http_json import ApiError
from room.adjustment import MAX_GAIN, MIN_GAIN, validate_gain


def initialize_levels(connection):
    connection.execute(f'''
        CREATE TABLE IF NOT EXISTS levels (
            hall TEXT NOT NULL,
            channel TEXT NOT NULL,
            gain INTEGER NOT NULL CHECK (gain BETWEEN {MIN_GAIN} AND {MAX_GAIN}),
            PRIMARY KEY (hall, channel),
            FOREIGN KEY (hall, channel) REFERENCES channels (hall, name)
        )
    ''')


def register_initial_levels(connection, hall, channels, initial):
    if not isinstance(initial, dict) or set(initial) != {channel.name for channel in channels}:
        raise ApiError("invalid_initial")
    levels = {channel.name: validate_gain(initial[channel.name]) for channel in channels}
    connection.executemany(
        "INSERT INTO levels (hall, channel, gain) VALUES (?, ?, ?)",
        [(hall, channel, gain) for channel, gain in levels.items()],
    )
    return levels


def read_levels(connection, hall):
    rows = connection.execute('''
        SELECT levels.channel, levels.gain
        FROM levels JOIN channels ON channels.hall = levels.hall AND channels.name = levels.channel
        WHERE levels.hall = ? ORDER BY channels.position
    ''', (hall,))
    return {row["channel"]: row["gain"] for row in rows}


def write_levels(connection, hall, levels):
    connection.executemany(
        "UPDATE levels SET gain = ? WHERE hall = ? AND channel = ?",
        [(gain, hall, channel) for channel, gain in levels.items()],
    )
