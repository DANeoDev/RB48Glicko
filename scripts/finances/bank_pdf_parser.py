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

try:
    import pymupdf
except ImportError:
    try:
        import fitz as pymupdf
    except ImportError:
        pymupdf = None

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
    if pymupdf is None:
        raise RuntimeError(
            "PyMuPDF ist auf diesem Server nicht installiert. "
            "Bitte installiere 'pymupdf' (z. B. via 'pip install pymupdf' im Terminal) "
            "oder lade Kontoauszüge als CSV-Dateien hoch."
        )

    if isinstance(pdf_content_or_path, (str, Path)):
        doc = pymupdf.open(str(pdf_content_or_path))
    elif isinstance(pdf_content_or_path, bytes):
        doc = pymupdf.open(stream=pdf_content_or_path, filetype="pdf")
    else:
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

    for page_idx, ptxt in enumerate(pages_text):
        if "Kontoauszug" not in ptxt and "Kontokorrent" not in ptxt and "alter Kontostand" not in ptxt:
            continue

        m_yr = re.search(r'neuer Kontostand vom \d{2}\.\d{2}\.(20\d{2})', ptxt) or re.search(r'erstellt am[\s\S]*?\b(20\d{2})\b', ptxt)
        stmt_year = int(m_yr.group(1)) if m_yr else int(default_year)

        lines = [line.strip() for line in ptxt.splitlines() if line.strip()]
        i = 0
        while i < len(lines):
            line = lines[i]

            skat_date_m = re.match(r'^(\d{2}\.\d{2}\.(?:\d{4})?)(?:\s+(\d{2}\.\d{2}\.(?:\d{4})?))?\s+(.+)', line)
            if not skat_date_m:
                i += 1
                continue

            vorgang_candidate = skat_date_m.group(3)
            is_tx_line = (
                "PN:" in vorgang_candidate
                or bool(re.search(r'(Überweisung|Lastschrift|Gebühr|Dauerauftrag|Gutschrift|Gutschr|Entgelt|Kartenzahlung|Abschluss)', vorgang_candidate, re.I))
                or bool(re.search(r'\d{1,3}(?:\.\d{3})*,\d{2}\s*[+\-HS]', vorgang_candidate))
            )
            if not is_tx_line:
                i += 1
                continue

            bu_raw = skat_date_m.group(1)
            if len(bu_raw.strip('.')) <= 5:
                p = bu_raw.strip('.').split('.')
                day, month = int(p[0]), int(p[1])
                tx_year = stmt_year if not (month == 12 and '01' in str(stmt_year)) else stmt_year - 1
                date_iso = f"{tx_year:04d}-{month:02d}-{day:02d}"
            else:
                date_iso = parse_date_to_iso(bu_raw)

            amt_val = None
            amt_match = re.search(r'([+\-]?\s*\d{1,3}(?:\.\d{3})*,\d{2})\s*([+\-HS])?', vorgang_candidate)
            desc = vorgang_candidate
            if amt_match and (" H" in amt_match.group(0) or " S" in amt_match.group(0) or amt_match.group(0).endswith("+") or amt_match.group(0).endswith("-")):
                amt_str_tok = amt_match.group(0).strip()
                amt_clean, valid = _clean_amount_token(amt_str_tok)
                if valid:
                    amt_val = amt_clean
                    desc = vorgang_candidate[:amt_match.start()].strip()

            i += 1
            entry_lines = []
            while i < len(lines):
                n_line = lines[i]
                if n_line.startswith('───') or 'neuer Kontostand' in n_line or re.match(r'^\d{2}\.\d{2}\.(?:\d{4})?(?:\s+\d{2}\.\d{2}\.(?:\d{4})?)?\s+', n_line):
                    break
                if amt_val is None:
                    amt_m = re.match(r'^\s*([+\-]?\s*\d{1,3}(?:\.\d{3})*,\d{2})\s*([+\-HS])?\s*$', n_line)
                    if amt_m:
                        amt_clean, valid = _clean_amount_token(amt_m.group(0))
                        if valid:
                            amt_val = amt_clean
                            i += 1
                            continue
                entry_lines.append(n_line)
                i += 1

            if amt_val is None:
                continue

            amount = round(amt_val, 2)
            full_entry_text = " ".join(entry_lines)
            payer_m = re.search(r'(?:Auftraggeber|Zahlungspflichtiger|Absender|Name):\s*([^,;\n\r]+?)(?:\s+(?:Verwendungszweck|Verw|SVWZ|IBAN|BIC|EREF|KREF|MREF|CRED)|\s*$)', full_entry_text, re.I)
            if payer_m:
                payer_name = payer_m.group(1).strip()
            elif entry_lines:
                payer_name = entry_lines[0].strip()
            else:
                payer_name = None

            note_m = re.search(r'(?:Verwendungszweck|SVWZ\+|Verw\.?\-Zweck|Notiz|Betreff):\s*(.+?)(?:\s+(?:EREF|KREF|MREF|CRED|IBAN|BIC)\+|\s*$)', full_entry_text, re.I)
            if note_m:
                note = note_m.group(1).strip()
            elif len(entry_lines) > 1:
                note = " ".join(entry_lines[1:]).strip()
            else:
                note = ""

            eref_match = re.search(r'\b(?:EREF|End-to-End-Ref(?:\.|erenz)?)\+?[:\s]*([^\s,;]+)', " ".join(entry_lines), re.I)
            if eref_match:
                tx_code = f"EREF-{eref_match.group(1).strip()}"
            else:
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
                "amount": amount,
                "raw_payer_name": payer_name,
                "raw_payer_email": None,
                "note": note,
                "status": status,
                "raw_payload": {"vorgang": desc, "entry_lines": entry_lines, "page": page_idx + 1},
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
