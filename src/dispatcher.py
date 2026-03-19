import json
import logging
import os
from datetime import datetime
from src.triage import TriageData

logger = logging.getLogger("vaani.dispatcher")


class DispatchBrief:
    """Generates and formats dispatch briefs for emergency responders."""

    def __init__(self, triage_data: TriageData, call_id: str):
        self.data = triage_data
        self.call_id = call_id
        self.generated_at = datetime.now()

    def generate_text_brief(self) -> str:
        """Generate a human-readable dispatch brief."""
        responders = ", ".join(self.data.recommended_responders).upper() if self.data.recommended_responders else "ALL UNITS"

        brief = f"""
╔══════════════════════════════════════════════════════╗
║              VAANI EMERGENCY DISPATCH BRIEF           ║
╚══════════════════════════════════════════════════════╝

CALL ID       : {self.call_id}
GENERATED AT  : {self.generated_at.strftime("%Y-%m-%d %H:%M:%S")}
PRIORITY      : {self.data.priority_color()} {self.data.dispatch_priority.upper()}

──────────────────────────────────────────────────────
EMERGENCY DETAILS
──────────────────────────────────────────────────────
TYPE          : {self.data.emergency_type.upper()}
SEVERITY      : {self.data.severity}/5 — {self.data.severity_label()}
LOCATION      : {self.data.location or "⚠️  NOT CONFIRMED — CALL BACK REQUIRED"}
PEOPLE        : {self.data.people_affected or "Unknown"}
CALLER STATE  : {self.data.caller_condition.upper()}

──────────────────────────────────────────────────────
SITUATION SUMMARY
──────────────────────────────────────────────────────
{self.data.specific_details or "No additional details extracted."}

──────────────────────────────────────────────────────
DISPATCH INSTRUCTIONS
──────────────────────────────────────────────────────
RESPOND UNITS : {responders}
FIRST AID     : {"Given by VAANI during call" if self.data.first_aid_given else "Not administered"}
FOLLOW UP     : {"⚠️  Required" if self.data.follow_up_required else "Not required"}
CALL DURATION : {self.data.call_duration_seconds}s
LANGUAGE      : {self.data.language_used.upper()}
TRIAGE STATUS : {"✅ Complete" if self.data.triage_complete else "⚠️  Incomplete — verify on arrival"}

══════════════════════════════════════════════════════
"""
        return brief

    def generate_json_brief(self) -> dict:
        """Generate machine-readable JSON for dispatch systems."""
        return {
            "call_id": self.call_id,
            "generated_at": self.generated_at.isoformat(),
            "priority": self.data.dispatch_priority,
            "severity": self.data.severity,
            "severity_label": self.data.severity_label(),
            "emergency": {
                "type": self.data.emergency_type,
                "location": self.data.location,
                "people_affected": self.data.people_affected,
                "details": self.data.specific_details,
            },
            "caller": {
                "condition": self.data.caller_condition,
                "language": self.data.language_used,
                "name": self.data.caller_name,
            },
            "dispatch": {
                "recommended_responders": self.data.recommended_responders,
                "first_aid_given": self.data.first_aid_given,
                "follow_up_required": self.data.follow_up_required,
                "triage_complete": self.data.triage_complete,
            },
            "call_duration_seconds": self.data.call_duration_seconds,
        }

    def get_sms_alert(self) -> str:
        """Generate a short SMS alert for responders."""
        return (
            f"🚨 VAANI ALERT | {self.data.emergency_type.upper()} | "
            f"Severity: {self.data.severity}/5 | "
            f"Location: {self.data.location or 'UNKNOWN'} | "
            f"Priority: {self.data.dispatch_priority.upper()} | "
            f"Responders: {', '.join(self.data.recommended_responders or ['ALL'])} | "
            f"Call ID: {self.call_id}"
        )

    def save_to_file(self, logs_dir: str = "logs"):
        """Save dispatch brief to logs directory."""
        os.makedirs(logs_dir, exist_ok=True)
        timestamp = self.generated_at.strftime("%Y%m%d_%H%M%S")

        text_path = os.path.join(logs_dir, f"{self.call_id}_{timestamp}_brief.txt")
        with open(text_path, "w", encoding="utf-8") as f:
            f.write(self.generate_text_brief())

        json_path = os.path.join(logs_dir, f"{self.call_id}_{timestamp}_brief.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.generate_json_brief(), f, indent=2, ensure_ascii=False)

        logger.info(f"Dispatch brief saved: {text_path}")
        return text_path, json_path