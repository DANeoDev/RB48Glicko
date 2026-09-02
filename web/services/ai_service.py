import json
import os
import urllib.error
import urllib.request

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.5-flash-lite"


class NewsAIError(RuntimeError):
    """Raised when the News AI formatter cannot complete the request."""


def format_news_markdown(text, model=None):
    """Format plain News text as RB48-compatible Markdown using Gemini."""
    if not isinstance(text, str) or not text.strip():
        raise NewsAIError("Please enter some text to format.")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise NewsAIError("GEMINI_API_KEY is not configured on the server.")

    prompt = f"""
You are the RB48 website News editor.

Convert the following plain text into clean, concise Markdown suitable for an RB48 News item.

Supported Markdown ONLY:
- # Heading
- ## Subheading
- **bold**
- *italic*
- unordered lists using -
- ordered lists using 1.
- HTTP(S) links using standard Markdown syntax
- normal paragraphs

Rules:
- Preserve the factual meaning and all important information from the input.
- Do not invent information, dates, names, claims, or links.
- Use the first # heading as a concise News title when the input clearly has a title.
- Improve structure, spelling, punctuation, and readability where appropriate.
- Do not use raw HTML, tables, code blocks, images, or unsupported Markdown features.
- Return ONLY the Markdown. Do not wrap it in a code fence and do not add commentary.

Plain text to format:
---
{text.strip()}
---
""".strip()

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "text/plain"},
    }
    selected_model = model or os.environ.get("RB48_NEWS_MODEL", DEFAULT_MODEL)
    request = urllib.request.Request(
        GEMINI_API_URL.format(model=selected_model),
        data=json.dumps(payload).encode("utf-8"),
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(details).get("error", {}).get("message")
        except json.JSONDecodeError:
            message = None
        if message:
            raise NewsAIError(f"News AI API error ({exc.code}): {message}") from exc
        raise NewsAIError(f"News AI API error ({exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise NewsAIError("Could not reach the News AI API.") from exc

    texts = []
    for candidate in response_data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            value = part.get("text")
            if value:
                texts.append(value)

    result = "\n".join(texts).strip()
    if not result:
        raise NewsAIError("The News AI returned an empty response.")

    return result
