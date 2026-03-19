import logging
import os
import uuid
from dotenv import load_dotenv

# ALL plugins imported on main thread — required by LiveKit
from livekit.agents import JobContext, WorkerOptions, cli, JobProcess
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import deepgram, silero, murf
from livekit.plugins import groq


from src import language
from src.prompts import VAANI_SYSTEM_PROMPT
from src.triage import TriageSession
from src.dispatcher import DispatchBrief
from src.language import (
    detect_caller_state,
    get_language_instruction,
    get_language_label,
    get_voice_config,
)
from src.logger import CallLogger
from src.llm_router import get_router

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("vaani.main")

SUPPORTED_LANGUAGES = [
    "english", "hindi", "hinglish", "tamil",
    "telugu", "bengali", "marathi", "kannada"
]

LANGUAGE_GREETINGS = {
    "english":  "112 Emergency. What is your emergency?",
    "hindi":    "112 Emergency. Aapki kya emergency hai?",
    "hinglish": "112 Emergency. Aapki kya emergency hai? How can I help you?",
    "tamil":    "112 Emergency. Ungal avasaram enna?",
    "telugu":   "112 Emergency. Mee emergency enti?",
    "bengali":  "112 Emergency. Aapnar emergency ki?",
    "marathi":  "112 Emergency. Tumchi emergency kaay aahe?",
    "kannada":  "112 Emergency. Nimma emergency yenu?",
}

LOCATION_PUSHBACK = {
    "english": {
        "needs_station_name":  "Which railway station exactly? What is the station name and area?",
        "needs_road_name":     "What is the name of that road? Which area or district is it in?",
        "needs_area_name":     "I need the area or locality name to send help faster. Can you tell me?",
        "needs_landmark_name": "What is the full name of that landmark and which area is it in?",
        "no_location":         "I need your exact location to send help. What street or area are you in?",
    },
    "hindi": {
        "needs_station_name":  "Kaun sa railway station? Station ka naam aur area batao.",
        "needs_road_name":     "Us road ka naam kya hai? Kaun sa area ya district hai?",
        "needs_area_name":     "Jaldi madad bhejne ke liye area ya locality ka naam chahiye. Bata sakte hain?",
        "needs_landmark_name": "Us jagah ka poora naam aur area kya hai?",
        "no_location":         "Help bhejne ke liye exact location chahiye. Aap kahan hain? Street ya area batao.",
    },
    "hinglish": {
        "needs_station_name":  "Kaun sa railway station? Station name aur area bolo.",
        "needs_road_name":     "Us road ka naam kya hai? Kaun sa area hai?",
        "needs_area_name":     "Area ya locality ka naam do — faster help bhej sakte hain.",
        "needs_landmark_name": "Us landmark ka poora naam aur area kya hai?",
        "no_location":         "Exact location do — street ya area name. Help bhejni hai.",
    },
    "tamil": {
        "needs_station_name":  "Yaar railway station? Station peyar sollunga.",
        "needs_road_name":     "Antha road peyar enna? Yaar area?",
        "needs_area_name":     "Area peyar sollunga — udavi anuppuven.",
        "needs_landmark_name": "Antha idathin peyar mattrum area enna?",
        "no_location":         "Ungal location sollunga — street illa area peyar.",
    },
    "telugu": {
        "needs_station_name":  "Edi railway station? Station peru cheppandi.",
        "needs_road_name":     "Aa road peru enti? Yedi area?",
        "needs_area_name":     "Area peru cheppandi — sahayam pampistha.",
        "needs_landmark_name": "Aa landmark peru mariyu area enti?",
        "no_location":         "Location cheppandi — street leda area peru.",
    },
    "bengali": {
        "needs_station_name":  "Kono railway station? Station er naam bolun.",
        "needs_road_name":     "Sei road er naam ki? Kono area?",
        "needs_area_name":     "Area er naam bolun — taratari help pathabo.",
        "needs_landmark_name": "Sei jaygatar poora naam o area ki?",
        "no_location":         "Location bolun — street ba area naam.",
    },
    "marathi": {
        "needs_station_name":  "Konta railway station? Station che nav sanga.",
        "needs_road_name":     "Tya road che nav kay aahe? Konta area?",
        "needs_area_name":     "Area che nav sanga — lavkar madad pathavto.",
        "needs_landmark_name": "Tya jagechya poora nav ani area kay aahe?",
        "no_location":         "Location sanga — street kiva area nav.",
    },
    "kannada": {
        "needs_station_name":  "Yavdu railway station? Station hesaru heli.",
        "needs_road_name":     "Aa road hesaru yenu? Yavdu area?",
        "needs_area_name":     "Area hesaru heli — bega help kalisutta.",
        "needs_landmark_name": "Aa jaagada hesaru mattu area yenu?",
        "no_location":         "Location heli — street athava area hesaru.",
    },
}


class VAANIAgent(Agent):
    """
    VAANI — Voice Adaptive AI for National Intelligence
    India's multilingual AI emergency triage agent for 112 helpline.
    Conversation: Gemini 1.5 Flash (free, high limits)
    Triage extraction: Groq with failover
    """

    def __init__(self, language: str = "english") -> None:

        voice_cfg   = get_voice_config(language)
        lang_label  = get_language_label(language)
        lang_instr  = get_language_instruction(language)

        full_prompt = VAANI_SYSTEM_PROMPT + f"""

═══════════════════════════════════════════════════════
CALLER LANGUAGE: {lang_label.upper()}
═══════════════════════════════════════════════════════
{lang_instr}

CRITICAL LANGUAGE RULE:
Respond ONLY in {lang_label} for this ENTIRE call.
Never switch language unless caller switches first.
Maximum 2 sentences per response.
This is a voice emergency call — keep it SHORT.

CRITICAL LOCATION RULE:
NEVER accept vague locations like "near X" or "100 meters from X".
Always push back and ask for street name, area name, or locality.
Do NOT say "help is on the way" until precise location is confirmed.
"""

        # ── BUILD CONVERSATION LLM ──
        # Gemini 1.5 Flash: free tier, 15 RPM, 1500 RPD — enough for demo
        # Falls back to Groq if Gemini key not available
        router= get_router()
        llm_instance = router.build_livekit_llm()
        logger.info(f"Conversation LLM: {router.get_current()['name']}")

        super().__init__(
            instructions=full_prompt,
            stt=deepgram.STT(
                model="nova-3",
                language=voice_cfg["deepgram_language"],
                smart_format=True,
                punctuate=True,
                interim_results=False,
                filler_words=False,
            ),
            llm=llm_instance,
            tts=murf.TTS(
                voice=voice_cfg["voice"],
                style=voice_cfg["style"],
                
            ),
        )

        self.language               = language
        self.message_count          = 0
        self.extraction_interval    = 3
        self.location_pushback_count = 0
        self.brief_saved            = False
        self._triage                = None
        self._call_logger           = None

        logger.info(
            f"VAANI initialized | "
            f"Language: {language} ({lang_label}) | "
            f"Voice: {voice_cfg['voice']} | "
            f"STT: {voice_cfg['deepgram_language']}"
        )

    def setup(self, triage: TriageSession, call_logger: CallLogger):
        """Inject triage session and logger after init."""
        self._triage      = triage
        self._call_logger = call_logger

    async def on_enter(self):
        """Called when agent joins room — greet in selected language."""
        self._call_logger.log_event("agent_joined", {"language": self.language})

        greeting = LANGUAGE_GREETINGS.get(
            self.language,
            LANGUAGE_GREETINGS["english"]
        )

        self._triage.add_transcript("assistant", greeting)
        self._call_logger.log_transcript("assistant", greeting)
        await self.session.say(greeting)
        logger.info(f"VAANI greeted in {self.language}: {greeting}")

    async def on_user_turn_completed(self, turn_ctx, new_message):
        """
        Called after every caller message.
        1. Extract text safely
        2. Inject language reminder into LLM context
        3. Detect caller emotional state
        4. Run triage extraction on message 1 and every 3rd message
        5. Inject location pushback when needed
        6. Call super to generate VAANI response
        """
        self.message_count += 1

        # ── EXTRACT TEXT FROM MESSAGE ──
        user_text = ""
        if hasattr(new_message, "content"):
            if isinstance(new_message.content, str):
                user_text = new_message.content
            elif isinstance(new_message.content, list):
                for item in new_message.content:
                    if hasattr(item, "text"):
                        user_text += item.text
                    elif isinstance(item, str):
                        user_text += item
        else:
            user_text = str(new_message)

        if not user_text.strip():
            await super().on_user_turn_completed(turn_ctx, new_message)
            return

        logger.info(
            f"Message #{self.message_count} "
            f"[{self.language}]: {user_text[:100]}"
        )

        self._triage.add_transcript("user", user_text)
        self._call_logger.log_transcript("user", user_text)

        # ── INJECT LANGUAGE REMINDER ──
        lang_label = get_language_label(self.language)
        lang_instr = get_language_instruction(self.language)
        try:
            turn_ctx.add_message(
                role="system",
                content=(
                    f"REMINDER: Respond ONLY in {lang_label}. "
                    f"{lang_instr} "
                    f"Maximum 2 short sentences."
                )
            )
        except Exception as e:
            logger.warning(f"Language reminder inject failed: {e}")

        # ── CALLER STATE DETECTION ──
        try:
            caller_state = detect_caller_state(user_text)
            self._triage.add_caller_state(caller_state)
            self._call_logger.log_caller_state(caller_state)
            logger.info(f"Caller state: {caller_state}")

            if caller_state in ["panicking", "screaming", "crying"]:
                self._call_logger.log_event("high_distress_detected", {
                    "state":         caller_state,
                    "message_count": self.message_count,
                })
                logger.warning(f"High distress: {caller_state}")
                try:
                    turn_ctx.add_message(
                        role="system",
                        content=(
                            f"ALERT: Caller is {caller_state}. "
                            f"Slow down. Acknowledge briefly in {lang_label}. "
                            f"Then ask for location."
                        )
                    )
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"State detection error: {e}")

        # ── TRIAGE EXTRACTION ──
        if self.message_count == 1 or self.message_count % self.extraction_interval == 0:
            await self._run_triage_extraction(turn_ctx)

        # ── CALL SUPER (generate VAANI response) ──
        try:
            await super().on_user_turn_completed(turn_ctx, new_message)
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "rate_limit" in err_str or "quota" in err_str:
                router  = get_router()
                old_name = router.get_current()["name"]
                router.failover()
                new_name = router.get_current()["name"]
                logger.warning(f"LLM failover: {old_name} → {new_name}")
                self._call_logger.log_event("llm_failover", {
                    "from":          old_name,
                    "to":            new_name,
                    "message_count": self.message_count,
                })
            else:
                logger.error(f"LLM response error: {e}")

    async def _run_triage_extraction(self, turn_ctx=None):
        """
        Extract structured triage data from transcript.
        Save dispatch brief as soon as emergency type and severity are known.
        Inject location pushback into LLM context when location is vague.
        """
        try:
            logger.info(f"Triage extraction at message #{self.message_count}")
            triage_data = await self._triage.extract_triage_data()

            # ── SAVE BRIEF AS SOON AS POSSIBLE ──
            if triage_data.emergency_type != "unknown" and triage_data.severity > 0:
                brief = DispatchBrief(triage_data, self._triage.call_id)
                text_path, json_path = brief.save_to_file()
                logger.info(f"Brief saved: {text_path}")
                logger.info(f"SMS: {brief.get_sms_alert()}")

                if not self.brief_saved:
                    self.brief_saved = True
                    self._call_logger.log_event("brief_generated", {
                        "emergency_type": triage_data.emergency_type,
                        "severity":       triage_data.severity,
                        "location":       triage_data.location,
                        "precise":        triage_data.has_precise_location(),
                    })

                if triage_data.is_complete():
                    logger.info(
                        f"TRIAGE COMPLETE | "
                        f"Type: {triage_data.emergency_type} | "
                        f"Sev: {triage_data.severity}/5 | "
                        f"Location: {triage_data.location} | "
                        f"Precise: {triage_data.has_precise_location()} | "
                        f"Priority: {triage_data.dispatch_priority} | "
                        f"Responders: {triage_data.recommended_responders}"
                    )
                    self._call_logger.log_event("triage_complete", {
                        "emergency_type":  triage_data.emergency_type,
                        "severity":        triage_data.severity,
                        "location":        triage_data.location,
                        "precise":         triage_data.has_precise_location(),
                        "responders":      triage_data.recommended_responders,
                        "priority":        triage_data.dispatch_priority,
                    })
                    print("\n" + brief.generate_text_brief())

            # ── LOCATION PUSHBACK ──
            if turn_ctx and self.location_pushback_count < 2:
                location_feedback = triage_data.get_location_feedback()

                if (
                    location_feedback != "acceptable"
                    and not triage_data.has_precise_location()
                ):
                    self.location_pushback_count += 1
                    pushbacks    = LOCATION_PUSHBACK.get(
                        self.language,
                        LOCATION_PUSHBACK["english"]
                    )
                    pushback_msg = pushbacks.get(
                        location_feedback,
                        pushbacks["needs_area_name"]
                    )
                    lang_label   = get_language_label(self.language)

                    try:
                        turn_ctx.add_message(
                            role="system",
                            content=(
                                f"LOCATION NOT PRECISE. "
                                f"Attempt {self.location_pushback_count}/3. "
                                f"Say in {lang_label}: '{pushback_msg}' "
                                f"Do NOT confirm dispatch yet."
                            )
                        )
                        logger.info(
                            f"Location pushback #{self.location_pushback_count} | "
                            f"Type: {location_feedback} | "
                            f"Current: {triage_data.location}"
                        )
                    except Exception as e:
                        logger.warning(f"Pushback inject failed: {e}")

                elif triage_data.has_precise_location():
                    self.location_pushback_count = 0
                    logger.info(f"Precise location confirmed: {triage_data.location}")

            # Log missing fields
            missing = self._triage.get_missing_fields()
            if missing:
                logger.info(f"Still missing: {missing}")

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "rate_limit" in err_str:
                router = get_router()
                router.failover()
                logger.warning(
                    f"Triage LLM failover → {router.get_current()['name']}"
                )
            else:
                logger.error(f"Triage extraction error: {e}")

    async def on_leave(self):
        """Called when call ends — final extraction, save all logs."""
        try:
            logger.info("Call ending — final triage extraction")
            await self._run_triage_extraction()

            final_data = self._triage.data
            brief      = DispatchBrief(final_data, self._triage.call_id)
            brief_json = brief.generate_json_brief()

            self._call_logger.log_event("call_ended", {
                "duration":        self._triage.get_duration(),
                "messages":        self.message_count,
                "language":        self.language,
                "triage_complete": final_data.triage_complete,
                "emergency_type":  final_data.emergency_type,
                "severity":        final_data.severity,
                "location":        final_data.location,
                "precise":         final_data.has_precise_location(),
                "priority":        final_data.dispatch_priority,
                "responders":      final_data.recommended_responders,
                "brief_saved":     self.brief_saved,
            })

            log_path = self._call_logger.finalize(
                triage_data=final_data.to_dict(),
                dispatch_brief=brief_json,
            )

            logger.info(f"Session saved: {log_path}")
            logger.info(
                f"CALL SUMMARY | "
                f"ID: {self._triage.call_id} | "
                f"Duration: {self._triage.get_duration()}s | "
                f"Messages: {self.message_count} | "
                f"Language: {self.language} | "
                f"Emergency: {final_data.emergency_type} | "
                f"Severity: {final_data.severity}/5 | "
                f"Location: {final_data.location} | "
                f"Priority: {final_data.dispatch_priority}"
            )

        except Exception as e:
            logger.error(f"Cleanup error: {e}")


async def entrypoint(ctx: JobContext):
    """
    Entry point for each incoming emergency call.
    Language read from room name: emergency-{language}-{uuid}
    """
    call_id = f"VAANI-{str(uuid.uuid4())[:8].upper()}"

    # Extract language from room name
    room_name = ctx.room.name
    language  = "english"
    try:
        parts = room_name.split("-")
        if len(parts) >= 2:
            lang_candidate = parts[1].lower()
            if lang_candidate in SUPPORTED_LANGUAGES:
                language = lang_candidate
    except Exception as e:
        logger.warning(f"Could not parse language from room: {e}")

    logger.info(
        f"Incoming call | "
        f"ID: {call_id} | "
        f"Room: {room_name} | "
        f"Language: {language}"
    )

    triage      = TriageSession(call_id)
    triage.language = language

    call_logger = CallLogger(call_id)
    call_logger.log_event("call_connected", {
        "room":     room_name,
        "language": language,
        "call_id":  call_id,
    })

    await ctx.connect()

    vad = ctx.proc.userdata.get("vad")

    agent = VAANIAgent(language=language)
    agent.setup(triage=triage, call_logger=call_logger)

    session = AgentSession(
        vad=vad,
        allow_interruptions=False,
        min_endpointing_delay=1.0,
    )

    await session.start(
        agent=agent,
        room=ctx.room
    )


def prewarm(proc: JobProcess):
    """Preload VAD model before calls arrive — zero latency on first call."""
    logger.info("Prewarming VAD model...")
    proc.userdata["vad"] = silero.VAD.load()
    logger.info("VAD model ready")


if __name__ == "__main__":
    logger.info("Starting VAANI — 112 Emergency Voice AI")
    logger.info("=" * 50)

    # Log available LLM providers
    router = get_router()
    logger.info(f"LLM providers: {len(router.providers)}")
    for i, p in enumerate(router.providers):
        logger.info(f"  {i+1}. {p['name']}")

    router= get_router()
    llm_instance = router.build_livekit_llm_for_language(language)

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        )
    )