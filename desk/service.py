import argparse
from http.server import ThreadingHTTPServer

from desk.closing import close_with_desk_status
from desk.dispatch import submit_adjustment
from desk.margin import note_opened_hall, submit_grant, submit_raise
from desk.preview import preview_adjustment
from desk.requests_query import query_request
from desk.room_link import RoomClient
from desk.store import DeskDatabase
from http_json import ApiError, JsonHandler, identifier


class DeskHandler(JsonHandler):
    def do_GET(self):
        self.respond(self._get)

    def do_POST(self):
        self.respond(self._post)

    def _get(self):
        room = self.server.room
        if self.route == "/request":
            hall, request_id = self.query("hall", "request_id")
            return query_request(self.server.database, room, hall, request_id)
        if self.route == "/report":
            self.query("hall", "report_id")
            return room.call("GET", self.path)
        raise ApiError("unknown_route", 404)

    def _post(self):
        database = self.server.database
        room = self.server.room
        route = self.route
        body = self.read_object()
        if route == "/preview":
            return preview_adjustment(room, body)
        if route == "/submit":
            return submit_adjustment(database, room, body)
        if route == "/margin/grant":
            return submit_grant(database, room, body)
        if route == "/margin/raise":
            return submit_raise(database, room, body)
        if route == "/close":
            return close_with_desk_status(database, room, identifier(body.get("hall")))
        if route == "/open":
            result = room.call("POST", "/open", body)
            hall = identifier(body.get("hall"))
            with database.write_transaction() as connection:
                note_opened_hall(connection, hall, isinstance(body.get("margin"), dict))
            return result
        if route in {"/sample", "/listen", "/manual", "/margin/local"}:
            return room.call("POST", route, body)
        raise ApiError("unknown_route", 404)


def serve_desk(path, room_port, port=0):
    database = DeskDatabase(path)
    database.initialize()
    server = ThreadingHTTPServer(("127.0.0.1", port), DeskHandler)
    server.database = database
    server.room = RoomClient(room_port)
    return server


def main():
    parser = argparse.ArgumentParser(description="Remote calibration desk")
    parser.add_argument("--db", required=True)
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--room-port", type=int, default=8101)
    args = parser.parse_args()
    with serve_desk(args.db, args.room_port, args.port) as server:
        print(server.server_port, flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
