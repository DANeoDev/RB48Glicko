import base64
import json
import os
import re
import urllib.error
import urllib.request

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.5-flash-lite"
MAX_IMAGE_BYTES = 10 * 1024 * 1024

class MatchParserError(RuntimeError):
    pass


def _extract_output_text(response_data):
    texts = []
    for candidate in response_data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if part.get("text"):
                texts.append(part["text"])
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
    raise MatchParserError("The match parser returned invalid JSON.")


def _call_gemini(parts, model=None):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise MatchParserError("GEMINI_API_KEY is not configured on the server.")
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "kind": {"type": "STRING", "enum": ["attendance", "match", "unknown"]},
                    "match_date": {"type": "STRING"},
                    "players": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "team_a": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "team_b": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "goals_a": {"type": "INTEGER"},
                    "goals_b": {"type": "INTEGER"}
                },
                "required": ["kind", "match_date", "players", "team_a", "team_b", "goals_a", "goals_b"]
            }
        }
    }
    request = urllib.request.Request(
        GEMINI_API_URL.format(model=model or os.environ.get("RB48_IMAGE_PARSER_MODEL", DEFAULT_MODEL)),
        data=json.dumps(payload).encode("utf-8"),
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return _parse_json(_extract_output_text(json.loads(response.read().decode("utf-8"))))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(details).get("error", {}).get("message")
        except json.JSONDecodeError:
            message = None
        raise MatchParserError(f"Match parser API error ({exc.code}): {message or 'unknown error'}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise MatchParserError("Could not reach the match parser API.") from exc


_PROMPT = """
You are extracting football match information for the RB48 database from an arbitrary user-provided message, screenshot, or photo.
Do not assume a fixed message layout. Understand the meaning of the content first, then return only the requested structured facts.

There are two useful kinds of input:
1. An attendance/availability list: people attending, but no completed result. Return kind=attendance, put every attending person in players, and leave team_a/team_b/goals empty/null.
2. A completed match report: identify the two sides, their players, and the result if present. Return kind=match, preserve the two sides in team_a and team_b, and put the numeric goals in goals_a/goals_b. Also put all detected names in players.

Identity/name rules:
- Preserve [M] exactly when it appears before a name. [M] is a verified identity marker and will be handled by the application.
- Preserve useful human detail such as `Konsti+1 (Jens)` or `Jan (Sprenger)` rather than simplifying it to `Konsti` or `Jan`.
- Do not invent names or infer missing players.
- For attendance screenshots, an entry marked `(✓)` is WAITING LIST, not attending. Exclude it even if it has an orange background. The `(✓)` marker is the primary signal.
- Dates should be YYYY-MM-DD only when unambiguous; otherwise use an empty string.
- Do not confuse scores, headings, labels, or other text with player names.
- If the content is not sufficiently recognizable as attendance or a match, use kind=unknown and extract only clearly identifiable names.

For fields that are not present, use an empty string for match_date and 0 for goals. The application will interpret these as missing values where appropriate.
Return valid JSON matching the supplied schema.
""".strip()


def parse_match_text(text, model=None):
    if not text or not text.strip():
        raise MatchParserError("The pasted text is empty.")
    return _normalize(_call_gemini([{"text": _PROMPT + "\n\nSOURCE TEXT:\n" + text.strip()}], model))


def parse_match_image(image_bytes, mime_type, model=None):
    if not image_bytes:
        raise MatchParserError("The uploaded image is empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise MatchParserError("The image is too large (maximum 10 MB).")
    if not mime_type or not mime_type.startswith("image/"):
        raise MatchParserError("Please upload an image file.")
    encoded = base64.b64encode(image_bytes).decode("ascii")
    parts = [
        {"inlineData": {"mimeType": mime_type, "data": encoded}},
        {"text": _PROMPT},
    ]
    return _normalize(_call_gemini(parts, model))


def _normalize(parsed):
    if not isinstance(parsed, dict):
        raise MatchParserError("The match parser returned an unexpected response.")
    def names(value):
        return [str(x).strip() for x in (value or []) if str(x).strip()]
    parsed["players"] = names(parsed.get("players"))
    parsed["team_a"] = names(parsed.get("team_a"))
    parsed["team_b"] = names(parsed.get("team_b"))
    if not parsed["players"]:
        parsed["players"] = parsed["team_a"] + parsed["team_b"]
    if parsed.get("match_date") == "":
        parsed["match_date"] = None
    return parsed


def normalize_player_name(name):
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
        name = normalize_player_name(raw_name)
        if not name:
            continue
        candidates = lookup.get(name.casefold(), [])
        if verified and candidates:
            for player_id in candidates:
                if player_id not in verified_ids:
                    verified_ids.append(player_id)
        elif candidates:
            conflicts.append({"name": name, "candidate_ids": candidates})
        else:
            unmatched.append({"name": name, "verified": verified})
    return verified_ids, conflicts, unmatched
