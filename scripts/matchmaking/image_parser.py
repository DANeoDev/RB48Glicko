import base64
import json
import os
import urllib.error
import urllib.request


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.6-luna"
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class MatchImageParserError(RuntimeError):
    pass


def _extract_output_text(response_data):
    texts = []
    for item in response_data.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if text:
                texts.append(text)
    return "\n".join(texts).strip()


def _parse_json(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
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

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise MatchImageParserError("OPENAI_API_KEY is not configured on the server.")

    encoded = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{encoded}"

    prompt = """
Analyze this screenshot/photo of a football match/player list.
Extract the match date and every player name that is visibly listed as participating.
Do not invent names. Preserve names as they appear in the image as closely as possible.
If the date is visible, return it as YYYY-MM-DD when you can determine it unambiguously;
otherwise return null.

Return ONLY valid JSON with this exact shape:
{
  "match_date": "YYYY-MM-DD" or null,
  "players": ["name 1", "name 2"]
}
""".strip()

    payload = {
        "model": model or os.environ.get("RB48_IMAGE_PARSER_MODEL", DEFAULT_MODEL),
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": data_url},
            ],
        }],
    }

    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise MatchImageParserError(f"Image parser API error ({exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise MatchImageParserError("Could not reach the image parser API.") from exc

    parsed = _parse_json(_extract_output_text(response_data))
    if not isinstance(parsed, dict):
        raise MatchImageParserError("The image parser returned an unexpected response.")

    players = parsed.get("players", [])
    if not isinstance(players, list):
        raise MatchImageParserError("The image parser returned an invalid player list.")

    return {
        "match_date": parsed.get("match_date"),
        "players": [str(name).strip() for name in players if str(name).strip()],
    }


def resolve_player_names(parsed_names, players):
    """Resolve parsed names against every known player alias.

    Matching is deliberately exact after whitespace/case normalization for now.
    Fuzzy matching can be added once we have real screenshots to evaluate.
    """
    lookup = {}
    for player_id, player in players.items():
        for alias in player.get("aliases", []):
            lookup[alias.strip().casefold()] = player_id

    resolved_ids = []
    unmatched = []
    for name in parsed_names:
        player_id = lookup.get(name.strip().casefold())
        if player_id is None:
            unmatched.append(name)
        elif player_id not in resolved_ids:
            resolved_ids.append(player_id)

    return resolved_ids, unmatched
