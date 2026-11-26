from http_json import ApiError
from review.report import initialize_reports
from room.history import initialize_history
from room.levels import initialize_levels
from session.channels import initialize_channels
from sound.samples import initialize_samples
from sqlite_store import transaction


class RoomDatabase:
    def __init__(self, path):
        self.path = path

    def initialize(self):
        with self.write_transaction() as connection:
            connection.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    hall TEXT PRIMARY KEY,
                    closed INTEGER NOT NULL DEFAULT 0 CHECK (closed IN (0, 1))
                )
            ''')
            from room.margin import initialize_margin_tables
            initialize_margin_tables(connection)
            initialize_channels(connection)
            initialize_levels(connection)
            initialize_samples(connection)
            initialize_history(connection)
            initialize_reports(connection)

    def read_snapshot(self):
        return transaction(self.path, write=False)

    def write_transaction(self):
        return transaction(self.path, write=True)


def get_session(connection, hall):
    row = connection.execute("SELECT closed FROM sessions WHERE hall = ?", (hall,)).fetchone()
    if row is None:
        raise ApiError("unknown_session", 404)
    return {"hall": hall, "status": "closed" if row["closed"] else "open"}


def insert_session(connection, hall):
    cursor = connection.execute(
        "INSERT INTO sessions (hall) VALUES (?) ON CONFLICT (hall) DO NOTHING", (hall,)
    )
    if cursor.rowcount == 0:
        raise ApiError("session_conflict", 409)


def mark_closed(connection, hall):
    connection.execute("UPDATE sessions SET closed = 1 WHERE hall = ?", (hall,))
