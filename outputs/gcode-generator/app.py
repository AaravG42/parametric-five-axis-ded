"""Dependency-free localhost server for the parametric G-code generator."""

from __future__ import annotations

from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys

from generator import DEFAULTS, generate, generate_penta_preview, generate_rep5x_preview
from fibr3d_export import DEMO, generate_fibr3d
import simulation_runner


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"


class Handler(SimpleHTTPRequestHandler):
    """Serve the interface and expose one JSON generation endpoint."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - HTTP method name
        if self.path == "/api/fibr3d/preset":
            self.send_json({**DEFAULTS, **DEMO})
            return
        if self.path == "/api/fibr3d/status":
            self.send_json(simulation_runner.status())
            return
        if self.path == "/api/defaults":
            self.send_json(DEFAULTS)
            return
        if self.path == "/":
            self.path = "/simulator.html"
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - HTTP method name
        if self.path.startswith('/api/fibr3d/'):
            try:
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Use application/json.')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 <= length <= 20_000_000: raise ValueError('Request too large')
                data = json.loads(self.rfile.read(length) or b'{}')
                if self.path.endswith('/generate'):
                    code = generate_fibr3d(data)
                    result = {'gcode': code, 'lines': len(code.splitlines())}
                elif self.path.endswith('/play'):
                    result = simulation_runner.start(data['gcode'])
                elif self.path.endswith('/control'):
                    result = simulation_runner.control(data['action'])
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self.send_json(result)
            except (ValueError, TypeError, KeyError, RuntimeError, OSError) as exc:
                self.send_json({'error': str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if self.path != "/api/generate":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 1_000_000:
                raise ValueError("Request is too large.")
            parameters = json.loads(self.rfile.read(length) or b"{}")
            result = generate(parameters)
            self.send_json({
                "gcode": result.gcode,
                "rep5x_gcode": generate_rep5x_preview(parameters),
                "penta_gcode": generate_penta_preview(parameters),
                "summary": result.summary(),
            })
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


def main() -> None:
    host = "127.0.0.1"
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Parametric G-code Generator: http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
