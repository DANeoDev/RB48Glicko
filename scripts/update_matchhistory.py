# scans existing ids in matchhistory.csv and appends new matches from the matches folder to it, avoiding duplicates

from pathlib import Path
import csv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MATCHES_FOLDER = PROJECT_ROOT / "matches"
MATCHHISTORY_FILE = PROJECT_ROOT / "data" / "matchhistory.csv"


def get_existing_match_ids():  # scan existing match ids in matchhistory.csv
    existing_ids = set()

    if MATCHHISTORY_FILE.exists():
        with open(MATCHHISTORY_FILE, "r", newline="", encoding="utf-8") as h_file:
            reader = csv.reader(h_file)
            for row in reader:
                if not row:
                    continue
                if row[0].startswith("#"):
                    continue  # Skip comment lines
                if row[0] == "match_id":
                    continue  # Skip header row

                existing_ids.add(row[0])

    return existing_ids


def append_new_matches(
    existing_ids,
):  # append new matches from matches folder to matchhistory.csv if not present already
    with open(MATCHHISTORY_FILE, "a", newline="", encoding="utf-8") as h_file:
        writer = csv.writer(h_file)

        # scan matches folder for new match files and append them to matchhistory.csv if they are not already present:
        for file in MATCHES_FOLDER.glob("*.csv"):
            with open(file, "r", newline="", encoding="utf-8") as csvfile:
                reader = csv.reader(csvfile)
                for row in reader:
                    if not row:
                        continue

                    match_id = row[0]

                    if match_id in existing_ids:
                        continue
                    writer.writerow(row)
                    existing_ids.add(match_id)


def update_matchhistory():
    existing_ids = get_existing_match_ids()
    append_new_matches(existing_ids)


if __name__ == "__main__":
    update_matchhistory()
