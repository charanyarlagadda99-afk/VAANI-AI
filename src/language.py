import logging
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("vaani.language")

# Murf Falcon voice IDs per language
# en-IN-ananya handles English, Hinglish, and code-mixing natively
LANGUAGE_CONFIG = {
    "english": {
        "voice": "en-IN-isha",
        "style": "Conversational",
        "deepgram_language": "en-IN",
        "label": "English",
        "instruction": "Respond in clear simple English only. Maximum 2 short sentences."
    },
    "hindi": {
        "voice": "hi-IN-Aman",
        "style": "Conversational",
        "deepgram_language": "hi",
        "label": "Hindi",
        "instruction": "Respond in simple Hindi only. Short sentences. Example: 'Aap kahan hain? Madad aa rahi hai abhi.' Maximum 2 sentences."
    },
    "hinglish": {
        "voice": "hi-IN-Aman",
        "style": "Conversational",
        "deepgram_language": "hi",
        "label": "Hinglish",
        "instruction": "Respond in natural Hinglish — mix Hindi and English. Example: 'Aap safe hain. Help aa rahi hai. Where exactly are you?' Maximum 2 sentences."
    },
    "tamil": {
        "voice": "ta-IN-iniya",
        "style": "Conversational",
        "deepgram_language": "ta",
        "label": "Tamil",
        "instruction": "Respond in simple Tamil mixed with essential English. Maximum 2 sentences."
    },
    "bengali": {
        "voice": "bn-IN-anwesha",
        "style": "Conversational",
        "deepgram_language": "bn",
        "label": "Bengali",
        "instruction": "Respond in simple Bengali mixed with English. Maximum 2 sentences."
    },
    "telugu": {
        "voice": "te-IN-Josie",
        "style": "Conversational",
        "deepgram_language": "te",
        "label": "Telugu",
        "instruction": "Respond naturally in Telugu. Use clear simple Telugu sentences. Maximum 2 sentences."
   },
    "marathi": {
        "voice": "mr-IN-rujuta",
        "style": "Conversational",
        "deepgram_language": "mr",
        "label": "Marathi",
        "instruction": "Respond in simple Marathi mixed with English. Maximum 2 sentences."
    },
    "kannada": {
        "voice": "kn-IN-julia",
        "style": "Conversational",
        "deepgram_language": "kn",
        "label": "Kannada",
        "instruction": "Respond naturally in Kannada. Use clear simple Kannada sentences. Maximum 2 sentences."
    },
}
# Deepgram language code mapping
DEEPGRAM_LANG_MAP = {
    "en-IN": "english",
    "en-US": "english",
    "en-GB": "english",
    "en":    "english",
    "hi":    "hindi",
    "hi-IN": "hindi",
    "ta":    "tamil",
    "ta-IN": "tamil",
    "te":    "telugu",
    "te-IN": "telugu",
    "bn":    "bengali",
    "bn-IN": "bengali",
    "mr":    "marathi",
    "mr-IN": "marathi",
    "gu":    "english",
    "kn":    "english",
    "ml":    "english",
    "pa":    "hindi",
}

# Hindi word list for Hinglish detection
HINDI_WORDS = {
    "hai", "hain", "kya", "mera", "meri", "aap", "tum", "yahan",
    "wahan", "kar", "tha", "thi", "raha", "rahi", "nahi", "nahin",
    "aur", "lekin", "par", "se", "ko", "ka", "ki", "ke", "mujhe",
    "humein", "jana", "aana", "emergency", "madad", "bachao", "jaldi",
    "abhi", "kahan", "kaun", "kyun", "kaise", "bahut", "thoda", "ek",
    "do", "teen", "log", "aadmi", "aurat", "ghar", "sadak", "hospital"
}

ENGLISH_WORDS = {
    "the", "is", "are", "was", "were", "have", "has", "this", "that",
    "and", "but", "or", "my", "your", "help", "please", "need",
    "want", "going", "coming", "people", "injured", "accident", "fire",
    "police", "ambulance", "road", "near", "here", "there", "just"
}


def detect_language_from_deepgram(deepgram_lang_code: str) -> str:
    """Map Deepgram language code to our language key."""
    if not deepgram_lang_code:
        return "english"
    lang = DEEPGRAM_LANG_MAP.get(deepgram_lang_code.lower(), None)
    if lang:
        logger.info(f"Deepgram language detected: {deepgram_lang_code} → {lang}")
        return lang
    return "english"


def detect_language_from_text(text: str) -> str:
    """Detect language from text content using word matching."""
    if not text:
        return "english"

    words = set(text.lower().split())

    # Check regional languages first
    tamil_words = {"vanakkam", "enna", "epdi", "naan", "inga", "avasaram", "udavi", "parunga", "sollunga"}
    telugu_words = {"namaskaram", "ela", "undi", "nenu", "meeru", "ikkade", "sahayam", "cheyandi"}
    bengali_words = {"namaskar", "kemon", "achi", "ami", "tumi", "apni", "sahajya", "doya", "asha"}
    marathi_words = {"namaskar", "kay", "aahe", "mi", "tumhi", "ithe", "madad", "krupa", "lavkar"}

    if words & tamil_words:
        return "tamil"
    if words & telugu_words:
        return "telugu"
    if words & bengali_words:
        return "bengali"
    if words & marathi_words:
        return "marathi"

    hindi_count = len(words & HINDI_WORDS)
    english_count = len(words & ENGLISH_WORDS)

    if hindi_count > 0 and english_count > 0:
        return "hinglish"
    if hindi_count > 0:
        return "hindi"

    return "english"


def get_language_instruction(language: str) -> str:
    """Get LLM instruction for responding in detected language."""
    config = LANGUAGE_CONFIG.get(language, LANGUAGE_CONFIG["english"])
    return config["instruction"]

def get_voice_config(language: str) -> dict:
    return LANGUAGE_CONFIG.get(language, LANGUAGE_CONFIG["english"])


def get_language_instruction(language: str) -> str:
    config = LANGUAGE_CONFIG.get(language, LANGUAGE_CONFIG["english"])
    return config["instruction"]


def get_language_label(language: str) -> str:
    config = LANGUAGE_CONFIG.get(language, LANGUAGE_CONFIG["english"])
    return config["label"]


def detect_caller_state(message: str) -> str:
    text_lower = message.lower()
    scream_indicators = (
        message.count("!") >= 2 or
        (message.isupper() and len(message) > 5) or
        "!!!" in message
    )
    panic_words = [
        "help", "please", "hurry", "fast", "quick", "dying", "dead",
        "blood", "bleeding", "cant breathe", "not breathing", "unconscious",
        "jaldi", "bachao", "mar", "khoon", "saans", "emergency",
        "fire", "aag", "accident", "crash", "attack", "trapped", "stuck",
        "madad", "bachao", "koi nahi", "please help"
    ]
    panic_count = sum(1 for w in panic_words if w in text_lower)
    if scream_indicators:
        return "screaming"
    if panic_count >= 3:
        return "panicking"
    if any(w in text_lower for w in ["please", "god", "bhagwan", "save", "ro raha"]):
        return "crying"
    if panic_count >= 1:
        return "panicking"
    return "calm"