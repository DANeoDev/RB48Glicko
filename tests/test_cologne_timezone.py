"""
Unit tests for Cologne timezone (Europe/Berlin) standardization across RB48.
"""
import unittest
from datetime import datetime, date, timezone, timedelta
from zoneinfo import ZoneInfo
import sqlite3

from scripts.utils.timezone import (
    COLOGNE_TZ,
    get_cologne_now,
    get_cologne_date,
    get_cologne_date_str,
    get_cologne_time_str,
    get_cologne_timestamp_str,
    get_cologne_file_timestamp,
    to_cologne_datetime,
    format_cologne_datetime,
)
from scripts.accounts.database import (
    create_account_tables,
    get_match_mvp_deadline,
    is_match_mvp_voting_open,
    record_match_mvp_vote,
    record_gallery_photo,
    get_gallery_photo_metadata,
)
from scripts.finances.database import (
    create_finance_tables,
    create_finance_archive,
    get_finance_archive_by_id,
    insert_transaction,
    get_transaction_by_id,
)
from web.routes.planner import (
    calculate_guest_unlock_time,
    is_guest_registration_unlocked,
)


class TestCologneTimezone(unittest.TestCase):
    def test_timezone_constant_and_now(self):
        """Verify COLOGNE_TZ is Europe/Berlin and get_cologne_now() returns aware datetime."""
        self.assertEqual(str(COLOGNE_TZ), "Europe/Berlin")
        now = get_cologne_now()
        self.assertIsNotNone(now.tzinfo)
        self.assertEqual(now.tzinfo, COLOGNE_TZ)

    def test_cologne_date_and_strings(self):
        """Verify helper functions return properly formatted strings."""
        now = get_cologne_now()
        date_str = get_cologne_date_str()
        time_str = get_cologne_time_str()
        ts_str = get_cologne_timestamp_str()
        file_ts = get_cologne_file_timestamp()

        self.assertEqual(date_str, now.strftime("%Y-%m-%d"))
        self.assertEqual(time_str[:5], now.strftime("%H:%M"))
        self.assertEqual(ts_str[:10], date_str)
        self.assertEqual(len(file_ts), 15)  # YYYYMMDD_HHMMSS

    def test_summer_and_winter_time_offsets(self):
        """Europe/Berlin must be UTC+2 in summer (CEST) and UTC+1 in winter (CET)."""
        summer_dt = datetime(2026, 7, 15, 12, 0, 0, tzinfo=COLOGNE_TZ)
        winter_dt = datetime(2026, 1, 15, 12, 0, 0, tzinfo=COLOGNE_TZ)

        self.assertEqual(summer_dt.utcoffset(), timedelta(hours=2))
        self.assertEqual(winter_dt.utcoffset(), timedelta(hours=1))

    def test_to_cologne_datetime_from_utc(self):
        """Converting a UTC datetime to Cologne time properly adjusts hours."""
        # Summer: 14:00 UTC -> 16:00 CEST (UTC+2)
        utc_summer = datetime(2026, 7, 20, 14, 0, 0, tzinfo=timezone.utc)
        cologne_summer = to_cologne_datetime(utc_summer)
        self.assertEqual(cologne_summer.hour, 16)
        self.assertEqual(cologne_summer.tzinfo, COLOGNE_TZ)

        # Winter: 14:00 UTC -> 15:00 CET (UTC+1)
        utc_winter = datetime(2026, 12, 20, 14, 0, 0, tzinfo=timezone.utc)
        cologne_winter = to_cologne_datetime(utc_winter)
        self.assertEqual(cologne_winter.hour, 15)
        self.assertEqual(cologne_winter.tzinfo, COLOGNE_TZ)

    def test_to_cologne_datetime_from_iso_string(self):
        """ISO strings with Z or offsets are properly converted to Cologne time."""
        iso_str = "2026-08-10T12:00:00Z"
        col_dt = to_cologne_datetime(iso_str)
        self.assertIsNotNone(col_dt)
        self.assertEqual(col_dt.hour, 14)  # 12:00 UTC is 14:00 CEST

        # Formatting
        fmt_str = format_cologne_datetime(iso_str, fmt="%d.%m.%Y %H:%M")
        self.assertEqual(fmt_str, "10.08.2026 14:00")

    def test_mvp_voting_deadline_and_window(self):
        """MVP deadline is 20:00 Europe/Berlin on next day; window checks respect Cologne time."""
        deadline = get_match_mvp_deadline("2026-09-08")
        self.assertEqual(deadline.year, 2026)
        self.assertEqual(deadline.month, 9)
        self.assertEqual(deadline.day, 9)
        self.assertEqual(deadline.hour, 20)
        self.assertEqual(deadline.minute, 0)
        self.assertEqual(deadline.tzinfo, COLOGNE_TZ)

        # 19:59 next day -> Open
        test_now_open = datetime(2026, 9, 9, 19, 59, 0, tzinfo=COLOGNE_TZ)
        self.assertTrue(is_match_mvp_voting_open("2026-09-08", test_now_open))

        # 20:01 next day -> Closed
        test_now_closed = datetime(2026, 9, 9, 20, 1, 0, tzinfo=COLOGNE_TZ)
        self.assertFalse(is_match_mvp_voting_open("2026-09-08", test_now_closed))

    def test_record_match_mvp_vote_cologne_timestamp(self):
        """Recorded MVP votes have created_at in Cologne date & time format."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        create_account_tables(conn)

        # Insert user
        conn.execute("INSERT INTO users (id, username, email, password_hash, created_at) VALUES (1, 'voter1', 'voter1@rb48.de', 'dummy', '2026-10-04 12:00:00')")
        conn.commit()

        success = record_match_mvp_vote(conn, "match_100", 1, 10, 20, 30)
        self.assertTrue(success)

        row = conn.execute("SELECT created_at FROM match_mvp_votes WHERE match_id = ?", ("match_100",)).fetchone()
        self.assertIsNotNone(row)
        created_at_str = row["created_at"]
        # Format is YYYY-MM-DD HH:MM:SS
        self.assertEqual(len(created_at_str), 19)
        today_cologne = get_cologne_date_str()
        self.assertTrue(created_at_str.startswith(today_cologne))

    def test_finances_archive_cologne_timestamp(self):
        """Created finance archive has archived_at formatted in Cologne time."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        create_finance_tables(conn)

        arch_id = create_finance_archive(
            conn,
            title="Archiv Test",
            tx_count=2,
            total_income=48.0,
            total_expenses=0.0,
            csv_data="test,csv",
        )
        arch = get_finance_archive_by_id(conn, arch_id)
        self.assertIsNotNone(arch)
        archived_at = arch["archived_at"]
        self.assertEqual(len(archived_at), 19)
        today_cologne = get_cologne_date_str()
        self.assertTrue(archived_at.startswith(today_cologne))

    def test_planner_guest_unlock_cologne_time(self):
        """Preceding Sunday 00:00 Cologne time controls guest unlock."""
        # Match on Tuesday 2026-09-08
        unlock_time = calculate_guest_unlock_time("2026-09-08 18:30")
        self.assertEqual(unlock_time.strftime("%Y-%m-%d %H:%M:%S"), "2026-09-06 00:00:00")


if __name__ == "__main__":
    unittest.main()
