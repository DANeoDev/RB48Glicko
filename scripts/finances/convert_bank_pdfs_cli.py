"""
Local CLI Tool: Convert Skatbank and Bank Statement PDFs to CSV.

Usage:
    python -m scripts.finances.convert_bank_pdfs_cli
    python scripts/finances/convert_bank_pdfs_cli.py --dir data/finances/skatbank
    python scripts/finances/convert_bank_pdfs_cli.py --file path/to/statement.pdf --output my_statement.csv
"""

import argparse
import csv
import io
import sys
from pathlib import Path

# Add project root to sys.path if invoked directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.finances.bank_pdf_parser import parse_bank_pdf, convert_pdf_to_csv


def convert_all_pdfs(
    input_dir: Path,
    output_dir: Path | None = None,
    combined_path: Path | None = None,
) -> tuple[int, int, float, float]:
    """
    Find all PDFs in input_dir, parse them, generate individual CSVs,
    and optionally a combined CSV file.
    Returns: (files_count, total_txs, total_income, total_expenses)
    """
    if not input_dir.exists():
        print(f"❌ Verzeichnis nicht gefunden: {input_dir}")
        return 0, 0, 0.0, 0.0

    if output_dir is None:
        output_dir = input_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Deduplicate files for case-insensitive file systems (Windows)
    pdf_files_set = {p.resolve() for p in input_dir.glob("*.pdf")} | {p.resolve() for p in input_dir.glob("*.PDF")}
    pdf_files = sorted(list(pdf_files_set))
    if not pdf_files:
        print(f"⚠️ Keine PDF-Dateien in {input_dir} gefunden.")
        return 0, 0, 0.0, 0.0

    all_txs = []
    seen_tx_codes = set()
    total_income = 0.0
    total_expenses = 0.0

    print(f"\n📂 Gefundene Kontoauszug-PDFs ({len(pdf_files)} Dateien) in '{input_dir}':")
    print("=" * 80)

    for pdf_path in pdf_files:
        csv_path = output_dir / f"{pdf_path.stem}.csv"
        try:
            txs = parse_bank_pdf(pdf_path)
            # Write individual CSV
            convert_pdf_to_csv(pdf_path, csv_path)

            file_income = sum(t["amount"] for t in txs if t["amount"] > 0)
            file_expenses = sum(abs(t["amount"]) for t in txs if t["amount"] < 0)

            print(f"  📄 {pdf_path.name}")
            print(f"     ➔ {len(txs)} Buchung(en) | Einnahmen: +{file_income:.2f} € | Ausgaben: -{file_expenses:.2f} €")
            print(f"     ➔ CSV gespeichert: {csv_path.name}")

            for t in txs:
                code = t["tx_code"]
                if code not in seen_tx_codes:
                    seen_tx_codes.add(code)
                    all_txs.append(t)
                    if t["amount"] > 0:
                        total_income += t["amount"]
                    else:
                        total_expenses += abs(t["amount"])

        except Exception as e:
            print(f"  ❌ Fehler bei {pdf_path.name}: {e}")

    # Write combined CSV if requested or default
    if combined_path:
        combined_path.parent.mkdir(parents=True, exist_ok=True)
        # Sort chronologically by date
        all_txs.sort(key=lambda x: (x["date"], x.get("time", "")))

        with open(combined_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow([
                "Datum", "Uhrzeit", "Beschreibung", "Betrag", "Währung",
                "Auftraggeber", "Verwendungszweck", "Transaktionscode"
            ])
            for tx in all_txs:
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
        print("=" * 80)
        print(f"✨ Kombinierte CSV mit allen {len(all_txs)} Buchungen erstellt:")
        print(f"   📁 {combined_path}")
        print(f"   💶 Gesamteinnahmen: +{total_income:.2f} € | Gesamtausgaben: -{total_expenses:.2f} €")
        print("=" * 80)

    return len(pdf_files), len(all_txs), total_income, total_expenses


def main():
    parser = argparse.ArgumentParser(
        description="Konvertiert Deutsche Skatbank Kontoauszüge (PDF) in uploadfertige CSV-Dateien."
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("data/finances/skatbank"),
        help="Pfad zum Ordner mit den PDF-Kontoauszügen (Standard: data/finances/skatbank)",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Einzelne PDF-Datei zum Konvertieren",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Pfad für die Ausgabedatei (bei --file) oder Ausgabeordner (bei --dir)",
    )
    parser.add_argument(
        "--combined",
        type=Path,
        default=Path("data/finances/skatbank/skatbank_all_2026.csv"),
        help="Pfad für die kombinierte Gesamt-CSV (Standard: data/finances/skatbank/skatbank_all_2026.csv)",
    )

    args = parser.parse_args()

    if args.file:
        if not args.file.exists():
            print(f"❌ Datei nicht gefunden: {args.file}")
            sys.exit(1)
        out_csv = args.output or args.file.with_suffix(".csv")
        try:
            txs = parse_bank_pdf(args.file)
            convert_pdf_to_csv(args.file, out_csv)
            print(f"✅ {len(txs)} Buchungen erfolgreich nach '{out_csv}' exportiert.")
        except Exception as e:
            print(f"❌ Konvertierungsfehler: {e}")
            sys.exit(1)
    else:
        convert_all_pdfs(
            input_dir=args.dir,
            output_dir=args.output or args.dir,
            combined_path=args.combined,
        )


if __name__ == "__main__":
    main()
