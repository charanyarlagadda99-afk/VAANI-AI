import json
import logging
import os
from datetime import datetime

logger = logging.getLogger("vaani.session")


class CallLogger:
    """Logs complete call sessions for audit and analytics."""

    def __init__(self, call_id: str, logs_dir: str = "logs"):
        self.call_id = call_id
        self.logs_dir = logs_dir
        self.session_data = {
            "call_id": call_id,
            "started_at": datetime.now().isoformat(),
            "ended_at": None,
            "transcript": [],
            "triage_data": None,
            "dispatch_brief": None,
            "events": [],
            "language_switches": [],
            "caller_states": [],
        }
        os.makedirs(logs_dir, exist_ok=True)
        logger.info(f"Call logger initialized: {call_id}")

    def log_event(self, event: str, details: dict = None):
        """Log a significant event during the call."""
        self.session_data["events"].append({
            "event": event,
            "timestamp": datetime.now().isoformat(),
            "details": details or {}
        })

    def log_transcript(self, role: str, content: str):
        """Add transcript entry."""
        self.session_data["transcript"].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })

    def log_language_switch(self, from_lang: str, to_lang: str):
        """Log a language switch during the call."""
        self.session_data["language_switches"].append({
            "from": from_lang,
            "to": to_lang,
            "timestamp": datetime.now().isoformat()
        })
        logger.info(f"Language switch: {from_lang} → {to_lang}")

    def log_caller_state(self, state: str):
        """Log caller emotional state."""
        self.session_data["caller_states"].append({
            "state": state,
            "timestamp": datetime.now().isoformat()
        })

    def finalize(self, triage_data: dict = None, dispatch_brief: dict = None):
        """Finalize and save the session log."""
        self.session_data["ended_at"] = datetime.now().isoformat()
        self.session_data["triage_data"] = triage_data
        self.session_data["dispatch_brief"] = dispatch_brief

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(
            self.logs_dir,
            f"{self.call_id}_{timestamp}_session.json"
        )

        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(self.session_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Session log saved: {log_path}")
        return log_path