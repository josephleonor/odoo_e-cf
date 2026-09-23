"""Isolated deterministic DGII flow simulator. Never accepts real e-CF XML."""
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

DOCUMENTS = {}


def receive(data):
    if data.get("type") not in ("31", "32", "34") or not str(data.get("encf", "")).startswith("E" + str(data.get("type", ""))):
        raise ValueError("type/encf mismatch")
    if not data.get("issuer_rnc") or not data.get("lines"):
        raise ValueError("missing issuer or lines")
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False)
    track = hashlib.sha256(canonical.encode()).hexdigest()[:24]
    DOCUMENTS.setdefault(track, {"state": "processing", "checks": 0, "encf": data["encf"]})
    return {"track_id": track, "state": "received"}


def status(track):
    if track not in DOCUMENTS:
        raise KeyError(track)
    item = DOCUMENTS[track]
    item["checks"] += 1
    if item["checks"] >= 2:
        item["state"] = "accepted"
    return {"track_id": track, "state": item["state"], "encf": item["encf"]}


class Handler(BaseHTTPRequestHandler):
    def respond(self, code, data):
        raw = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        if self.path != "/receive":
            return self.respond(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 65536:
                return self.respond(413, {"error": "too large"})
            data = json.loads(self.rfile.read(length))
            return self.respond(200, receive(data))
        except (ValueError, TypeError) as exc:
            return self.respond(400, {"error": str(exc)})

    def do_GET(self):
        if self.path == "/health":
            return self.respond(200, {"status": "ok", "mode": "simulation"})
        if self.path.startswith("/status/"):
            try:
                return self.respond(200, status(unquote(self.path[8:])))
            except KeyError:
                return self.respond(404, {"error": "unknown track"})
        return self.respond(404, {"error": "not found"})


if __name__ == "__main__":
    print("Simulation only: http://127.0.0.1:8765", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
