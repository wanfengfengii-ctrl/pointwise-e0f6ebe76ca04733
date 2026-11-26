from sqlite_store import transaction


class DeskDatabase:
    def __init__(self, path):
        self.path = path

    def initialize(self):
        with self.write_transaction() as connection:
            connection.execute('''
                CREATE TABLE IF NOT EXISTS requests (
                    hall TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    parameters TEXT NOT NULL,
                    terminal TEXT,
                    PRIMARY KEY (hall, request_id)
                )
            ''')

    def read_snapshot(self):
        return transaction(self.path, write=False)

    def write_transaction(self):
        return transaction(self.path, write=True)
