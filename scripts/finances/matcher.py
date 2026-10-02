import re
import difflib
from datetime import datetime
from scripts.database.database import get_connection as get_rb48_connection
from scripts.accounts.database import get_accounts_connection
from scripts.finances.database import get_finances_connection, get_identities


def normalize_text(text: str | None) -> str:
    """Normalize text for case-insensitive and punctuation-free comparison."""
    if not text:
        return ""
    # Lowercase, replace umlauts/accents for robust matching
    t = text.strip().lower()
    t = t.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    # Replace non-alphanumeric with space
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def parse_guest_hints_from_note(note: str | None) -> list[str]:
    """Extract potential guest names from PayPal payment notes.
    
    Examples:
        'Gastbeitrag Max'           -> ['Max']
        'Für Max und Tim'           -> ['Max', 'Tim']
        'Gastbeitrag Max + Lisa'    -> ['Max', 'Lisa']
        '2x Gastbeitrag'            -> []  (count but no names)
        'Handyzahlung'              -> []
        ''                          -> []
    """
    if not note:
        return []
    
    clean = note.strip()
    if not clean:
        return []
    
    # Early check: full-string patterns like '2x Gastbeitrag', '3x Gast', '2 mal Gastbeitrag'
    if re.match(r'^\d+\s*(x|mal)\s*(gast(beitrag)?|beitrag)?\s*$', clean, re.IGNORECASE):
        return []
    
    # Remove leading multiplier prefix (e.g. '2x ', '3 mal ')
    remainder = re.sub(r'^\d+\s*(x|mal)\s*', '', clean, flags=re.IGNORECASE).strip()
    
    # Remove common keyword prefixes
    prefixes = [
        r'vereinsbeitrag\s*(und\s*)?',
        r'mitgliedsbeitrag\s*(und\s*)?',
        r'gastbeitrag\s*',
        r'gast[\-\s]*beitrag\s*',
        r'gast\s*',
        r'zahlung\s+(?:von|f(?:ue|[uü])r)\s+',
        r'f(?:ue|[uü])r\s+',
        r'von\s+',
        r'beitrag\s+(f(?:ue|[uü])r\s+)?',
    ]
    for prefix in prefixes:
        remainder = re.sub(f'^{prefix}', '', remainder, flags=re.IGNORECASE).strip()
    
    # If only a number pattern remains (e.g. '2x', '3 mal'), no names
    if re.match(r'^\d+\s*(x|mal)?\s*$', remainder, re.IGNORECASE):
        return []
    
    # If remainder is empty or same as original generic description, no hints
    if not remainder or remainder.lower() in ('handyzahlung', 'zahlung', 'paypal', ''):
        return []
    
    # Split by common delimiters: 'und', '+', '&', ',', '/'
    parts = re.split(r'\s+und\s+|\s*[+&,/]\s*', remainder, flags=re.IGNORECASE)
    
    names = []
    stopwords = {
        'gastbeitrag', 'beitrag', 'gast', 'handyzahlung', 'zahlung', 'paypal',
        'vereinsbeitrag', 'mitgliedsbeitrag', 'halbjahr', 'h1', 'h2', 'jahresbeitrag',
        'spende', 'turnier', 'ball', 'mitglieder'
    }
    for part in parts:
        name = part.strip()
        # Strip sub-prefixes like 'zahlung von ' or 'von '
        name = re.sub(r'^(?:zahlung\s+(?:von|f(?:ue|[uü])r)\s+|von\s+|f(?:ue|[uü])r\s+)', '', name, flags=re.IGNORECASE).strip()
        # Filter out noise: pure numbers, very short tokens, common words
        if name and len(name) >= 2 and not re.match(r'^\d+$', name):
            if name.lower() not in stopwords:
                names.append(name)
    
    return names


def analyze_payment_note(note: str | None) -> dict:
    """Analyze note for membership due clues, period hints, and guest names."""
    if not note:
        return {"has_due_hint": False, "guest_names": [], "period_hint": None}

    text = note.strip().lower()
    has_due = any(k in text for k in ("vereinsbeitrag", "mitgliedsbeitrag", "mitglied", "halbjahr", "h1", "h2", "jahresbeitrag"))

    period_hint = None
    curr_year = str(datetime.now().year)
    year_match = re.search(r'\b(202\d)\b', text)
    year_str = year_match.group(1) if year_match else curr_year

    if any(k in text for k in ("h2", "2. halbjahr", "2.halbjahr", "zweites halbjahr")):
        period_hint = f"{year_str}-H2"
    elif any(k in text for k in ("h1", "1. halbjahr", "1.halbjahr", "erstes halbjahr")):
        period_hint = f"{year_str}-H1"

    guest_names = parse_guest_hints_from_note(note)

    return {
        "has_due_hint": has_due,
        "guest_names": guest_names,
        "period_hint": period_hint,
    }


def find_player_match(
    raw_payer_name: str | None,
    raw_payer_email: str | None,
    note: str | None = None,
    finances_conn=None,
    rb48_conn=None,
    accounts_conn=None,
) -> dict:
    """
    Smart matching engine that suggests a player_id, user_id, and confidence score (0.0 to 1.0)
    based on learned identities, user accounts, and player aliases.
    """
    close_fin = False
    close_rb48 = False
    close_acc = False

    if finances_conn is None:
        finances_conn = get_finances_connection()
        close_fin = True
    if rb48_conn is None:
        rb48_conn = get_rb48_connection()
        close_rb48 = True
    if accounts_conn is None:
        accounts_conn = get_accounts_connection()
        close_acc = True

    try:
        clean_email = (raw_payer_email or "").strip().lower()
        clean_name = (raw_payer_name or "").strip()
        norm_name = normalize_text(clean_name)
        norm_email = normalize_text(clean_email)

        # 1. Check persistent learned memory (payment_identities)
        if clean_email:
            row = finances_conn.execute(
                "SELECT player_id, user_id, confidence FROM payment_identities WHERE LOWER(payer_email) = ?",
                (clean_email,),
            ).fetchone()
            if row:
                return {
                    "player_id": row["player_id"],
                    "user_id": row["user_id"],
                    "confidence": float(row["confidence"] or 1.0),
                    "match_type": "learned_email",
                    "reason": "Gelerntes Profil (E-Mail)",
                }

        if clean_name:
            row = finances_conn.execute(
                "SELECT player_id, user_id, confidence FROM payment_identities WHERE LOWER(payer_name) = ?",
                (clean_name.lower(),),
            ).fetchone()
            if row:
                return {
                    "player_id": row["player_id"],
                    "user_id": row["user_id"],
                    "confidence": min(float(row["confidence"] or 0.95), 0.95),
                    "match_type": "learned_name",
                    "reason": "Gelerntes Profil (Name)",
                }

        # 2. Check registered user accounts (accounts.db)
        if clean_email:
            user = accounts_conn.execute(
                "SELECT id, username, email, player_id, attendance_name FROM users WHERE LOWER(email) = ?",
                (clean_email,),
            ).fetchone()
            if user and user["player_id"]:
                return {
                    "player_id": user["player_id"],
                    "user_id": user["id"],
                    "confidence": 0.95,
                    "match_type": "user_email",
                    "reason": f"Benutzerkonto ({user['username']})",
                }

        # 3. Check aliases and players in rb48.db
        alias_rows = rb48_conn.execute("SELECT alias, player_id FROM aliases").fetchall()
        
        # Exact alias match in name or email
        best_match = None
        best_score = 0.0
        best_reason = ""

        name_tokens = norm_name.split() if norm_name else []
        email_prefix = clean_email.split("@")[0] if "@" in clean_email else clean_email
        norm_email_prefix = normalize_text(email_prefix)

        for row in alias_rows:
            alias = row["alias"]
            pid = row["player_id"]
            norm_alias = normalize_text(alias)
            
            # Skip noise or generic aliases like "+1"
            if not norm_alias or norm_alias in ("1", "gast", "guest"):
                continue

            # Exact match with whole name
            if norm_alias == norm_name:
                return {
                    "player_id": pid,
                    "user_id": None,
                    "confidence": 0.95,
                    "match_type": "alias_exact",
                    "reason": f"Exakter Spieler-Name ('{alias}')",
                }

            # Alias is one of the tokens in the full name (e.g. "Kha" in "An-Kha Ha-Phuoc" or "Samuel" in "Samuel Schelp")
            for token in name_tokens:
                if token == norm_alias:
                    score = 0.88
                    if score > best_score:
                        best_score = score
                        best_match = pid
                        best_reason = f"Alias-Treffer ('{alias}')"
                elif token.startswith(norm_alias) and len(norm_alias) >= 3:
                    # e.g. "Nik" in "Niklas"
                    score = 0.80
                    if score > best_score:
                        best_score = score
                        best_match = pid
                        best_reason = f"Namens-Präfix ('{alias}' -> '{token}')"
                elif norm_alias.startswith(token) and len(token) >= 3:
                    score = 0.78
                    if score > best_score:
                        best_score = score
                        best_match = pid
                        best_reason = f"Namens-Ähnlichkeit ('{token}' -> '{alias}')"
                else:
                    # Check shared prefix (e.g. "konst" in "konsti" and "konstantin")
                    prefix_len = 0
                    for c1, c2 in zip(token, norm_alias):
                        if c1 == c2:
                            prefix_len += 1
                        else:
                            break
                    if prefix_len >= 4:
                        score = 0.75 + min(prefix_len - 4, 3) * 0.03
                        if score > best_score:
                            best_score = score
                            best_match = pid
                            best_reason = f"Namens-Ähnlichkeit ('{token}' ~ '{alias}')"

            # Check email prefix
            if norm_alias in norm_email_prefix:
                score = 0.75
                if score > best_score:
                    best_score = score
                    best_match = pid
                    best_reason = f"E-Mail enthält Alias ('{alias}')"

            # String similarity (difflib) on full name vs alias
            sim = difflib.SequenceMatcher(None, norm_alias, norm_name).ratio()
            if sim > 0.80 and sim > best_score:
                best_score = sim * 0.85
                best_match = pid
                best_reason = f"Hohe Namensähnlichkeit ('{alias}')"

        if best_match and best_score >= 0.70:
            return {
                "player_id": best_match,
                "user_id": None,
                "confidence": round(best_score, 2),
                "match_type": "alias_fuzzy",
                "reason": best_reason,
            }

        return {
            "player_id": None,
            "user_id": None,
            "confidence": 0.0,
            "match_type": "none",
            "reason": "Keine automatische Zuordnung gefunden",
        }
    finally:
        if close_fin:
            finances_conn.close()
        if close_rb48:
            rb48_conn.close()
        if close_acc:
            accounts_conn.close()


def mask_single_word(word: str) -> str:
    """Mask a single word/name so it is not fully exposed."""
    s = word.strip()
    if len(s) <= 2:
        return s + ".."
    if len(s) == 3:
        return s[:2] + ".."
    if len(s) == 4:
        return s[:2] + ".."
    if len(s) == 5:
        return s[:3] + "..."
    if len(s) == 6:
        return s[:4] + "..."
    return s[:3] + "..."


def mask_payer_name(raw_name: str | None) -> str:
    """
    Mask a payer name or email from PayPal so that full names are not completely exposed.
    Examples:
        'Sarah Lagona'               -> 'Sarah Lago...'
        'Julian Lang'                -> 'Julian La..'
        'Stefan Metzger'             -> 'Stefan Met...'
        'sarah.lagona@gmail.com'     -> 'Sarah Lago...'
        'juliankorsch@googlemail.com'-> 'Jul...'
    """
    if not raw_name:
        return ""
    s = raw_name.strip()
    if s.startswith("Transaktion #"):
        return s
    if "@" in s and " " not in s:
        local, _ = s.split("@", 1)
        for sep in [".", "_", "-"]:
            if sep in local:
                sub = local.split(sep)
                first = sub[0].capitalize()
                last = sub[-1].capitalize()
                return f"{first} {mask_single_word(last)}"
        return mask_single_word(local).capitalize()

    parts = s.split()
    if len(parts) == 1:
        return mask_single_word(parts[0])

    first_names = " ".join(parts[:-1])
    last_name = parts[-1]
    return f"{first_names} {mask_single_word(last_name)}"

