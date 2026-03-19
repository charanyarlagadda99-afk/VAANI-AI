import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("vaani.triage")


def get_client():
    """Get current triage client from router with failover support."""
    from src.llm_router import get_router
    router = get_router()
    client, client_type, model = router.build_triage_client()
    return client, model


DISPATCH_EXTRACTION_PROMPT = """
You are an emergency data extraction system for India's 112 helpline.
Based on the conversation transcript, extract structured emergency data.

IMPORTANT: Return ONLY raw JSON. No markdown. No backticks. No explanation.
Start your response directly with {{ and end with }}

{{
  "emergency_type": "medical|accident|fire|crime|disaster|other",
  "severity": 1,
  "location": "exact location string or null",
  "people_affected": null,
  "caller_condition": "safe|injured|trapped|panicking|unknown",
  "specific_details": "key details in 1-2 sentences",
  "language_used": "hindi|english|hinglish|tamil|telugu|bengali|marathi|other",
  "first_aid_given": false,
  "dispatch_priority": "immediate|high|medium|low",
  "recommended_responders": ["ambulance", "police", "fire", "ndrf"],
  "follow_up_required": false,
  "call_duration_seconds": 0,
  "triage_complete": false
}}

Severity guide:
1 = minor, no immediate danger
2 = non-urgent, needs attention
3 = urgent, stable condition
4 = critical, time-sensitive
5 = life-threatening, immediate response

Location extraction rules:
- Extract ANY location mentioned — even vague ones like "near railway station"
- If caller says "near X" extract "near X, [city if mentioned]"
- If caller gives street name, extract it fully
- If no location mentioned at all, return null

Conversation transcript:
{transcript}
"""


@dataclass
class TriageData:
    """Structured emergency data extracted from call."""
    emergency_type: str = "unknown"
    severity: int = 0
    location: Optional[str] = None
    people_affected: Optional[int] = None
    caller_condition: str = "unknown"
    specific_details: str = ""
    language_used: str = "unknown"
    first_aid_given: bool = False
    dispatch_priority: str = "medium"
    recommended_responders: list = field(default_factory=list)
    follow_up_required: bool = False
    call_duration_seconds: int = 0
    triage_complete: bool = False
    caller_name: Optional[str] = None
    caller_phone: Optional[str] = None
    emotional_states: list = field(default_factory=list)
    timestamps: dict = field(default_factory=dict)

    def is_complete(self) -> bool:
        """
        Complete when we have emergency type and severity.
        Location may still be vague — brief saves regardless.
        """
        return all([
            self.emergency_type != "unknown",
            self.severity > 0,
        ])

    def has_precise_location(self) -> bool:
        """
        Relaxed location check.
        Accepts any location that has a recognizable name or area.
        Only rejects completely empty or single generic word locations.
        """
        if not self.location:
            return False

        location = self.location.strip()

        # Too short to be real
        if len(location) < 5:
            return False

        # Completely generic — no name attached
        purely_vague = [
            "here", "there", "outside", "inside",
            "this place", "that place", "somewhere",
            "nearby", "close"
        ]
        if location.lower() in purely_vague:
            return False

        # Has a landmark or road name with context — accept it
        # "near MG Road" is acceptable
        # "near railway station Bangalore" is acceptable
        # "100 meters from Koramangala" is acceptable
        has_name = any(
            len(word) > 3 and word[0].isupper()
            for word in location.split()
        )

        # Has a city or area mentioned
        has_area = len(location.split()) >= 2

        return has_name or has_area

    def get_location_feedback(self) -> str:
        """
        Return what kind of location clarification is needed.
        Used by agent to give specific follow-up.
        """
        if not self.location:
            return "no_location"

        location_lower = self.location.lower()

        if any(w in location_lower for w in ["railway station", "station"]):
            return "needs_station_name"
        if any(w in location_lower for w in ["main road", "highway", "road"]):
            return "needs_road_name"
        if any(w in location_lower for w in ["near", "next to", "beside", "opposite"]):
            return "needs_area_name"
        if any(w in location_lower for w in ["temple", "school", "hospital", "college"]):
            return "needs_landmark_name"

        return "acceptable"

    def to_dict(self) -> dict:
        return asdict(self)

    def severity_label(self) -> str:
        labels = {
            1: "MINOR",
            2: "LOW",
            3: "MODERATE",
            4: "HIGH",
            5: "CRITICAL"
        }
        return labels.get(self.severity, "UNKNOWN")

    def priority_color(self) -> str:
        colors = {
            "immediate": "🔴",
            "high":      "🟠",
            "medium":    "🟡",
            "low":       "🟢"
        }
        return colors.get(self.dispatch_priority, "⚪")


class TriageSession:
    """Manages a single emergency call triage session."""

    def __init__(self, call_id: str):
        self.call_id = call_id
        self.data = TriageData()
        self.transcript: list[dict] = []
        self.start_time = time.time()
        self.language = "english"
        self.caller_states: list[str] = []
        self.extraction_attempts = 0
        self.calming_index = 0
        logger.info(f"Triage session started: {call_id}")

    def add_transcript(self, role: str, content: str):
        """Add a message to the call transcript."""
        self.transcript.append({
            "role": role,
            "content": content,
            "timestamp": time.time() - self.start_time
        })

    def add_caller_state(self, state: str):
        """Track emotional state changes throughout the call."""
        self.caller_states.append({
            "state": state,
            "timestamp": time.time() - self.start_time
        })
        self.data.emotional_states = self.caller_states

    def get_transcript_text(self) -> str:
        """Get formatted transcript for LLM extraction."""
        lines = []
        for entry in self.transcript:
            role = "VAANI" if entry["role"] == "assistant" else "CALLER"
            lines.append(f"{role}: {entry['content']}")
        return "\n".join(lines)

    def get_duration(self) -> int:
        """Get call duration in seconds."""
        return int(time.time() - self.start_time)

    async def extract_triage_data(self) -> TriageData:
        self.extraction_attempts += 1
        transcript_text = self.get_transcript_text()
        if not transcript_text:
            return self.data

        from src.llm_router import get_router
        router = get_router()

        # Try up to 3 providers
        for attempt in range(len(router.providers)):
            try:
                client, model = get_client()
                prompt = DISPATCH_EXTRACTION_PROMPT.format(transcript=transcript_text)

                response = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=600,
                    temperature=0,
                    response_format={"type": "json_object"},
                )

                raw = response.choices[0].message.content.strip()

                # Strip markdown backticks
                if raw.startswith("```"):
                    parts = raw.split("```")
                    if len(parts) >= 2:
                        raw = parts[1]
                        if raw.startswith("json"):
                            raw = raw[4:]
                raw = raw.strip()

                extracted = json.loads(raw)

                # Update fields
                self.data.emergency_type = extracted.get("emergency_type", self.data.emergency_type)
                self.data.severity = extracted.get("severity", self.data.severity)
                new_location = extracted.get("location")
                if new_location and new_location != "null":
                    self.data.location = new_location
                self.data.people_affected = extracted.get("people_affected", self.data.people_affected)
                self.data.caller_condition = extracted.get("caller_condition", self.data.caller_condition)
                self.data.specific_details = extracted.get("specific_details", self.data.specific_details)
                self.data.language_used = extracted.get("language_used", self.language)
                self.data.first_aid_given = extracted.get("first_aid_given", False)
                self.data.dispatch_priority = extracted.get("dispatch_priority", self.data.dispatch_priority)
                self.data.recommended_responders = extracted.get("recommended_responders", self.data.recommended_responders)
                self.data.follow_up_required = extracted.get("follow_up_required", False)
                self.data.triage_complete = extracted.get("triage_complete", False)
                self.data.call_duration_seconds = self.get_duration()

                # Auto-fill responders if empty
                if not self.data.recommended_responders:
                    auto = {
                        "medical":  ["ambulance"],
                        "accident": ["ambulance","police"],
                        "fire":     ["fire","ambulance"],
                        "crime":    ["police"],
                        "disaster": ["ndrf","ambulance","police"],
                        "other":    ["ambulance","police"]
                    }
                    self.data.recommended_responders = auto.get(
                        self.data.emergency_type, ["ambulance","police"]
                    )

                logger.info(
                    f"Triage #{self.extraction_attempts} OK | "
                    f"Provider: {router.get_current()['name']} | "
                    f"Type: {self.data.emergency_type} | "
                    f"Sev: {self.data.severity} | "
                    f"Location: {self.data.location}"
                )
                return self.data

            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "rate_limit" in err_str or "quota" in err_str:
                    logger.warning(f"Rate limit on {router.get_current()['name']} — failing over")
                    router.failover()
                    continue
                else:
                    logger.error(f"Triage extraction error: {e}")
                    return self.data

        logger.error("All LLM providers exhausted")
        return self.data

    def needs_location(self) -> bool:
        return not self.data.location

    def needs_precise_location(self) -> bool:
        return not self.data.has_precise_location()

    def needs_severity(self) -> bool:
        return self.data.severity == 0

    def needs_emergency_type(self) -> bool:
        return self.data.emergency_type == "unknown"

    def is_high_priority(self) -> bool:
        return (
            self.data.severity >= 4 or
            self.data.dispatch_priority in ["immediate", "high"]
        )

    def get_missing_fields(self) -> list:
        """Return list of critical fields still missing."""
        missing = []
        if self.needs_emergency_type():
            missing.append("emergency_type")
        if self.needs_location():
            missing.append("location")
        elif self.needs_precise_location():
            missing.append("precise_location")
        if self.needs_severity():
            missing.append("severity")
        return missing