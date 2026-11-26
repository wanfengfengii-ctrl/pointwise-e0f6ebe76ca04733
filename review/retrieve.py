from http_json import ApiError
from review.report import read_report


def retrieve_report(database, hall, number):
    with database.read_snapshot() as connection:
        report = read_report(connection, hall, number)
    if report is None:
        raise ApiError("unknown_report", 404)
    return report
