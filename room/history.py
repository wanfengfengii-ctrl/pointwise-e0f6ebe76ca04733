import json


def initialize_history(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS operations (
            hall TEXT NOT NULL REFERENCES sessions (hall),
            sequence INTEGER NOT NULL CHECK (sequence > 0),
            origin TEXT NOT NULL CHECK (origin IN ('manual', 'remote')),
            operation_id TEXT NOT NULL,
            result TEXT NOT NULL,
            PRIMARY KEY (hall, sequence),
            UNIQUE (hall, origin, operation_id)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS remote_results (
            hall TEXT NOT NULL REFERENCES sessions (hall),
            request_id TEXT NOT NULL,
            result TEXT NOT NULL,
            PRIMARY KEY (hall, request_id)
        )
    ''')


def append_operation(connection, hall, origin, operation_id, receipt):
    sequence = connection.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM operations WHERE hall = ?", (hall,)
    ).fetchone()[0]
    result = {**receipt, "sequence": sequence}
    connection.execute('''
        INSERT INTO operations (hall, sequence, origin, operation_id, result) VALUES (?, ?, ?, ?, ?)
    ''', (hall, sequence, origin, operation_id, json.dumps(result)))
    return result


def find_remote_result(connection, hall, request_id):
    row = connection.execute(
        "SELECT result FROM remote_results WHERE hall = ? AND request_id = ?", (hall, request_id)
    ).fetchone()
    return None if row is None else json.loads(row["result"])


def record_remote_result(connection, hall, request_id, result):
    connection.execute(
        "INSERT INTO remote_results (hall, request_id, result) VALUES (?, ?, ?)",
        (hall, request_id, json.dumps(result)),
    )


def find_manual_result(connection, hall, operation_id):
    row = connection.execute('''
        SELECT result FROM operations WHERE hall = ? AND origin = 'manual' AND operation_id = ?
    ''', (hall, operation_id)).fetchone()
    return None if row is None else json.loads(row["result"])


def list_operations(connection, hall):
    rows = connection.execute(
        "SELECT origin, result FROM operations WHERE hall = ? ORDER BY sequence", (hall,)
    )
    return [{**json.loads(row["result"]), "origin": row["origin"]} for row in rows]


def list_remote_results(connection, hall):
    rows = connection.execute("SELECT result FROM remote_results WHERE hall = ?", (hall,))
    return [json.loads(row["result"]) for row in rows]
