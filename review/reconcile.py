from http_json import ApiError


def _index_results(hall, results):
    if not isinstance(results, list):
        raise ApiError("review_mismatch", 409)
    indexed = {}
    for result in results:
        if not isinstance(result, dict) or result.get("hall") != hall:
            raise ApiError("review_mismatch", 409)
        request_id = result.get("request_id")
        if not isinstance(request_id, str) or request_id in indexed:
            raise ApiError("review_mismatch", 409)
        if result.get("status") not in ("applied", "rejected"):
            raise ApiError("review_mismatch", 409)
        indexed[request_id] = result
    return indexed


def reconcile_operations(hall, operations, room_results, desk_results):
    confirmed = _index_results(hall, desk_results)
    if confirmed != _index_results(hall, room_results):
        raise ApiError("review_mismatch", 409)

    applied = {number: result for number, result in confirmed.items() if result["status"] == "applied"}
    entries = []
    for entry in operations:
        if entry["origin"] == "remote":
            actual = {key: value for key, value in entry.items() if key != "origin"}
            if applied.pop(entry["request_id"], None) != actual:
                raise ApiError("review_mismatch", 409)
        entries.append(entry)
    if applied:
        raise ApiError("review_mismatch", 409)
    return entries
