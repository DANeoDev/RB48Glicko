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

    for row in reader:
        # Standardize key lookups across German and English PayPal exports
        date_raw = (
            row.get("Datum")
            or row.get("Date")
            or row.get("datum")
            or ""
        )
        time_raw = (
            row.get("Uhrzeit")
            or row.get("Time")
            or row.get("uhrzeit")
            or ""
        )
        desc_raw = (
            row.get("Beschreibung")
            or row.get("Description")
            or row.get("Typ")
            or row.get("Type")
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
            or ""
        )
        note_raw = (
            row.get("Rechnungsnummer")
            or row.get("Notiz")
            or row.get("Betreff")
            or row.get("Note")
            or ""
        )

        amount = parse_german_amount(gross_raw)
        date_iso = parse_date_to_iso(date_raw)

        if not tx_code and not date_iso:
            continue

        # Status: negative or known expense providers
        if amount < 0 or "express-zahlung" in desc_raw.lower() or "eversport" in payer_name.lower():
            status = "expense"
        else:
            status = "imported"

        transactions.append({
            "source": "paypal",
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
