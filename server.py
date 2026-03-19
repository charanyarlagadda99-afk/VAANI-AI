import os
import uuid
import json
import logging
import glob
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
import jwt
import time

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vaani.server")

LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")
LIVEKIT_URL = os.getenv("LIVEKIT_URL")

SUPPORTED_LANGUAGES = [
    "english", "hindi", "hinglish", "tamil",
    "telugu", "bengali", "marathi", "kannada"
]


def generate_token(room: str, identity: str) -> str:
    now = int(time.time())
    payload = {
        "iss": LIVEKIT_API_KEY,
        "sub": identity,
        "iat": now,
        "exp": now + 3600,
        "name": "Emergency Caller",
        "video": {
            "roomJoin": True,
            "room": room,
            "canPublish": True,
            "canSubscribe": True,
        }
    }
    return jwt.encode(payload, LIVEKIT_API_SECRET, algorithm="HS256")


def get_latest_briefs(limit: int = 10) -> list:
    """Read latest dispatch briefs from logs directory."""
    try:
        logs_dir = os.path.join(os.path.dirname(__file__), "logs")
        json_files = glob.glob(os.path.join(logs_dir, "*_brief.json"))
        json_files.sort(key=os.path.getmtime, reverse=True)

        briefs = []
        for f in json_files[:limit]:
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    data["_file"] = os.path.basename(f)
                    data["_modified"] = os.path.getmtime(f)
                    briefs.append(data)
            except Exception:
                continue
        return briefs
    except Exception as e:
        logger.error(f"Error reading briefs: {e}")
        return []


def get_latest_sessions(limit: int = 10) -> list:
    """Read latest session logs."""
    try:
        logs_dir = os.path.join(os.path.dirname(__file__), "logs")
        session_files = glob.glob(os.path.join(logs_dir, "*_session.json"))
        session_files.sort(key=os.path.getmtime, reverse=True)

        sessions = []
        for f in session_files[:limit]:
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    data["_file"] = os.path.basename(f)
                    sessions.append(data)
            except Exception:
                continue
        return sessions
    except Exception as e:
        logger.error(f"Error reading sessions: {e}")
        return []


class TokenHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)

        # ── TOKEN ENDPOINT ──
        if parsed.path == "/token":
            params = parse_qs(parsed.query)
            language = params.get("language", ["english"])[0]
            if language not in SUPPORTED_LANGUAGES:
                language = "english"

            room = f"emergency-{language}-{str(uuid.uuid4())[:6]}"
            identity = f"caller-{str(uuid.uuid4())[:6]}"

            try:
                token = generate_token(room, identity)
                response = json.dumps({
                    "token": token,
                    "room": room,
                    "livekit_url": LIVEKIT_URL,
                    "identity": identity,
                    "language": language,
                })
                self._send_json(200, response)
                logger.info(f"Token issued | Room: {room} | Language: {language}")
            except Exception as e:
                logger.error(f"Token error: {e}")
                self._send_json(500, json.dumps({"error": str(e)}))

        # ── HEALTH ENDPOINT ──
        elif parsed.path == "/health":
            self._send_json(200, json.dumps({
                "status": "VAANI server running",
                "timestamp": time.time(),
            }))

        # ── LATEST BRIEFS ENDPOINT ──
        elif parsed.path == "/briefs":
            params = parse_qs(parsed.query)
            limit = int(params.get("limit", [10])[0])
            briefs = get_latest_briefs(limit)
            self._send_json(200, json.dumps(briefs))

        # ── LATEST SESSIONS ENDPOINT ──
        elif parsed.path == "/sessions":
            params = parse_qs(parsed.query)
            limit = int(params.get("limit", [10])[0])
            sessions = get_latest_sessions(limit)
            self._send_json(200, json.dumps(sessions))

        # ── STATS ENDPOINT ──
        elif parsed.path == "/stats":
            briefs = get_latest_briefs(100)
            sessions = get_latest_sessions(100)

            emergency_types = {}
            severities = []
            languages = {}
            priorities = {}

            for b in briefs:
                etype = b.get("emergency", {}).get("type", "unknown")
                emergency_types[etype] = emergency_types.get(etype, 0) + 1

                sev = b.get("severity", 0)
                if sev:
                    severities.append(sev)

                lang = b.get("caller", {}).get("language", "unknown")
                languages[lang] = languages.get(lang, 0) + 1

                pri = b.get("priority", "unknown")
                priorities[pri] = priorities.get(pri, 0) + 1

            stats = {
                "total_calls": len(sessions),
                "total_briefs": len(briefs),
                "emergency_types": emergency_types,
                "avg_severity": round(sum(severities) / len(severities), 1) if severities else 0,
                "languages": languages,
                "priorities": priorities,
            }
            self._send_json(200, json.dumps(stats))

        else:
            self.send_response(404)
            self.end_headers()

    def _send_json(self, code: int, body: str):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer(("localhost", 8080), TokenHandler)
    logger.info("VAANI Token Server running on http://localhost:8080")
    logger.info(f"LiveKit URL: {LIVEKIT_URL}")
    server.serve_forever()