import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("MURF_API_KEY")

response = requests.get(
    "https://api.murf.ai/v1/speech/voices?model=FALCON",
    headers={"api-key": API_KEY}
)

print(f"Status: {response.status_code}")
voices = response.json()

indian_locales = ["hi-IN", "ta-IN", "te-IN", "bn-IN", "mr-IN", "kn-IN", "en-IN"]

print("\n=== MURF FALCON VOICES — INDIAN LANGUAGES ===\n")

if isinstance(voices, list):
    for voice in voices:
        locale = voice.get("locale", "")
        if any(loc in locale for loc in indian_locales):
            print(f"Voice ID : {voice.get('voiceId')}")
            print(f"Name     : {voice.get('displayName')}")
            print(f"Locale   : {locale}")
            print(f"Gender   : {voice.get('gender')}")
            print(f"Styles   : {voice.get('availableStyles')}")
            print("-" * 40)
    print(f"\nTotal Falcon voices found: {len(voices)}")
else:
    print("Raw response:")
    print(voices)