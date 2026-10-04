import csv
from datetime import datetime
import io
from pathlib import Path


def parse_german_amount(val_str: str) -> float:
    """Parse German currency number string like '3,50' or '-74,00' or '1.250,50' to float."""
    if not val_str:
        return 0.0
    clean = val_str.strip().replace("€", "").replace("\xa0", "").strip()
    # If standard US dot decimal
    if "," in clean and "." in clean:
        # Check if dot is thousand sep: 1.234,56
        if clean.rfind(",") > clean.rfind("."):
            clean = clean.replace(".", "").replace(",", ".")
        else:
            clean = clean.replace(",", "")
    elif "," in clean:
        clean = clean.replace(",", ".")
    try:
        return float(clean)
    except ValueError:
        return 0.0


def parse_date_to_iso(date_str: str) -> str:
    """Convert 'DD.MM.YYYY' or 'YYYY-MM-DD' to standard ISO 'YYYY-MM-DD'."""
    if not date_str:
        return ""
    clean = date_str.strip()
    # Try German DD.MM.YYYY
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(clean, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return clean


def parse_paypal_csv(content_or_file) -> list[dict]:
    """
    Parse a PayPal export CSV (file path, bytes, or string) and extract standardized transactions.
    """
    raw_text = ""
    if isinstance(content_or_file, (str, Path)) and (isinstance(content_or_file, Path) or Path(content_or_file).exists()):
        file_path = Path(content_or_file)
        # Try multiple encodings
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
        # File-like object
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

    # Detect delimiter
    sample = raw_text[:2048]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","

    reader = csv.DictReader(io.StringIO(raw_text), delimiter=delimiter)
    transactions = []

    for raw_row in reader:
        # Standardize and strip key lookups
        row = {str(k).strip(): (v.strip() if isinstance(v, str) else v) for k, v in raw_row.items() if k is not None}

        # Standardize key lookups across German and English PayPal exports
        date_raw = (
            row.get("Datum")
            or row.get("Date")
            or row.get("Buchungstag")
            or row.get("datum")
            or ""
        )
        time_raw = (
            row.get("Uhrzeit")
            or row.get("Time")
            or row.get("uhrzeit")
            or "00:00:00"
        )
        desc_raw = (
            row.get("Beschreibung")
            or row.get("Description")
            or row.get("Typ")
            or row.get("Type")
            or row.get("Buchungstext")
            or ""
        )
        curr_raw = (
            row.get("Währung")
            or row.get("Currency")
            or "EUR"
        )
        gross_raw = (
            row.get("Brutto")
            or row.get("Gross")
            or row.get("Betrag")
            or row.get("Amount")
            or "0,00"
        )
        tx_code = (
            row.get("Transaktionscode")
            or row.get("Transaction ID")
            or row.get("Transaktions-ID")
            or row.get("Referenz")
            or ""
        )
        payer_email = (
            row.get("Absender E-Mail-Adresse")
            or row.get("From Email Address")
            or row.get("E-Mail-Adresse")
            or row.get("Email")
            or ""
        )
        payer_name = (
            row.get("Name")
            or row.get("Absender")
            or row.get("Auftraggeber")
            or row.get("Name Zahlungsbeteiligter")
            or row.get("Sender Name")
            or row.get("From Name")
            or ""
        )
        # Collect all notes / references across standard and detailed PayPal CSV formats
        candidate_notes = []
        for field in ("Hinweis", "Betreff", "Notiz", "Note", "Verwendungszweck", "SVWZ", "Artikelbezeichnung", "Rechnungsnummer"):
            val = (row.get(field) or "").strip()
            if val and val not in candidate_notes:
                candidate_notes.append(val)
        note_raw = " - ".join(candidate_notes)

        amount = parse_german_amount(gross_raw)
        date_iso = parse_date_to_iso(date_raw)

        if not tx_code and not date_iso:
            continue

        # Adjust sign if Auswirkung auf Guthaben is explicit (e.g. Soll / Haben)
        impact_raw = (row.get("Auswirkung auf Guthaben") or row.get("Impact on Balance") or "").strip().lower()
        if impact_raw == "soll" and amount > 0:
            amount = -amount
        elif impact_raw == "haben" and amount < 0:
            amount = abs(amount)

        # Detect source: if it contains bank-specific fields but no PayPal fields, label as bank
        is_actually_bank = (
            ("Auftraggeber" in row or "Verwendungszweck" in row or "SKATBANK" in str(tx_code).upper())
            and not any(f in row for f in ("Absender E-Mail-Adresse", "From Email Address", "Auswirkung auf Guthaben", "Guthaben"))
        )
        source = "bank" if is_actually_bank else "paypal"

        # Status: negative or known expense providers
        if amount < 0 or "express-zahlung" in desc_raw.lower() or "eversport" in payer_name.lower():
            status = "expense"
        else:
            status = "imported"

        transactions.append({
            "source": source,
            "tx_code": tx_code.strip(),
            "date": date_iso,
            "time": time_raw.strip(),
            "description": desc_raw.strip(),
            "currency": curr_raw.strip(),
            "amount": amount,
            "raw_payer_email": payer_email.strip().lower() if payer_email else None,
            "raw_payer_name": payer_name.strip() if payer_name else None,
            "note": note_raw.strip(),
            "status": status,
            "raw_payload": row,
        })

    return transactions
