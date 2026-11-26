import argparse
from http.server import ThreadingHTTPServer

from http_json import ApiError, JsonHandler, identifier
from review.retrieve import retrieve_report
from room.execute import execute_adjustment
from room.history import find_remote_result
from room.levels import read_levels
from room.manual import apply_manual
from session.closing import close_session
from session.opening import open_session
from session.store import RoomDatabase, get_session
from sound.monitor import listen
from sound.samples import bind_sample


class RoomHandler(JsonHandler):
    def do_GET(self):
        self.respond(self._get)

    def do_POST(self):
        self.respond(self._post)

    def _get(self):
        database = self.server.database
        if self.route == "/report":
            hall, number = self.query("hall", "report_id")
            return retrieve_report(database, hall, number)
        if self.route == "/_room/levels":
            hall, = self.query("hall")
            with database.read_snapshot() as connection:
                session = get_session(connection, hall)
                return {**session, "levels": read_levels(connection, hall)}
        if self.route == "/_room/receipt":
            hall, request_id = self.query("hall", "request_id")
            with database.read_snapshot() as connection:
                receipt = find_remote_result(connection, hall, request_id)
            if receipt is None:
                raise ApiError("unknown_receipt", 404)
            return receipt
        raise ApiError("unknown_route", 404)

    def _post(self):
        database = self.server.database
        route = self.route
        body = self.read_object()
        if route == "/open":
            return open_session(database, body)
        hall = identifier(body.get("hall"))
        if route == "/sample":
            with database.write_transaction() as connection:
                get_session(connection, hall)
                return bind_sample(connection, hall, body)
        if route == "/listen":
            return listen(database, hall, body.get("samples"))
        if route == "/manual":
            return apply_manual(database, hall, body)
        if route == "/_room/execute":
            return execute_adjustment(database, hall, body)
        if route == "/_room/close":
            return close_session(database, hall, body.get("terminal"))
        raise ApiError("unknown_route", 404)


def serve_room(path, port=0):
    database = RoomDatabase(path)
    database.initialize()
    server = ThreadingHTTPServer(("127.0.0.1", port), RoomHandler)
    server.database = database
    return server


def main():
    parser = argparse.ArgumentParser(description="Hall gain and reference audio service")
    parser.add_argument("--db", required=True)
    parser.add_argument("--port", type=int, default=8101)
    args = parser.parse_args()
    with serve_room(args.db, args.port) as server:
        print(server.server_port, flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
