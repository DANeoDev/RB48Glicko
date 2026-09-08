"""Historical leaderboard snapshots and matchday metadata generator for time-scrollbar."""

from datetime import datetime, timedelta
from scripts.database.db_matches import get_matches, get_all_match_teams
from scripts.database.db_players import get_players
from scripts.database.db_ratings import get_calibrations
from scripts.glicko.glicko2 import Glicko2, TOTAL, BOX, HF
from scripts.glicko.glicko2_calculator import (
    prepare_glicko_table,
    glicko_table_to_ratings,
    ratings_to_glicko_table,
    group_matches_by_date,
    update_session,
)
from scripts.frontend.view_models import (
    _collect_player_match_events,
    _compute_single_game_delta,
    _compute_period_delta,
)

GERMAN_MONTHS = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April",
    5: "Mai", 6: "Juni", 7: "Juli", 8: "August",
    9: "September", 10: "Oktober", 11: "November", 12: "Dezember"
}

GERMAN_MONTHS_SHORT = {
    1: "JAN", 2: "FEB", 3: "MÄR", 4: "APR",
    5: "MAI", 6: "JUN", 7: "JUL", 8: "AUG",
    9: "SEP", 10: "OKT", 11: "NOV", 12: "DEZ"
}


def get_matchday_metadata_map(connection, matches=None):
    """
    Return a mapping from match date (YYYY-MM-DD) to rich matchday metadata.
    Matchday number resets per calendar year (season).
    """
    if matches is None:
        matches = get_matches(connection)
    sessions = group_matches_by_date(matches)
    sorted_dates = sorted(sessions.keys())

    years = {}
    for date_str in sorted_dates:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        years.setdefault(dt.year, []).append(date_str)

    metadata_map = {}
    for year, dates in years.items():
        for idx, date_str in enumerate(dates, start=1):
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            session_matches = sessions[date_str]
            pitches = sorted(list(set(m["pitch"].upper() for m in session_matches)))
            month_num = dt.month
            month_name = GERMAN_MONTHS.get(month_num, dt.strftime("%B"))
            month_short = GERMAN_MONTHS_SHORT.get(month_num, dt.strftime("%b").upper())
            two_digit_year = dt.strftime("%y")

            metadata_map[date_str] = {
                "date": date_str,
                "date_formatted": dt.strftime("%d.%m.%y"),
                "season": year,
                "matchday_number": idx,
                "label": f"Saison {year} · {idx}. Spieltag",
                "short_label": f"{idx}. Spieltag",
                "month_key": dt.strftime("%Y-%m"),
                "month_label": f"{month_name} {year}",
                "month_vertical": f"{month_short} {two_digit_year}",
                "matches_count": len(session_matches),
                "pitch_types": pitches,
            }

    return metadata_map


def _compute_snapshot_deltas(
    evts_up_to_date: list[dict],
    date_str: str,
    cutoff_month: str,
    cutoff_quarter: str,
    cutoff_year: str,
    pkey: str,
    curr_r: float,
    curr_rd: float,
    curr_c: float,
) -> dict:
    """
    Compute accurate backward-looking deltas for a historical snapshot date:
    - 'game': Delta for the session matches played on date_str (or 0 if player didn't play that session).
    - 'month': Delta across matches in the 30 days leading up to date_str.
    - 'quarter': Delta across matches in the 90 days leading up to date_str.
    - 'year': Delta across matches in the 365 days leading up to date_str.
    """
    def _calc_subset_delta(subset_evts: list[dict]) -> dict:
        if not subset_evts:
            return {
                "conservative": 0.0,
                "rating": 0.0,
                "rd": 0.0,
                "games": 0,
                "wins": 0,
                "losses": 0,
                "win_percent": 0.0,
            }
        g = len(subset_evts)
        w = sum(1 for e in subset_evts if e.get("is_win"))
        losses = sum(1 for e in subset_evts if e.get("is_loss"))
        wp = round((w / g * 100.0), 1) if g > 0 else 0.0

        first_e = subset_evts[0]
        first_b_r = first_e["rating_before_total"] if pkey == TOTAL else first_e["rating_before_pitch"]
        first_b_rd = first_e["rd_before_total"] if pkey == TOTAL else first_e["rd_before_pitch"]
        if first_b_r is not None and first_b_rd is not None:
            first_b_c = first_b_r - 3.0 * first_b_rd
            delta_r = curr_r - first_b_r
            delta_rd = curr_rd - first_b_rd
            delta_c = curr_c - first_b_c
        else:
            delta_r = 0.0
            delta_rd = 0.0
            delta_c = 0.0

        return {
            "conservative": delta_c,
            "rating": delta_r,
            "rd": delta_rd,
            "games": g,
            "wins": w,
            "losses": losses,
            "win_percent": wp,
        }

    session_evts = [e for e in evts_up_to_date if e["date"] == date_str]
    month_evts = [e for e in evts_up_to_date if e["date"] >= cutoff_month]
    quarter_evts = [e for e in evts_up_to_date if e["date"] >= cutoff_quarter]
    year_evts = [e for e in evts_up_to_date if e["date"] >= cutoff_year]

    return {
        "game": _calc_subset_delta(session_evts),
        "month": _calc_subset_delta(month_evts),
        "quarter": _calc_subset_delta(quarter_evts),
        "year": _calc_subset_delta(year_evts),
    }


def compute_historical_snapshots(connection):
    """
    Compute chronological rating and stats snapshots after each matchday (session),
    plus aggregated month-end snapshots.
    """
    matches = get_matches(connection)
    players = get_players(connection)
    calibrations = get_calibrations(connection)
    metadata_map = get_matchday_metadata_map(connection, matches=matches)
    sessions = group_matches_by_date(matches)
    sorted_dates = sorted(sessions.keys())
    match_teams_map = get_all_match_teams(connection)

    prepared = prepare_glicko_table(connection, matches, calibrations, match_teams_map=match_teams_map)
    ratings = glicko_table_to_ratings(prepared)
    engine = Glicko2()

    sorted_matches_all = sorted(matches.values(), key=lambda m: (m["date"], m["match_id"]))
    player_events = _collect_player_match_events(connection, sorted_matches_all, players)

    # Cumulative stats tracking per player and pitch
    cumulative_stats = {}
    for pid in players:
        cumulative_stats[pid] = {
            TOTAL: {"games": 0, "wins": 0, "losses": 0, "draws": 0},
            BOX: {"games": 0, "wins": 0, "losses": 0, "draws": 0},
            HF: {"games": 0, "wins": 0, "losses": 0, "draws": 0},
        }

    matchdays_snapshots = []

    for date_str in sorted_dates:
        session_matches = sessions[date_str]
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        cutoff_month = (dt - timedelta(days=30)).strftime("%Y-%m-%d")
        cutoff_quarter = (dt - timedelta(days=90)).strftime("%Y-%m-%d")
        cutoff_year = (dt - timedelta(days=365)).strftime("%Y-%m-%d")

        # 1. Update cumulative match stats with this session's matches
        for match in session_matches:
            match_id = match["match_id"]
            pitch_type = match["pitch"].lower()
            team_a, team_b = match_teams_map.get(match_id, ([], []))
            ga = match["goals_a"]
            gb = match["goals_b"]

            # Team A results
            for pid in team_a:
                if pid not in cumulative_stats:
                    continue
                cumulative_stats[pid][TOTAL]["games"] += 1
                if pitch_type in cumulative_stats[pid]:
                    cumulative_stats[pid][pitch_type]["games"] += 1

                if ga > gb:
                    cumulative_stats[pid][TOTAL]["wins"] += 1
                    if pitch_type in cumulative_stats[pid]:
                        cumulative_stats[pid][pitch_type]["wins"] += 1
                elif ga < gb:
                    cumulative_stats[pid][TOTAL]["losses"] += 1
                    if pitch_type in cumulative_stats[pid]:
                        cumulative_stats[pid][pitch_type]["losses"] += 1
                else:
                    cumulative_stats[pid][TOTAL]["draws"] += 1
                    if pitch_type in cumulative_stats[pid]:
                        cumulative_stats[pid][pitch_type]["draws"] += 1

            # Team B results
            for pid in team_b:
                if pid not in cumulative_stats:
                    continue
                cumulative_stats[pid][TOTAL]["games"] += 1
                if pitch_type in cumulative_stats[pid]:
                    cumulative_stats[pid][pitch_type]["games"] += 1

                if gb > ga:
                    cumulative_stats[pid][TOTAL]["wins"] += 1
                    if pitch_type in cumulative_stats[pid]:
                        cumulative_stats[pid][pitch_type]["wins"] += 1
                elif gb < ga:
                    cumulative_stats[pid][TOTAL]["losses"] += 1
                    if pitch_type in cumulative_stats[pid]:
                        cumulative_stats[pid][pitch_type]["losses"] += 1
                else:
                    cumulative_stats[pid][TOTAL]["draws"] += 1
                    if pitch_type in cumulative_stats[pid]:
                        cumulative_stats[pid][pitch_type]["draws"] += 1

        # 2. Update Glicko ratings for this session
        update_session(connection, session_matches, ratings, engine, match_teams_map=match_teams_map)
        current_ratings_dict = ratings_to_glicko_table(ratings)

        # 3. Assemble leaderboard snapshot with historical deltas
        leaderboard = []
        for pid, pdata in players.items():
            r_data = current_ratings_dict.get(pid, {})
            p_stats = cumulative_stats.get(pid, {})

            player_entry = {
                "player_id": pid,
                "alias": pdata["aliases"][0] if pdata.get("aliases") else f"Player {pid}",
            }

            for pkey in (TOTAL, BOX, HF):
                r_item = r_data.get(pkey, {"rating": 1500.0, "rd": 350.0, "sigma": 0.06})
                s_item = p_stats.get(pkey, {"games": 0, "wins": 0, "losses": 0, "draws": 0})
                r_val = r_item["rating"]
                rd_val = r_item["rd"]
                c_val = r_val - 3.0 * rd_val
                g = s_item["games"]
                w = s_item["wins"]
                losses = s_item["losses"]
                wp = round((w / g * 100.0), 1) if g > 0 else 0.0

                all_p_evts = player_events.get(pid, {}).get(pkey, [])
                evts_up_to_date = [e for e in all_p_evts if e["date"] <= date_str]

                deltas = _compute_snapshot_deltas(
                    evts_up_to_date,
                    date_str,
                    cutoff_month,
                    cutoff_quarter,
                    cutoff_year,
                    pkey,
                    r_val,
                    rd_val,
                    c_val,
                )

                player_entry[pkey] = {
                    "rating": round(r_val, 1),
                    "rd": round(rd_val, 1),
                    "conservative": round(c_val, 1),
                    "games": g,
                    "wins": w,
                    "losses": losses,
                    "win_percent": wp,
                    "deltas": deltas,
                }

            leaderboard.append(player_entry)

        # Sort leaderboard by total conservative rating descending
        leaderboard.sort(key=lambda p: p[TOTAL]["conservative"], reverse=True)

        meta = metadata_map[date_str]
        matchday_snapshot = {
            "id": f"d-{date_str}",
            "type": "matchday",
            "date": date_str,
            "date_formatted": meta["date_formatted"],
            "season": meta["season"],
            "matchday_number": meta["matchday_number"],
            "label": meta["label"],
            "short_label": meta["short_label"],
            "month_key": meta["month_key"],
            "month_label": meta["month_label"],
            "month_vertical": meta["month_vertical"],
            "matches_count": meta["matches_count"],
            "pitch_types": meta["pitch_types"],
            "leaderboard": leaderboard,
        }
        matchdays_snapshots.append(matchday_snapshot)

    # 4. Group into month-end snapshots
    month_groups = {}
    for snap in matchdays_snapshots:
        month_groups.setdefault(snap["month_key"], []).append(snap)

    months_snapshots = []
    for month_key in sorted(month_groups.keys()):
        m_snaps = month_groups[month_key]
        last_snap = m_snaps[-1]  # state at the end of the month
        total_month_matches = sum(s["matches_count"] for s in m_snaps)
        all_pitches = sorted(list(set(p for s in m_snaps for p in s["pitch_types"])))

        months_snapshots.append({
            "id": f"m-{month_key}",
            "type": "month",
            "month_key": month_key,
            "month_label": last_snap["month_label"],
            "month_vertical": last_snap["month_vertical"],
            "date": last_snap["date"],
            "date_formatted": last_snap["date_formatted"],
            "label": f"Monats-Endstand {last_snap['month_label']}",
            "short_label": last_snap["month_label"],
            "matchdays_count": len(m_snaps),
            "matches_count": total_month_matches,
            "pitch_types": all_pitches,
            "leaderboard": last_snap["leaderboard"],
        })

    # Reverse so newest is at top (index 0) and oldest at bottom (index -1)
    matchdays_snapshots.reverse()
    months_snapshots.reverse()

    return {
        "matchdays": matchdays_snapshots,
        "months": months_snapshots,
    }

