import http.client
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlencode, urlsplit


class ApiError(Exception):
    def __init__(self, code, status=400, **details):
        super().__init__(code)
        self.code = code
        self.status = status
        self.payload = {"error": code, **details}


def identifier(value, error="invalid_identifier"):
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ApiError(error)
    return value


def query_path(path, **parameters):
    return f"{path}?{urlencode(parameters)}"


def json_request(port, method, path, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        if body is None:
            connection.request(method, path)
        else:
            connection.request(method, path, json.dumps(body).encode("utf-8"),
                               {"Content-Type": "application/json"})
        response = connection.getresponse()
        payload = json.loads(response.read())
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON response object")
        return response.status, payload
    finally:
        connection.close()


class JsonHandler(BaseHTTPRequestHandler):
    @property
    def route(self):
        return urlsplit(self.path).path

    def query(self, *names):
        values = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        if set(values) != set(names) or any(len(items) != 1 for items in values.values()):
            raise ApiError("invalid_query")
        return [identifier(values[name][0]) for name in names]

    def read_object(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                raise ValueError("Missing JSON body")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, RecursionError) as exc:
            raise ApiError("invalid_json") from exc
        if not isinstance(payload, dict):
            raise ApiError("invalid_json")
        return payload

    def respond(self, action):
        try:
            result = action()
        except ApiError as exc:
            self.send_json(exc.status, exc.payload)
        else:
            if isinstance(result, tuple):
                self.send_json(*result)
            else:
                self.send_json(200, result)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def log_message(self, format, *args):
        return
