"""Startet ABSEITS: Server an, Browser auf."""

import argparse
import threading
import webbrowser

import config
from server import serve


def main():
    ap = argparse.ArgumentParser(description=config.TITLE)
    ap.add_argument("--offline", action="store_true", help="Ollama nicht benutzen, nur Notbetrieb")
    ap.add_argument("--no-browser", action="store_true", help="Browser nicht automatisch öffnen")
    ap.add_argument("--port", type=int, default=config.PORT)
    args = ap.parse_args()
    app, httpd = serve(force_offline=args.offline, port=args.port)
    url = "http://%s:%d/" % (config.HOST, args.port)
    print("%s läuft auf %s (Strg+C beendet)" % (config.TITLE, url))
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.running = False
        httpd.server_close()


if __name__ == "__main__":
    main()
