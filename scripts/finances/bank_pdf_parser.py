"""
Bank statement parser for Deutsche Skatbank and generic German bank PDF statements (and bank CSVs).
Extracts transactions, normalizes dates and amounts, detects payers and notes/verwendungszweck,
and converts PDF statements to standard CSV files stored in data/finances/skatbank/.
"""

import csv
from datetime import datetime
import io
import re
from pathlib import Path
import pymupdf

from scripts.finances.paypal_parser import parse_german_amount, parse_date_to_iso


def _extract_year_from_header(text: str) -> str:
    """Find the statement year from statement headers (e.g. 'Kontoauszug 2026' or 'per 31.12.2026')."""
    m = re.search(r'\b(202\d)\b', text)
    if m:
        return m.group(1)
    return str(datetime.now().year)


def _clean_amount_token(token: str) -> tuple[float, bool]:
    """
    Parse an amount string from German bank statement.
    Recognizes:
      '48,00+' -> +48.0
      '48,00 +' -> +48.0
      '48,00H' -> +48.0
      '+48,00' -> +48.0
      '15,00-' -> -15.0
      '15,00S' -> -15.0
      '-15,00' -> -15.0
    Returns: (amount, is_valid)
    """
    if not token:
        return 0.0, False
    s = token.strip()

    is_negative = False
    if s.endswith('-') or s.endswith('S') or s.endswith('s') or s.startswith('-'):
        is_negative = True
    elif s.endswith('+') or s.endswith('H') or s.endswith('h') or s.startswith('+'):
        is_negative = False

    cleaned = re.sub(r'[+\-HhSs€\s]', '', s)
    amt = parse_german_amount(cleaned)
    if is_negative:
        amt = -abs(amt)
    else:
        amt = abs(amt)
    return amt, True


def parse_bank_pdf(pdf_content_or_path) -> list[dict]:
    """
    Parse a German bank PDF statement (e.g. Deutsche Skatbank / VR-Banken).
    Extracts transactions into standardized dicts with source='bank'.
    """
    if isinstance(pdf_content_or_path, (str, Path)):
        doc = pymupdf.open(str(pdf_content_or_path))
    elif isinstance(pdf_content_or_path, bytes):
        doc = pymupdf.open(stream=pdf_content_or_path, filetype="pdf")
    else:
        # File-like
        data = pdf_content_or_path.read()
        doc = pymupdf.open(stream=data, filetype="pdf")

    full_text = ""
    pages_text = []
    for page in doc:
        ptxt = page.get_text("text")
        pages_text.append(ptxt)
        full_text += "\n" + ptxt

    default_year = _extract_year_from_header(full_text)

    transactions = []

    # Strategy 1: Tabular or line-based extraction across pages
    for page_idx, ptxt in enumerate(pages_text):
        lines = [line.strip() for line in ptxt.splitlines() if line.strip()]
        i = 0
        while i < len(lines):
            line = lines[i]

            # Look for lines starting with a date (e.g. 01.07.2026 or 01.07.26 or 01.07.)
            date_match = re.match(r'^(\d{2}\.\d{2}\.(?:\d{4}|\d{2})?)\b(?:\s+(\d{2}\.\d{2}\.(?:\d{4}|\d{2})?))?', line)
            if not date_match:
                i += 1
                continue

            raw_date = date_match.group(1)
            # Expand short date like 01.07. to 01.07.2026
            if len(raw_date) == 6 or raw_date.endswith('.'):
                raw_date = f"{raw_date.rstrip('.')}.{default_year}"
            elif len(raw_date.split('.')[-1]) == 2:
                # 01.07.26 -> 01.07.2026
                p = raw_date.split('.')
                raw_date = f"{p[0]}.{p[1]}.20{p[2]}"

            date_iso = parse_date_to_iso(raw_date)

            # Collect subsequent lines belonging to this booking entry until next date or end of block
            entry_lines = [line[date_match.end():].strip()]
            i += 1
            while i < len(lines):
                next_line = lines[i]
                # If next line starts with a new transaction date, stop
                if re.match(r'^\d{2}\.\d{2}\.(?:\d{4}|\d{2})?\b', next_line):
                    break
                # If footer or balance line, stop entry
                if re.match(r'^(Alter Kontostand|Neuer Kontostand|Kontostand|Endsaldo|Saldo|Seite \d+)', next_line, re.I):
                    i += 1
                    break
                entry_lines.append(next_line)
                i += 1

            entry_text = " ".join([l for l in entry_lines if l]).strip()

            # Find amount in entry_lines or line itself
            amount = 0.0
            found_amount = False

            # Search amount tokens: e.g. 48,00+ or 69,00 + or +48,00 or -15,00 or 48,00 H
            amt_matches = list(re.finditer(r'([+\-]?\s*\d{1,3}(?:\.\d{3})*,\d{2})\s*([+\-HS])?', entry_text))
            if amt_matches:
                # The last amount match in the line is usually the transaction amount (or second to last if saldo is next)
                for m in reversed(amt_matches):
                    full_amt_token = m.group(0).strip()
                    amt_val, valid = _clean_amount_token(full_amt_token)
                    if valid and abs(amt_val) > 0.001:
                        # Exclude obvious year numbers or saldos if recognizable
                        amount = amt_val
                        found_amount = True
                        break

            if not found_amount or abs(amount) < 0.001:
                continue

            # Identify Vorgang / Description
            desc = "Überweisung"
            desc_match = re.search(r'\b(SEPA-Gutschrift|Gutschrift|SEPA-Überweisung|Überweisung|Dauerauftrag|Lastschrift|Kartenzahlung|Abschluss|Entgelt|Zinsen)\b', entry_text, re.I)
            if desc_match:
                desc = desc_match.group(1).title()

            # If amount had no explicit sign: Gutschrift is +, Lastschrift is -
            if not re.search(r'[+\-HS]', entry_text) and not entry_text.startswith('+') and not entry_text.startswith('-'):
                if any(k in desc.lower() for k in ('gutschrift', 'eingang')):
                    amount = abs(amount)
                elif any(k in desc.lower() for k in ('lastschrift', 'entgelt', 'gebühr', 'abschluss')):
                    amount = -abs(amount)

            # Identify Payer / Auftraggeber
            payer_name = None
            payer_match = re.search(
                r'(?:Auftraggeber|Zahlungspflichtiger|Absender|Von|Name):\s*([^,;\n\r]+?)(?:\s+(?:Verwendungszweck|Verw|SVWZ|IBAN|BIC|EREF|KREF|MREF|CRED|End-to-End)|\s*$)',
                entry_text,
                re.I
            )
            if payer_match:
                payer_name = payer_match.group(1).strip()
            else:
                # Secondary heuristic: look for personal name patterns or text after booking type
                # Often e.g. "SEPA-Gutschrift Konstantin Steuer EREF+..."
                after_desc = ""
                if desc_match:
                    after_desc = entry_text[desc_match.end():].strip()
                else:
                    after_desc = entry_text

                # Strip IBAN / BIC / EREF
                cleaned_after = re.sub(r'\b[A-Z]{2}\d{2}[A-Z0-9\s]{12,30}\b', '', after_desc)
                cleaned_after = re.sub(r'\b(?:BIC|EREF|KREF|MREF|SVWZ|CRED)\+[^\s]+', '', cleaned_after)
                # Find leading words (2-3 words capitalized like a name)
                words = cleaned_after.split()
                if len(words) >= 2 and all(w[0].isupper() for w in words[:2] if len(w) > 0 and w.isalpha()):
                    candidate = f"{words[0]} {words[1]}"
                    if candidate.lower() not in ('deutsche skatbank', 'vr bank', 'neuer kontostand', 'alter kontostand'):
                        payer_name = candidate

            # Extract Verwendungszweck / Note
            note = ""
            note_match = re.search(r'(?:Verwendungszweck|SVWZ\+|Verw\.?\-Zweck|Notiz|Betreff):\s*(.+?)(?:\s+(?:EREF|KREF|MREF|CRED|IBAN|BIC)\+|\s*$)', entry_text, re.I)
            if note_match:
                note = note_match.group(1).strip()
            else:
                # Capture text between known markers
                cleaned_note = entry_text
                # Remove date, description, payer, amount tokens
                if desc_match:
                    cleaned_note = cleaned_note.replace(desc_match.group(0), "")
                if payer_name:
                    cleaned_note = cleaned_note.replace(payer_name, "")
                for m in amt_matches:
                    cleaned_note = cleaned_note.replace(m.group(0), "")
                # Remove IBANs
                cleaned_note = re.sub(r'\b[A-Z]{2}\d{2}[A-Z0-9\s]{12,30}\b', '', cleaned_note)
                cleaned_note = re.sub(r'\b(?:Auftraggeber|BIC|EREF|KREF|MREF|CRED|SVWZ|IBAN)[+:]?[^\s]*', '', cleaned_note, flags=re.I)
                cleaned_note = re.sub(r'\s+', ' ', cleaned_note).strip()
                if len(cleaned_note) > 3:
                    note = cleaned_note

            # Extract EREF or unique transaction code
            eref_match = re.search(r'\b(?:EREF|End-to-End-Ref(?:\.|erenz)?)\+?([^\s,;]+)', entry_text, re.I)
            if eref_match:
                tx_code = f"EREF-{eref_match.group(1).strip()}"
            else:
                # Deterministic hash of date, amount, payer, note
                h_str = f"{date_iso}-{amount:.2f}-{payer_name or ''}-{note[:20]}"
                tx_code = f"SKATBANK-{date_iso}-{abs(hash(h_str)) % 100000000:08d}"

            status = "imported" if amount > 0 else "expense"

            transactions.append({
                "source": "bank",
                "tx_code": tx_code,
                "date": date_iso,
                "time": "00:00:00",
                "description": desc,
                "currency": "EUR",
                "amount": round(amount, 2),
                "raw_payer_name": payer_name,
                "raw_payer_email": None,
                "note": note,
                "status": status,
                "raw_payload": {"entry_text": entry_text, "page": page_idx + 1},
            })

    return transactions


def convert_pdf_to_csv(pdf_content_or_path, output_csv_path: str | Path | None = None) -> str:
    """
    Parse a bank PDF statement and write a standard CSV file.
    Returns the CSV string or writes to output_csv_path if provided.
    """
    txs = parse_bank_pdf(pdf_content_or_path)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        "Datum", "Uhrzeit", "Beschreibung", "Betrag", "Währung",
        "Auftraggeber", "Verwendungszweck", "Transaktionscode"
    ])

    for tx in txs:
        # Format german amount with comma e.g. 48,00
        amt_str = f"{tx['amount']:.2f}".replace('.', ',')
        writer.writerow([
            tx["date"],
            tx["time"],
            tx["description"],
            amt_str,
            tx["currency"],
            tx["raw_payer_name"] or "",
            tx["note"] or "",
            tx["tx_code"],
        ])

    csv_data = output.getvalue()
    if output_csv_path:
        out_p = Path(output_csv_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(csv_data, encoding="utf-8-sig")

    return csv_data


def parse_bank_csv(content_or_file) -> list[dict]:
    """
    Parse a German bank CSV statement (Skatbank / VR-Bank CSV export).
    """
    raw_text = ""
    if isinstance(content_or_file, (str, Path)) and (isinstance(content_or_file, Path) or Path(content_or_file).exists()):
        file_path = Path(content_or_file)
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
            try:
                raw_text = file_path.read_text(encoding=enc)
                break
            except Exception:
                continue
    elif isinstance(content_or_file, bytes):
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
            try:
                raw_text = content_or_file.decode(enc)
                break
            except Exception:
                continue
    elif isinstance(content_or_file, str):
        raw_text = content_or_file
    else:
        data = content_or_file.read()
        if isinstance(data, bytes):
            for enc in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
                try:
                    raw_text = data.decode(enc)
                    break
                except Exception:
                    continue
        else:
            raw_text = data

    if not raw_text:
        return []

    sample = raw_text[:2048]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","

    reader = csv.DictReader(io.StringIO(raw_text), delimiter=delimiter)
    transactions = []

    for row in reader:
        date_raw = (
            row.get("Datum")
            or row.get("Buchungstag")
            or row.get("Valutadatum")
            or row.get("Date")
            or ""
        )
        time_raw = row.get("Uhrzeit") or row.get("Time") or "00:00:00"
        desc_raw = (
            row.get("Beschreibung")
            or row.get("Buchungstext")
            or row.get("Vorgang")
            or "Überweisung"
        )
        amt_raw = (
            row.get("Betrag")
            or row.get("Umsatz")
            or row.get("Amount")
            or "0,00"
        )
        payer_raw = (
            row.get("Auftraggeber")
            or row.get("Auftraggeber/Empfänger")
            or row.get("Name")
            or row.get("Name Zahlungsbeteiligter")
            or ""
        )
        note_raw = (
            row.get("Verwendungszweck")
            or row.get("Notiz")
            or row.get("Note")
            or ""
        )
        tx_code = (
            row.get("Transaktionscode")
            or row.get("Referenz")
            or row.get("End-to-End-Referenz")
            or ""
        )

        amount = parse_german_amount(amt_raw)
        date_iso = parse_date_to_iso(date_raw)

        if not date_iso:
            continue

        if not tx_code:
            h_str = f"{date_iso}-{amount:.2f}-{payer_raw}-{note_raw[:20]}"
            tx_code = f"SKATBANK-{date_iso}-{abs(hash(h_str)) % 100000000:08d}"

        status = "imported" if amount > 0 else "expense"

        transactions.append({
            "source": "bank",
            "tx_code": tx_code.strip(),
            "date": date_iso,
            "time": time_raw.strip(),
            "description": desc_raw.strip(),
            "currency": "EUR",
            "amount": amount,
            "raw_payer_email": None,
            "raw_payer_name": payer_raw.strip() if payer_raw else None,
            "note": note_raw.strip(),
            "status": status,
            "raw_payload": row,
        })

    return transactions
