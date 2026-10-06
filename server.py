"""Kleiner lokaler Webserver: liefert die Oberfläche und den Spielstand."""

import json
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import config
from engine import Game
from referee import Referee

STATIC = Path(__file__).resolve().parent / "static"


class App:
    def __init__(self, force_offline=False):
        self.referee = Referee(force_offline=force_offline)
        self.game = Game(referee=self.referee)
        self.running = True

    def loop(self):
        last = time.time()
        while self.running:
            now = time.time()
            dt = min(0.1, now - last)
            last = now
            try:
                self.game.step(dt)
            except Exception as exc:  # ein Fehler darf das Spiel nicht beenden
                print("Fehler in der Spielschleife:", repr(exc))
            time.sleep(1 / 30)

    def new_game(self):
        with self.game.lock:
            self.game.new_match()


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/api/state":
                since = int(parse_qs(url.query).get("since", ["0"])[0] or 0)
                self._json(app.game.snapshot(since))
                return
            path = "index.html" if url.path in ("/", "") else url.path.lstrip("/")
            if path.startswith("static/"):
                path = path[len("static/"):]
            target = (STATIC / path).resolve()
            if STATIC.resolve() not in target.parents and target != STATIC.resolve():
                self._send(404, b"nicht gefunden", "text/plain")
                return
            if not target.is_file():
                self._send(404, b"nicht gefunden", "text/plain")
                return
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            self._send(200, target.read_bytes(), ctype)

        def do_POST(self):
            url = urlparse(self.path)
            try:
                length = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(min(length, 10000)) or b"{}")
            except Exception:
                self._json({"ok": False, "error": "Kaputte Anfrage."}, 400)
                return
            if url.path == "/api/act":
                res = app.game.act(str(data.get("type", "")), data.get("text", ""), data.get("amount", 0))
                self._json(res)
            elif url.path == "/api/new":
                app.new_game()
                self._json({"ok": True})
            else:
                self._json({"ok": False, "error": "Unbekannt."}, 404)

    return Handler


def serve(force_offline=False, host=None, port=None):
    app = App(force_offline=force_offline)
    threading.Thread(target=app.loop, daemon=True).start()
    httpd = ThreadingHTTPServer((host or config.HOST, port or config.PORT), make_handler(app))
    return app, httpd
