#!/usr/bin/env python3
"""Local dev server for the Cover Editor with a one-click 'Update ZDL' endpoint.

    python3 tools/serve_editor.py            # then open the printed URL

Serves the repo statically (so tools/cover_editor.html loads) AND handles
POST /apply_cover {name, grid} — it writes the cover override and rebuilds that
effect's .ZDL via apply_cover.apply_cover(), returning the build log as JSON.
That's what lets the editor's "Update ZDL" button do the whole job with no
terminal step. Binds to localhost only.
"""

from __future__ import annotations

import json
import sys
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import apply_cover as ac  # noqa: E402


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def log_message(self, *a):  # keep the console quiet except for builds
        pass

    def do_POST(self):
        if self.path.split("?")[0] != "/apply_cover":
            self.send_error(404)
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            name, grid = body.get("name"), body.get("grid")
            if not name or grid is None:
                res = {"ok": False, "message": "missing name/grid", "log": ""}
            else:
                print(f"[apply_cover] {name}: building …")
                res = ac.apply_cover(name, grid, build=not body.get("placeOnly"))
                print(f"[apply_cover] {name}: {res['message']}")
        except Exception as exc:  # noqa: BLE001
            res = {"ok": False, "message": f"server error: {exc}", "log": ""}
        out = json.dumps(res).encode()
        self.send_response(200 if res.get("ok") else 500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def _bind(port: int) -> ThreadingHTTPServer:
    """Bind to `port`; if it's taken, walk up to the next free one so the
    server never dies on 'Address already in use' (e.g. a stray http.server
    already sitting on 8000)."""
    want = port
    for p in range(port, port + 20):
        try:
            return ThreadingHTTPServer(("127.0.0.1", p), Handler)
        except OSError:
            continue
    raise SystemExit(f"couldn't find a free port near {want}")


def main() -> None:
    """Serve the repo and open an editor.

        python3 tools/serve_editor.py              # patch editor
        python3 tools/serve_editor.py --cover      # cover editor
        python3 tools/serve_editor.py --no-open    # just serve
        python3 tools/serve_editor.py 8100         # pick a starting port

    Opens the PATCH editor by default: it is the tool reached for most, and it
    needs a localhost origin because Web MIDI refuses to run on a file:// page.
    """
    args = sys.argv[1:]
    which = "patch"
    if "--cover" in args:
        which = "cover"
    if "--no-open" in args:
        which = None
    ports = [a for a in args if a.isdigit()]
    port = int(ports[0]) if ports else 8000

    httpd = _bind(port)
    actual = httpd.server_address[1]
    base = f"http://localhost:{actual}"
    patch_url = f"{base}/tools/patch_editor.html"
    cover_url = f"{base}/tools/cover_editor.html"

    if actual != port:
        print(f"(port {port} was busy -- using {actual})")
    print(f"Patch Editor  ->  {patch_url}")
    print(f"Cover Editor  ->  {cover_url}")
    print("   Web MIDI only works on localhost or https, so open these URLs --")
    print("   a file:// page will load but can never reach the pedal.")
    print("   'Update ZDL' in the cover editor rebuilds the effect. Ctrl-C to stop.")

    url = patch_url if which == "patch" else (cover_url if which == "cover" else None)
    if url:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
