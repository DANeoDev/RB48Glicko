from datetime import datetime, timedelta
import time
import unittest

from scripts.accounts.auth import register_user
from scripts.accounts.database import approve_user, get_accounts_connection, mark_email_verified, update_user_role
from scripts.planner.database import (
    add_guest_rsvp,
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
        self.app = app
        self.client = self.app.test_client()
        self.conn = get_planner_connection()

    def tearDown(self):
        self.conn.close()

    def test_create_events_capacity_defaults(self):
        box_id = create_event(self.conn, "2026-10-10 18:30", "box", title="Saturday Box")
        hf_id = create_event(self.conn, "2026-10-12 18:30", "hf", title="Monday HF")

        box_event = get_event_by_id(self.conn, box_id)
        hf_event = get_event_by_id(self.conn, hf_id)

        self.assertEqual(box_event["max_players"], 12)
        self.assertEqual(hf_event["max_players"], 18)

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
        visitor_guest_id = add_guest_rsvp(self.conn, event_id, "Dennis", registered_by_user_id=None, registered_by_name=None)
        attendees = [dict(a) for a in get_event_attendees(self.conn, event_id)]
        self.assertEqual(attendees[0]["name"], "Dennis (Guest)")

        # 2. Member adding multiple guests (Konsti +1, Konsti +2)
        add_guest_rsvp(self.conn, event_id, "Max", registered_by_user_id=50, registered_by_name="Konsti")
        add_guest_rsvp(self.conn, event_id, "Ingo", registered_by_user_id=50, registered_by_name="Konsti")

        updated = [dict(a) for a in get_event_attendees(self.conn, event_id)]
        self.assertEqual(updated[1]["name"], "Max (Konsti +1)")
        self.assertEqual(updated[2]["name"], "Ingo (Konsti +2)")

    def test_planner_routes_integration(self):
        # Create user
        unique_name = f"planner_user_{int(time.time() * 1000000)}"
        user_id, _ = register_user(unique_name, f"{unique_name}@example.com", "pass12345")
        acc_conn = get_accounts_connection()
        try:
            mark_email_verified(acc_conn, user_id)
            approve_user(acc_conn, user_id, approved=True)
        finally:
            acc_conn.close()

        # Create past Sunday event so guest registration is open
        past_event_id = create_event(self.conn, (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M"), "box")

        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        # 1. Member self-RSVP attend
        resp = self.client.post(f"/planner/{past_event_id}/rsvp", data={"status": "attending"}, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # 2. Update attendance name
        name_resp = self.client.post("/settings/attendance-name", data={"attendance_name": "ProKonsti"}, follow_redirects=True)
        self.assertEqual(name_resp.status_code, 200)

        # 3. Add a guest
        guest_resp = self.client.post(f"/planner/{past_event_id}/guest", data={"guest_name": "Lukas"}, follow_redirects=True)
        self.assertEqual(guest_resp.status_code, 200)
        self.assertIn(b"Lukas (ProKonsti +1)", guest_resp.data)

        # 4. View /planner page
        get_resp = self.client.get("/planner")
        self.assertEqual(get_resp.status_code, 200)
        self.assertIn(b"Attendance Planner", get_resp.data)


if __name__ == "__main__":
    unittest.main()
