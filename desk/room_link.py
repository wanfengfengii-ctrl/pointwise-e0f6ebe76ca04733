import http.client

from http_json import ApiError, json_request, query_path


class LinkUnavailable(ApiError):
    def __init__(self):
        super().__init__("room_unavailable", 503)


class RoomClient:
    def __init__(self, port):
        self.port = port

    def call(self, method, path, body=None):
        try:
            status, payload = json_request(self.port, method, path, body)
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise LinkUnavailable() from exc
        if status >= 500:
            raise LinkUnavailable()
        if status != 200:
            details = dict(payload)
            error = details.pop("error", "room_error")
            raise ApiError(error, status, **details)
        return payload

    def read_levels(self, hall):
        return self.call("GET", query_path("/_room/levels", hall=hall))

    def send_adjustment(self, request):
        return self.call("POST", "/_room/execute", request.envelope())

    def read_receipt(self, hall, request_id):
        path = query_path("/_room/receipt", hall=hall, request_id=request_id)
        try:
            return self.call("GET", path)
        except ApiError as exc:
            if exc.code == "unknown_receipt":
                return None
            raise
