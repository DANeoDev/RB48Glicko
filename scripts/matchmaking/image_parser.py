import base64
import json
import os
import re
import urllib.error
import urllib.request

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.5-flash-lite"
MAX_IMAGE_BYTES = 10 * 1024 * 1024

class MatchImageParserError(RuntimeError):
    pass

def _extract_output_text(response_data):
    texts = []
    for candidate in response_data.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            text = part.get("text")
            if text:
                texts.append(text)
    return "\n".join(texts).strip()

def _parse_json(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    raise MatchImageParserError("The image parser returned an invalid response.")

def parse_match_image(image_bytes, mime_type, model=None):
    if not image_bytes:
        raise MatchImageParserError("The uploaded image is empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise MatchImageParserError("The image is too large (maximum 10 MB).")
    if not mime_type or not mime_type.startswith("image/"):
        raise MatchImageParserError("Please upload an image file.")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise MatchImageParserError("GEMINI_API_KEY is not configured on the server.")

    encoded = base64.b64encode(image_bytes).decode("ascii")
    prompt = """
Analyze this screenshot/photo of a football attendance/player list.

Identify ONLY people visibly marked as attending/participating and, if visible, the attendance date.

IMPORTANT:
- Preserve the [M] prefix exactly when it appears before a player name. [M] is a verified association-member identity signal.
- A player on the WAITING LIST is NOT attending. The waiting-list marker is the literal `(✓)` symbol; it may also have an orange background. Exclude every `(✓)` entry regardless of color, and use the symbol rather than color as the primary rule.
- Do not interpret scores, teams, ratings, positions, or other unrelated text.
- Do not invent names. Preserve names as shown.
- If the date is unambiguous, return YYYY-MM-DD; otherwise null.

Return ONLY valid JSON:
{"match_date":"YYYY-MM-DD" or null,"players":["[M] name 1","name 2"]}
""".strip()
    payload = {
        "contents": [{"parts": [{"inlineData": {"mimeType": mime_type, "data": encoded}}, {"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    selected_model = model or os.environ.get("RB48_IMAGE_PARSER_MODEL", DEFAULT_MODEL)
    request = urllib.request.Request(
        GEMINI_API_URL.format(model=selected_model),
        data=json.dumps(payload).encode("utf-8"),
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(details).get("error", {}).get("message")
        except json.JSONDecodeError:
            message = None
        if message:
            raise MatchImageParserError(f"Image parser API error ({exc.code}): {message}") from exc
        raise MatchImageParserError(f"Image parser API error ({exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise MatchImageParserError("Could not reach the image parser API.") from exc

    parsed = _parse_json(_extract_output_text(response_data))
    if not isinstance(parsed, dict):
        raise MatchImageParserError("The image parser returned an unexpected response.")
    players = parsed.get("players", [])
    if not isinstance(players, list):
        raise MatchImageParserError("The image parser returned an invalid player list.")
    return {"match_date": parsed.get("match_date"), "players": [str(name).strip() for name in players if str(name).strip()]}

def _normalize_detected_name(name):
    name = re.sub(r"^\s*\[M\]\s*", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s*\[M\]\s*$", "", name, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", name).strip()

def resolve_player_names(parsed_names, players):
    lookup = {}
    for player_id, player in players.items():
        for alias in player.get("aliases", []):
            lookup.setdefault(alias.strip().casefold(), []).append(player_id)
    verified_ids, conflicts, unmatched = [], [], []
    for raw_name in parsed_names:
        verified = bool(re.match(r"^\s*\[M\](?:\s|$)", raw_name, flags=re.IGNORECASE))
        name = _normalize_detected_name(raw_name)
        if not name:
            continue
        candidates = lookup.get(name.casefold(), [])
        if verified:
            if candidates:
                for player_id in candidates:
                    if player_id not in verified_ids:
                        verified_ids.append(player_id)
            else:
                unmatched.append({"name": name, "verified": True})
        elif candidates:
            conflicts.append({"name": name, "candidate_ids": candidates})
        else:
            unmatched.append({"name": name, "verified": False})
    return verified_ids, conflicts, unmatched

def normalize_player_name(name):
    return _normalize_detected_name(name)
