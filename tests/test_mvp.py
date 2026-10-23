import unittest
import os
import tempfile
from pathlib import Path
import shutil

from scripts.accounts.auth import register_user
from scripts.accounts.database import (
    approve_user,
    get_accounts_connection,
    mark_email_verified,
    record_match_mvp_votes,
    get_user_match_mvp_votes,
    get_user_match_mvp_vote,
    get_user_mvp_votes_for_matches,
    get_match_mvp_podium,
    get_match_mvp_winners,
    get_mvp_medal_table,
    link_user_to_player,
)
from scripts.database.database import main as init_database
from web.app import create_app
from web.services.cache import invalidate_stats_cache


class TestMVPVotingAndMedals(unittest.TestCase):
    def setUp(self):
        invalidate_stats_cache()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db = Path(self.temp_dir.name) / "test_rb48.db"
        self.test_accounts_db = Path(self.temp_dir.name) / "test_accounts.db"

        os.environ["RB48_DATABASE_FILE"] = str(self.test_db)
        os.environ["RB48_ACCOUNTS_DATABASE_FILE"] = str(self.test_accounts_db)
        init_database()

        self.conn = get_accounts_connection()
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.conn.close()
        invalidate_stats_cache()
        os.environ.pop("RB48_DATABASE_FILE", None)
        os.environ.pop("RB48_ACCOUNTS_DATABASE_FILE", None)
        self.temp_dir.cleanup()

    def create_user(self, role="user", linked_player_id=None):
        u_name = f"user_{os.urandom(4).hex()}"
        user_id, _ = register_user(u_name, f"{u_name}@example.com", "SecretPass123!")
        conn = get_accounts_connection()
        try:
            mark_email_verified(conn, user_id)
            approve_user(conn, user_id)
            if linked_player_id:
                link_user_to_player(conn, user_id, linked_player_id)
        finally:
            conn.close()
        return user_id

    def test_record_and_get_ranked_votes(self):
        u1 = self.create_user(linked_player_id=1)
        u2 = self.create_user(linked_player_id=2)

        # User 1 votes for 10 (Gold), 20 (Silver), 30 (Bronze)
        record_match_mvp_votes(self.conn, "M001", u1, [10, 20, 30])
        votes = get_user_match_mvp_votes(self.conn, "M001", u1)
        self.assertEqual(votes, [10, 20, 30])
        self.assertEqual(get_user_match_mvp_vote(self.conn, "M001", u1), 10)

        # User 2 votes for only 1 player
        record_match_mvp_votes(self.conn, "M001", u2, [10])
        votes2 = get_user_match_mvp_votes(self.conn, "M001", u2)
        self.assertEqual(votes2, [10])

        # User 1 updates their vote
        record_match_mvp_votes(self.conn, "M001", u1, [20, 10])
        updated_votes = get_user_match_mvp_votes(self.conn, "M001", u1)
        self.assertEqual(updated_votes, [20, 10])

        # Multi-match fetch
        all_votes = get_user_mvp_votes_for_matches(self.conn, u1, ["M001", "M002"])
        self.assertEqual(all_votes.get("M001"), [20, 10])

    def test_podium_calculation_and_tie_breaking(self):
        u1 = self.create_user(linked_player_id=1)
        u2 = self.create_user(linked_player_id=2)
        u3 = self.create_user(linked_player_id=3)

        # Match M1:
        # User 1: 1st=10, 2nd=20, 3rd=30
        # User 2: 1st=10, 2nd=30, 3rd=20
        # User 3: 1st=20, 2nd=10, 3rd=30
        #
        # Totals:
        # Player 10: total=3, rank1=2, rank2=1, rank3=0
        # Player 20: total=3, rank1=1, rank2=1, rank3=1
        # Player 30: total=3, rank1=0, rank2=1, rank3=2
        #
        # Tie-breaker on rank1: Player 10 > Player 20 > Player 30
        # Gold: [10], Silver: [20], Bronze: [30]
        record_match_mvp_votes(self.conn, "M1", u1, [10, 20, 30])
        record_match_mvp_votes(self.conn, "M1", u2, [10, 30, 20])
        record_match_mvp_votes(self.conn, "M1", u3, [20, 10, 30])

        podium_map = get_match_mvp_podium(self.conn, ["M1"])
        podium = podium_map["M1"]
        self.assertEqual(podium["gold"], [10])
        self.assertEqual(podium["silver"], [20])
        self.assertEqual(podium["bronze"], [30])

        winners = get_match_mvp_winners(self.conn, ["M1"])
        self.assertEqual(winners["M1"], [10])

    def test_podium_exact_ties(self):
        u1 = self.create_user(linked_player_id=1)
        u2 = self.create_user(linked_player_id=2)

        # Match M2: Player 30 has 2 total votes (two 2nd place), players 10 and 20 each have 1 vote (1st place)
        record_match_mvp_votes(self.conn, "M2", u1, [10, 30])
        record_match_mvp_votes(self.conn, "M2", u2, [20, 30])

        podium_map = get_match_mvp_podium(self.conn, ["M2"])
        podium = podium_map["M2"]
        self.assertEqual(podium["gold"], [30])
        self.assertEqual(sorted(podium["silver"]), [10, 20])
        self.assertEqual(podium["bronze"], [])

    def test_medal_table_aggregation(self):
        u1 = self.create_user(linked_player_id=1)

        # Match M1: Gold=10, Silver=20, Bronze=30
        record_match_mvp_votes(self.conn, "M1", u1, [10, 20, 30])
        # Match M2: Gold=10, Silver=30, Bronze=20
        record_match_mvp_votes(self.conn, "M2", u1, [10, 30, 20])
        # Match M3: Gold=20, Silver=10, Bronze=40
        record_match_mvp_votes(self.conn, "M3", u1, [20, 10, 40])

        matches_dict = {"M1": {}, "M2": {}, "M3": {}}
        table = get_mvp_medal_table(self.conn, matches_dict)

        # Player 10: Gold=2, Silver=1, Bronze=0 -> Total=3, Points=2*3 + 1*2 = 8 (Rank 1)
        # Player 20: Gold=1, Silver=1, Bronze=1 -> Total=3, Points=1*3 + 1*2 + 1*1 = 6 (Rank 2)
        # Player 30: Gold=0, Silver=1, Bronze=1 -> Total=2, Points=0*3 + 1*2 + 1*1 = 3 (Rank 3)
        # Player 40: Gold=0, Silver=0, Bronze=1 -> Total=1, Points=0*3 + 0*2 + 1*1 = 1 (Rank 4)
        self.assertEqual(len(table), 4)
        self.assertEqual(table[0]["player_id"], 10)
        self.assertEqual(table[0]["gold"], 2)
        self.assertEqual(table[0]["silver"], 1)
        self.assertEqual(table[0]["bronze"], 0)
        self.assertEqual(table[0]["total_medals"], 3)
        self.assertEqual(table[0]["medal_score"], 8)
        self.assertEqual(table[0]["rank"], 1)

        self.assertEqual(table[1]["player_id"], 20)
        self.assertEqual(table[1]["gold"], 1)
        self.assertEqual(table[1]["rank"], 2)

        # Filtered to only M1
        table_m1 = get_mvp_medal_table(self.conn, matches_dict, filtered_match_ids=["M1"])
        self.assertEqual(len(table_m1), 3)
        self.assertEqual(table_m1[0]["player_id"], 10)
        self.assertEqual(table_m1[0]["gold"], 1)

    def test_mvp_medals_route(self):
        u1 = self.create_user(linked_player_id=1)
        with self.client.session_transaction() as sess:
            sess["user_id"] = u1
            sess["user_role"] = "user"
            sess["is_approved"] = 1

        resp = self.client.get("/stats/mvp-medals")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"MVP-Medaillenspiegel", resp.data)

    def test_box_appointments_deduplicated_in_medal_table(self):
        """A Box evening with multiple matches (e.g. game 1 and game 2) awards exactly 1 set of medals in the medal table."""
        u1 = self.create_user(linked_player_id=1)

        # Evening of 2024-05-01 has 2 Box games
        mid1 = "2024-05-01-1"
        mid2 = "2024-05-01-2"
        record_match_mvp_votes(self.conn, mid1, u1, [10, 20, 30])

        matches_dict = {
            mid1: {"match_id": mid1, "date": "2024-05-01", "pitch": "box"},
            mid2: {"match_id": mid2, "date": "2024-05-01", "pitch": "box"},
        }

        # Query medal table with both matches included
        table = get_mvp_medal_table(self.conn, matches_dict, filtered_match_ids=[mid1, mid2])
        self.assertEqual(len(table), 3)
        self.assertEqual(table[0]["player_id"], 10)
        self.assertEqual(table[0]["gold"], 1)  # Only 1 gold awarded for the evening!
        self.assertEqual(table[0]["total_medals"], 1)

    def test_self_voting_rejected_in_record_votes(self):
        """User cannot vote for themselves in record_match_mvp_votes."""
        u1 = self.create_user(linked_player_id=10)
        with self.assertRaises(ValueError) as ctx:
            record_match_mvp_votes(self.conn, "M001", u1, [10, 20])
        self.assertIn("selbst", str(ctx.exception))

    def test_legacy_vs_weighted_scoring_systems(self):
        """
        Verify that:
        1. Historical matches (< 2026-10-23): sorted by total_votes first.
           Player with 4 votes (1G, 1S, 2B) beats player with 3 votes (3G).
        2. Future matches (>= 2026-10-23): sorted by 4-3-2 points first.
           Player with 3 votes (3G = 12 pts) beats player with 4 votes (1G, 1S, 2B = 11 pts).
        3. Equal points tie-break on future matches: rank1 > rank2 > rank3 > total_votes.
           Player with 1G (4 pts, 1 rank1) beats player with 2B (4 pts, 0 rank1).
        """
        u1 = self.create_user(linked_player_id=1)
        u2 = self.create_user(linked_player_id=2)
        u3 = self.create_user(linked_player_id=3)
        u4 = self.create_user(linked_player_id=4)
        u5 = self.create_user(linked_player_id=5)

        # Player 10: 3 votes, all 1st place (Gold)
        #   -> Legacy: 3 votes.
        #   -> Weighted: 3 * 4 = 12 pts.
        # Player 20: 4 votes (1x 1st, 1x 2nd, 2x 3rd)
        #   -> Legacy: 4 votes.
        #   -> Weighted: 1*4 + 1*3 + 2*2 = 11 pts.

        # --- 1. Historical Match: 2026-07-08-1 (Legacy) ---
        legacy_id = "2026-07-08-1"
        record_match_mvp_votes(self.conn, legacy_id, u1, [10])
        record_match_mvp_votes(self.conn, legacy_id, u2, [10])
        record_match_mvp_votes(self.conn, legacy_id, u3, [10])
        record_match_mvp_votes(self.conn, legacy_id, u4, [20, 99, 98])
        record_match_mvp_votes(self.conn, legacy_id, u5, [99, 20, 98])

        # Let's add 2 bronze votes for Player 20 from u1 and u2 in legacy match:
        # Actually, let's re-record with clean ballots:
        record_match_mvp_votes(self.conn, legacy_id, u1, [10, 91, 20])  # 10 gets Gold, 20 gets Bronze
        record_match_mvp_votes(self.conn, legacy_id, u2, [10, 92, 20])  # 10 gets Gold, 20 gets Bronze
        record_match_mvp_votes(self.conn, legacy_id, u3, [10])          # 10 gets Gold
        record_match_mvp_votes(self.conn, legacy_id, u4, [20])          # 20 gets Gold
        record_match_mvp_votes(self.conn, legacy_id, u5, [93, 20])      # 20 gets Silver
        # Totals for legacy_id:
        # Player 10: 3 votes (3 rank1) -> 3 votes, 12 pts
        # Player 20: 4 votes (1 rank1, 1 rank2, 2 rank3) -> 4 votes, 11 pts

        legacy_podium = get_match_mvp_podium(self.conn, [legacy_id])[legacy_id]
        self.assertEqual(legacy_podium["scoring_system"], "legacy_count")
        # Under legacy count, 20 (4 votes) beats 10 (3 votes)
        self.assertEqual(legacy_podium["gold"], [20])
        self.assertEqual(legacy_podium["silver"], [10])

        # --- 2. Future Match: 2026-10-28-1 (Weighted 4-3-2) ---
        future_id = "2026-10-28-1"
        record_match_mvp_votes(self.conn, future_id, u1, [10, 91, 20])
        record_match_mvp_votes(self.conn, future_id, u2, [10, 92, 20])
        record_match_mvp_votes(self.conn, future_id, u3, [10])
        record_match_mvp_votes(self.conn, future_id, u4, [20])
        record_match_mvp_votes(self.conn, future_id, u5, [93, 20])

        future_podium = get_match_mvp_podium(self.conn, [future_id])[future_id]
        self.assertEqual(future_podium["scoring_system"], "weighted_4_3_2")
        # Under 4-3-2 points, 10 (12 pts) beats 20 (11 pts)
        self.assertEqual(future_podium["gold"], [10])
        self.assertEqual(future_podium["silver"], [20])

        # --- 3. Tie-breaking on points: 1G (4 pts) vs 2B (4 pts) ---
        tie_id = "2026-11-01-1"
        # Player 30 gets 1x Gold (4 pts, 1 rank1)
        # Player 40 gets 2x Bronze (4 pts, 0 rank1)
        record_match_mvp_votes(self.conn, tie_id, u1, [30, 99, 40])
        record_match_mvp_votes(self.conn, tie_id, u2, [99, 98, 40])

        tie_podium = get_match_mvp_podium(self.conn, [tie_id])[tie_id]
        self.assertEqual(tie_podium["scoring_system"], "weighted_4_3_2")
        # 30 and 40 both have 4 points, but 30 has 1 rank1 while 40 has 0 rank1 -> 30 wins silver over 40 (or gold after 99)
        self.assertEqual(tie_podium["gold"], [99])  # 99 has 1G (4) + 1S (3) = 7 pts
        self.assertEqual(tie_podium["silver"], [30])  # 30 has 4 pts (1G)
        self.assertEqual(tie_podium["bronze"], [40])  # 40 has 4 pts (2B)


if __name__ == "__main__":
    unittest.main()

