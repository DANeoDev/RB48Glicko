import json
import os
import urllib.error
import urllib.request

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.5-flash-lite"


def suggest_transaction_allocation_ai(
    tx: dict,
    open_receivables: list[dict],
    players: list[dict],
    model: str | None = None,
) -> dict | None:
    """
    Use Google Gemini to intelligently analyze an incoming finance transaction
    (amount, date, payer name, email, purpose/note) against open receivables and players.
    Returns structured suggestion or None on failure / missing API key.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    # Filter to most relevant receivables (e.g. up to 100 open items)
    compact_receivables = []
    for r in open_receivables[:100]:
        compact_receivables.append({
            "id": r["id"],
            "kind": r.get("kind"),
            "title": r.get("title"),
            "amount": float(r.get("amount", 0.0)),
            "player_id": r.get("player_id"),
            "guest_alias": r.get("guest_alias"),
            "match_date": r.get("match_date"),
            "period": r.get("period"),
        })

    compact_players = []
    for p in players[:150]:
        compact_players.append({
            "id": p.get("player_id"),
            "name": p.get("name"),
            "aliases": p.get("aliases", []),
        })

    prompt = f"""
You are an intelligent club finance assistant for the RB48 football club.
Analyze the following bank/PayPal transaction and recommend:
1. Which player paid this (payer_player_id or payer_alias)
2. Which specific open receivable(s) (by receivable_id) this payment covers, and how much of each.

TRANSACTION:
- ID: {tx.get("id")}
- Amount: {tx.get("amount")} EUR
- Date: {tx.get("date")}
- Payer Name: {tx.get("raw_payer_name")}
- Payer Email: {tx.get("raw_payer_email")}
- Note / Verwendungszweck: {tx.get("note")}
- Description: {tx.get("description")}

OPEN RECEIVABLES (first 100):
{json.dumps(compact_receivables, ensure_ascii=False)}

REGISTERED PLAYERS:
{json.dumps(compact_players, ensure_ascii=False)}

RULES:
- A semester membership due is usually 48.00 EUR (e.g. 2026-H1, 2026-H2). A full year is 96.00 EUR.
- Guest fees are 3.50 EUR per match kick.
- SoSe26 / Sommersemester refers to 2026-H1. WiSe26 / Wintersemester refers to 2026-H2.
- A member may pay on behalf of another guest or member (proxy payment, e.g. 'Julian für Malte').
- Only allocate up to the transaction amount ({tx.get("amount")} EUR).
- Output valid JSON only, matching this exact schema:
{{
  "payer_player_id": <int or null>,
  "payer_alias": <string or null>,
  "allocations": [
    {{"receivable_id": <int>, "amount": <float>}}
  ],
  "confidence": <float between 0.0 and 1.0>,
  "reasoning": "<short German explanation>"
}}
""".strip()

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
        },
    }

    selected_model = model or os.environ.get("RB48_FINANCE_AI_MODEL", DEFAULT_MODEL)
    url = GEMINI_API_URL.format(model=selected_model)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            candidates = res_data.get("candidates", [])
            if not candidates:
                return None
            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            if not parts:
                return None
            raw_text = parts[0].get("text", "").strip()
            parsed = json.loads(raw_text)

            valid_rids = {r["id"] for r in compact_receivables}
            filtered_allocs = [
                a for a in parsed.get("allocations", [])
                if a.get("receivable_id") in valid_rids and float(a.get("amount", 0.0)) > 0
            ]
            parsed["allocations"] = filtered_allocs
            return parsed
    except Exception:
        return None
