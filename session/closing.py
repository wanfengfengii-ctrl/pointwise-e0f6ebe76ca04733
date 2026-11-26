from review.collect import collect_operations
from review.reconcile import reconcile_operations
from review.report import report_number, store_report
from session.store import get_session, mark_closed


def close_session(database, hall, desk_results):
    with database.write_transaction() as connection:
        session = get_session(connection, hall)
        if session["status"] == "open":
            operations, room_results = collect_operations(connection, hall)
            entries = reconcile_operations(hall, operations, room_results, desk_results)
            store_report(connection, hall, entries)
            mark_closed(connection, hall)
    return {"hall": hall, "status": "closed", "report_id": report_number(hall)}
