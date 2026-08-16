import os
import json
import time
from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY env var not set (get one from Google AI Studio)")

_client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_ID = os.environ.get("GEMINI_MODEL_ID", "gemini-3.7-flash")

SYSTEM_PROMPT = """..."""  # unchanged


def _history_to_contents(history):
    contents = []
    for turn in history or []:
        role = "user" if turn.get("role") == "user" else "model"
        text = turn.get("content", "")
        if text:
            contents.append(types.Content(role=role, parts=[types.Part(text=text)]))
    return contents


def _call_gemini_with_retry(contents, max_attempts=3):
    """Gemini's own SDK retries on 503s internally via tenacity, but under
    sustained high demand it can still exhaust those and raise. Add one more
    layer with a short backoff before giving up and falling back to the
    friendly error the user sees."""
    last_err = None
    for attempt in range(max_attempts):
        try:
            return _client.models.generate_content(
                model=MODEL_ID,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    temperature=0.4,
                ),
            )
        except genai_errors.ServerError as e:
            last_err = e
            if attempt < max_attempts - 1:
                time.sleep(1.5 * (attempt + 1))  # 1.5s, 3s
                continue
            raise
    raise last_err


def get_legal_ai_reply(history, message):
    contents = _history_to_contents(history)
    contents.append(types.Content(role="user", parts=[types.Part(text=message)]))

    try:
        response = _call_gemini_with_retry(contents)
    except genai_errors.ServerError:
        return {
            "type": "answer",
            "reply": "The AI service is under heavy load right now — please try sending that again in a few seconds.",
            "category": None,
            "summary": None,
            "strength": None,
        }

    raw = (response.text or "").strip()
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        data = {
            "type": "answer",
            "reply": raw or "Sorry, could you rephrase your issue?",
        }

    data.setdefault("type", "answer")
    data.setdefault("reply", "")
    data.setdefault("category", None)
    data.setdefault("summary", None)
    data.setdefault("strength", None)
    return data