from datetime import datetime, timedelta
import os
from pathlib import Path
import tempfile
import time
import unittest

from scripts.accounts.auth import register_user
from scripts.accounts.database import (
    approve_player_link,
    approve_user,
    get_accounts_connection,
    get_user_by_id,
    mark_email_verified,
    reject_player_link,
    request_player_link,
    update_user_role,
)
from scripts.planner.database import (
    add_guest_rsvp,
    add_standard_wednesday_events,
    backup_and_clear_all_events,
    cancel_user_rsvp,
    create_event,
    get_event_attendees,
    get_event_by_id,
    get_planner_connection,
    get_upcoming_events,
    remove_attendee,
    set_user_rsvp,
)
from web.app import app
from web.routes.planner import calculate_guest_unlock_time, format_event_view_data, is_guest_registration_unlocked


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_planner_db = Path(self.temp_dir.name) / "test_planner.db"
        self.test_accounts_db = Path(self.temp_dir.name) / "test_accounts.db"

        os.environ["RB48_PLANNER_DATABASE_FILE"] = str(self.test_planner_db)
        os.environ["RB48_ACCOUNTS_DATABASE_FILE"] = str(self.test_accounts_db)

        self.app = app
        self.client = self.app.test_client()
        self.conn = get_planner_connection()

    def tearDown(self):
        self.conn.close()
        os.environ.pop("RB48_PLANNER_DATABASE_FILE", None)
        os.environ.pop("RB48_ACCOUNTS_DATABASE_FILE", None)
        self.temp_dir.cleanup()

    def test_create_events_capacity_defaults(self):
        box_id = create_event(self.conn, "2026-10-10 18:30", "box", title="Saturday Box")
        hf_id = create_event(self.conn, "2026-10-12 18:30", "hf", title="Monday HF")

        box_event = get_event_by_id(self.conn, box_id)
        hf_event = get_event_by_id(self.conn, hf_id)

        self.assertEqual(box_event["max_players"], 12)
        self.assertEqual(hf_event["max_players"], 18)

    def test_add_standard_wednesday_events_alternating(self):
        # Seed initial box event on a Tuesday
        create_event(self.conn, "2026-09-08 20:00", "box")

        created_ids = add_standard_wednesday_events(self.conn, count=4)
        self.assertEqual(len(created_ids), 4)

        events = get_upcoming_events(self.conn, limit=10)
        # 1st is the Tuesday BOX, followed by the 4 Wednesdays:
        # Since last was BOX, the 1st new Wednesday must be HF!
        self.assertEqual(events[1]["pitch"], "hf")
        self.assertEqual(events[1]["max_players"], 18)
        self.assertIn("Halbfeld", events[1]["location"])
        self.assertIn("20:30", events[1]["event_date"])

        # 2nd Wednesday must be BOX
        self.assertEqual(events[2]["pitch"], "box")
        self.assertEqual(events[2]["max_players"], 12)
        self.assertIn("Soccerbox", events[2]["location"])
        self.assertIn("20:00", events[2]["event_date"])

        # 3rd Wednesday must be HF
        self.assertEqual(events[3]["pitch"], "hf")
        # 4th Wednesday must be BOX
        self.assertEqual(events[4]["pitch"], "box")

    def test_chronological_ordering_and_waiting_list(self):
        event_id = create_event(self.conn, "2026-11-01 18:30", "box", max_players=3)

        # Add 4 players
        set_user_rsvp(self.conn, event_id, user_id=101, display_name="Player 1", status="attending")
        time.sleep(0.01)
        set_user_rsvp(self.conn, event_id, user_id=102, display_name="Player 2", status="attending")
        time.sleep(0.01)
        set_user_rsvp(self.conn, event_id, user_id=103, display_name="Player 3", status="attending")
        time.sleep(0.01)
        set_user_rsvp(self.conn, event_id, user_id=104, display_name="Player 4", status="attending")

        attendees = [dict(a) for a in get_event_attendees(self.conn, event_id)]
        event = dict(get_event_by_id(self.conn, event_id))
        view_data = format_event_view_data(event, None, attendees)

        # Capacity is 3 -> active roster has 3, waiting list has 1
        self.assertEqual(len(view_data["active_roster"]), 3)
        self.assertEqual(len(view_data["waiting_list"]), 1)
        self.assertEqual(view_data["active_roster"][0]["name"], "Player 1")
        self.assertEqual(view_data["waiting_list"][0]["name"], "Player 4")

        # Now Player 2 cancels -> Player 4 should automatically move up to active roster!
        cancel_user_rsvp(self.conn, event_id, user_id=102)

        updated_attendees = [dict(a) for a in get_event_attendees(self.conn, event_id)]
        updated_view = format_event_view_data(event, None, updated_attendees)

        self.assertEqual(len(updated_view["active_roster"]), 3)
        self.assertEqual(len(updated_view["waiting_list"]), 0)
        self.assertEqual([p["name"] for p in updated_view["active_roster"]], ["Player 1", "Player 3", "Player 4"])

    def test_sunday_unlock_time_calculation(self):
        # Tuesday match on 2026-09-08 -> preceding Sunday is 2026-09-06 00:00:00
        tuesday_match = "2026-09-08 18:30"
        unlock_sunday = calculate_guest_unlock_time(tuesday_match)
        self.assertEqual(unlock_sunday.strftime("%Y-%m-%d %H:%M:%S"), "2026-09-06 00:00:00")

        # Sunday match on 2026-09-13 -> Sunday is 2026-09-13 00:00:00
        sunday_match = "2026-09-13 18:30"
        unlock_same_sunday = calculate_guest_unlock_time(sunday_match)
        self.assertEqual(unlock_same_sunday.strftime("%Y-%m-%d %H:%M:%S"), "2026-09-13 00:00:00")

    def test_guest_suffixes(self):
        event_id = create_event(self.conn, "2026-12-01 18:30", "box")

        # 1. Visitor guest
        add_guest_rsvp(self.conn, event_id, "Dennis", registered_by_user_id=None, registered_by_name=None)
        attendees = [dict(a) for a in get_event_attendees(self.conn, event_id)]
        self.assertEqual(attendees[0]["name"], "Dennis (Guest)")

        # 2. Member adding multiple guests (Konsti +1, Konsti +2)
        add_guest_rsvp(self.conn, event_id, "Max", registered_by_user_id=50, registered_by_name="Konsti")
        add_guest_rsvp(self.conn, event_id, "Ingo", registered_by_user_id=50, registered_by_name="Konsti")

        updated = [dict(a) for a in get_event_attendees(self.conn, event_id)]
        self.assertEqual(updated[1]["name"], "Max (Konsti +1)")
        self.assertEqual(updated[2]["name"], "Ingo (Konsti +2)")

    def test_pending_player_link_workflow(self):
        unique_name = f"link_user_{int(time.time() * 1000000)}"
        user_id, _ = register_user(unique_name, f"{unique_name}@example.com", "pass12345")
        acc_conn = get_accounts_connection()
        try:
            mark_email_verified(acc_conn, user_id)
            approve_user(acc_conn, user_id, approved=True)

            # User requests link to player 2
            request_player_link(acc_conn, user_id, 2)
            u = get_user_by_id(acc_conn, user_id)
            self.assertEqual(u["pending_player_id"], 2)
            self.assertIsNone(u["player_id"])

            # Webmaster approves link
            approve_player_link(acc_conn, user_id)
            u = get_user_by_id(acc_conn, user_id)
            self.assertIsNone(u["pending_player_id"])
            self.assertEqual(u["player_id"], 2)
        finally:
            acc_conn.close()

    def test_webmaster_clear_all_dates_with_backup_and_2step_verification(self):
        # 1. Create webmaster user
        unique_name = f"wm_user_{int(time.time() * 1000000)}"
        wm_id, _ = register_user(unique_name, f"{unique_name}@example.com", "pass12345")
        acc_conn = get_accounts_connection()
        try:
            mark_email_verified(acc_conn, wm_id)
            approve_user(acc_conn, wm_id, approved=True)
            update_user_role(acc_conn, wm_id, "webmaster")
        finally:
            acc_conn.close()

        # Seed some events
        create_event(self.conn, "2026-10-10 20:00", "box")
        create_event(self.conn, "2026-10-17 20:30", "hf")
        self.assertEqual(len(get_upcoming_events(self.conn)), 2)

        with self.client.session_transaction() as sess:
            sess["user_id"] = wm_id

        # 2. Failed verification (only step 1 checked, wrong text)
        fail_resp = self.client.post("/planner/events/clear-all", data={"confirm_1": "yes", "confirm_2": "WRONG"}, follow_redirects=True)
        self.assertEqual(fail_resp.status_code, 200)
        self.assertIn(b"Two-step verification failed", fail_resp.data)
        self.assertEqual(len(get_upcoming_events(self.conn)), 2)

        # 3. Successful 2-step verification
        success_resp = self.client.post("/planner/events/clear-all", data={"confirm_1": "yes", "confirm_2": "CLEAR ALL DATES"}, follow_redirects=True)
        self.assertEqual(success_resp.status_code, 200)
        self.assertIn(b"archived to data/backups/upcoming_matchdates/", success_resp.data)

        # Database is now completely clean
        events_after = get_upcoming_events(self.conn)
        self.assertEqual(len(events_after), 0)

    def test_planner_routes_integration(self):
        # Create user
        unique_name = f"planner_user_{int(time.time() * 1000000)}"
        user_id, _ = register_user(unique_name, f"{unique_name}@example.com", "pass12345")
        acc_conn = get_accounts_connection()
        try:
            mark_email_verified(acc_conn, user_id)
            approve_user(acc_conn, user_id, approved=True)
            update_user_role(acc_conn, user_id, "admin")
        finally:
            acc_conn.close()

        # Create future event (2 weeks from now -> locked for normal users, but admin is exempt)
        future_date = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d %H:%M")
        future_event_id = create_event(self.conn, future_date, "box")

        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        # 1. Member self-RSVP attend
        resp = self.client.post(f"/planner/{future_event_id}/rsvp", data={"status": "attending"}, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # 2. Update profile via settings
        prof_resp = self.client.post("/settings/profile", data={"attendance_name": "ProKonsti", "player_id": "1"}, follow_redirects=True)
        self.assertEqual(prof_resp.status_code, 200)

        # 3. Admin adds a guest even though time-lock is active for normal users
        guest_resp = self.client.post(f"/planner/{future_event_id}/guest", data={"guest_name": "Lukas"}, follow_redirects=True)
        self.assertEqual(guest_resp.status_code, 200)
        self.assertIn(b"Lukas (ProKonsti +1)", guest_resp.data)

        # 4. Admin auto-seed 4 matchdays
        seed_resp = self.client.post("/planner/events/auto-seed", follow_redirects=True)
        self.assertEqual(seed_resp.status_code, 200)
        self.assertIn(b"standard Wednesday matchdays", seed_resp.data)

        # 5. View /planner page
        get_resp = self.client.get("/planner")
        self.assertEqual(get_resp.status_code, 200)
        self.assertIn(b"Attendance Planner", get_resp.data)

        # 6. Test Match Center preselection with comma-separated IDs
        mc_resp = self.client.get("/match-center?players=1,2,3")
        self.assertEqual(mc_resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
