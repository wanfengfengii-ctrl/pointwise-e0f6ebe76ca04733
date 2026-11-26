import json


def initialize_reports(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            hall TEXT PRIMARY KEY REFERENCES sessions (hall),
            report_id TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL
        )
    ''')


def report_number(hall):
    return f"review-{hall}"


def store_report(connection, hall, entries):
    number = report_number(hall)
    report = {"hall": hall, "report_id": number, "operations": entries}
    connection.execute(
        "INSERT INTO reports (hall, report_id, payload) VALUES (?, ?, ?)",
        (hall, number, json.dumps(report)),
    )
    return report


def read_report(connection, hall, number):
    row = connection.execute(
        "SELECT payload FROM reports WHERE hall = ? AND report_id = ?", (hall, number)
    ).fetchone()
    return None if row is None else json.loads(row["payload"])
