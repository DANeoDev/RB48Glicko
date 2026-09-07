import unittest
from scripts.database.database import get_connection
from scripts.analysis.history_snapshots import get_matchday_metadata_map, compute_historical_snapshots


class TestHistorySnapshots(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection()

    def tearDown(self):
        self.conn.close()

    def test_get_matchday_metadata_map(self):
        meta = get_matchday_metadata_map(self.conn)
        self.assertGreater(len(meta), 0)
        # Check first and last date
        dates = sorted(meta.keys())
        first_d = meta[dates[0]]
        self.assertEqual(first_d["matchday_number"], 1)
        self.assertIn("Saison 2026", first_d["label"])
        self.assertEqual(first_d["short_label"], "1. Spieltag")
        
        last_d = meta[dates[-1]]
        self.assertEqual(last_d["matchday_number"], len(dates))
        self.assertEqual(last_d["date_formatted"], "02.09.26")
        self.assertEqual(last_d["short_label"], f"{len(dates)}. Spieltag")

    def test_compute_historical_snapshots(self):
        snapshots = compute_historical_snapshots(self.conn)
        self.assertIn("matchdays", snapshots)
        self.assertIn("months", snapshots)
        
        matchdays = snapshots["matchdays"]
        self.assertEqual(len(matchdays), 9)
        
        # Check newest matchday snapshot (top of scrollbar)
        md_newest = matchdays[0]
        self.assertEqual(md_newest["date"], "2026-09-02")
        self.assertEqual(md_newest["matchday_number"], 9)
        self.assertGreater(len(md_newest["leaderboard"]), 0)
        
        # Check oldest matchday snapshot (bottom of scrollbar)
        md_oldest = matchdays[-1]
        self.assertEqual(md_oldest["date"], "2026-07-08")
        self.assertEqual(md_oldest["matchday_number"], 1)

        # In md_newest, leaderboard is sorted by total.conservative descending
        top1 = md_newest["leaderboard"][0]
        self.assertIn("total", top1)
        self.assertIn("conservative", top1["total"])
        self.assertIn("rating", top1["total"])
        self.assertIn("rd", top1["total"])
        
        # Check months snapshots (newest first)
        months = snapshots["months"]
        self.assertEqual(len(months), 3) # September, August, Juli 2026
        self.assertEqual(months[0]["month_key"], "2026-09")
        self.assertEqual(months[1]["month_key"], "2026-08")
        self.assertEqual(months[2]["month_key"], "2026-07")
        self.assertIn("JUL 26", months[2]["month_vertical"])


if __name__ == "__main__":
    unittest.main()
