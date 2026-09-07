"""Analysis module for computing player achievements and milestones."""

from datetime import datetime
from scripts.database.database import get_connection
from scripts.database.db_players import get_players
from scripts.database.db_ratings import get_player_rating_history
from scripts.accounts.database import (
    get_accounts_connection,
    get_approved_linked_players,
    get_user_seen_achievements,
    record_player_unlocked_achievement,
    has_player_unlocked_achievement,
)

MONTH_NAMES_DE = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember"
}

TIER_ORDER = {"platin": 4, "gold": 3, "silver": 2, "bronze": 1}


def _load_player_matches(connection, player_id):
    """Fetch and prepare active matches and expectation data for the player."""
    rows = connection.execute("""
        SELECT m.match_id, m.date, m.goals_a, m.goals_b,
               mp.player_id, mp.team
        FROM matches m
        JOIN match_players mp ON m.match_id = mp.match_id
        ORDER BY m.date ASC, m.match_id ASC
    """).fetchall()

    matches = {}
    for r in rows:
        mid = r["match_id"]
        if mid not in matches:
            matches[mid] = {
                "match_id": mid,
                "date": r["date"],
                "goals_a": r["goals_a"],
                "goals_b": r["goals_b"],
                "team_a": [],
                "team_b": []
            }
        if r["team"] == "a":
            matches[mid]["team_a"].append(r["player_id"])
        else:
            matches[mid]["team_b"].append(r["player_id"])

    # Ignore the first 5 matches of the global match history
    sorted_mids = sorted(matches.keys(), key=lambda mid: (matches[mid]["date"], matches[mid]["match_id"]))
    ignored_global_mids = set(sorted_mids[:5])
    active_global_matches = {mid: m for mid, m in matches.items() if mid not in ignored_global_mids}

    # Fetch match ratings for all players to compute team ratings and expectations
    mr_rows = connection.execute("""
        SELECT match_id, player_id, rating
        FROM match_ratings
        WHERE rating_type = 'total'
    """).fetchall()

    match_player_ratings = {}
    for mr in mr_rows:
        match_player_ratings.setdefault(mr["match_id"], {})[mr["player_id"]] = mr["rating"]

    player_matches = []
    for mid, m in sorted(active_global_matches.items(), key=lambda item: (item[1]["date"], item[1]["match_id"])):
        if player_id in m["team_a"] or player_id in m["team_b"]:
            is_team_a = player_id in m["team_a"]
            own_goals = m["goals_a"] if is_team_a else m["goals_b"]
            opp_goals = m["goals_b"] if is_team_a else m["goals_a"]
            is_win = own_goals > opp_goals
            is_loss = own_goals < opp_goals
            is_draw = own_goals == opp_goals

            # Compute estimated win prob from team average ratings in that match
            m_ratings = match_player_ratings.get(m["match_id"], {})
            team_a_r = [m_ratings[pid] for pid in m["team_a"] if pid in m_ratings]
            team_b_r = [m_ratings[pid] for pid in m["team_b"] if pid in m_ratings]

            avg_a = sum(team_a_r) / len(team_a_r) if team_a_r else 1500.0
            avg_b = sum(team_b_r) / len(team_b_r) if team_b_r else 1500.0

            own_avg = avg_a if is_team_a else avg_b
            opp_avg = avg_b if is_team_a else avg_a

            # Logistic expectation
            expected_win = 1.0 / (1.0 + 10.0 ** ((opp_avg - own_avg) / 400.0))

            own_team_ids = m["team_a"] if is_team_a else m["team_b"]
            opp_team_ids = m["team_b"] if is_team_a else m["team_a"]

            player_matches.append({
                "match_id": m["match_id"],
                "date": m["date"],
                "is_win": is_win,
                "is_loss": is_loss,
                "is_draw": is_draw,
                "goals_for": own_goals,
                "goals_against": opp_goals,
                "expected_win_prob": expected_win,
                "own_team_ids": [pid for pid in own_team_ids if pid != player_id],
                "opp_team_ids": opp_team_ids
            })

    return player_matches, active_global_matches, rows


def _eval_century_club(total_games: int) -> dict:
    century_tiers = [(100, "gold"), (50, "silver"), (25, "bronze")]
    unlocked_tier = None
    next_target = 25
    for target, tier in century_tiers:
        if total_games >= target:
            unlocked_tier = tier
            next_target = target
            break

    return {
        "id": "century_club",
        "icon": "💯",
        "title_key": "achievements.century_title",
        "tier": unlocked_tier if unlocked_tier else "locked",
        "unlocked": unlocked_tier is not None,
        "progress_text": f"{total_games} / {next_target} Spiele" if not unlocked_tier or total_games < 100 else f"{total_games} Spiele absolviert",
        "description_key": "achievements.century_desc",
        "detail_text": f"Aktuell: {total_games} Spiele absolviert"
    }


def _eval_winning_streak(active_matches: list) -> dict:
    current_w_streak = 0
    max_w_streak = 0
    for m in active_matches:
        if m["is_win"]:
            current_w_streak += 1
            if current_w_streak > max_w_streak:
                max_w_streak = current_w_streak
        else:
            current_w_streak = 0

    ws_tiers = [(20, "platin"), (12, "gold"), (8, "silver"), (4, "bronze")]
    ws_unlocked_tier = None
    for target, tier in ws_tiers:
        if max_w_streak >= target:
            ws_unlocked_tier = tier
            break

    if max_w_streak >= 20:
        ws_target = 20
    elif max_w_streak >= 12:
        ws_target = 20
    elif max_w_streak >= 8:
        ws_target = 12
    elif max_w_streak >= 4:
        ws_target = 8
    else:
        ws_target = 4

    return {
        "id": "winning_streak",
        "icon": "🔥",
        "title_key": "achievements.winning_streak_title",
        "tier": ws_unlocked_tier if ws_unlocked_tier else "locked",
        "unlocked": ws_unlocked_tier is not None,
        "progress_text": f"{max_w_streak} / {ws_target} Siege in Folge" if not ws_unlocked_tier or max_w_streak < 20 else f"{max_w_streak} Siege in Folge erreicht!",
        "description_key": "achievements.winning_streak_desc",
        "detail_text": f"Rekord-Siegesserie: {max_w_streak} Siege in Folge (aktuell: {current_w_streak})" if ws_unlocked_tier else f"Aktuelle Serie: {current_w_streak} Siege (Rekord: {max_w_streak})"
    }


def _eval_iron_man(active_matches: list, active_global_matches: dict) -> dict:
    distinct_dates = sorted(list(set(m["date"] for m in active_global_matches.values())))
    player_dates = set(m["date"] for m in active_matches)

    max_consecutive_sessions = 0
    curr_streak = 0
    for d in distinct_dates:
        if d in player_dates:
            curr_streak += 1
            if curr_streak > max_consecutive_sessions:
                max_consecutive_sessions = curr_streak
        else:
            curr_streak = 0

    iron_tiers = [(25, "platin"), (15, "gold"), (10, "silver"), (5, "bronze")]
    iron_unlocked = None
    iron_target = 5
    for target, tier in iron_tiers:
        if max_consecutive_sessions >= target:
            iron_unlocked = tier
            iron_target = target
            break

    return {
        "id": "iron_man",
        "icon": "🛡️",
        "title_key": "achievements.iron_man_title",
        "tier": iron_unlocked if iron_unlocked else "locked",
        "unlocked": iron_unlocked is not None,
        "progress_text": f"{max_consecutive_sessions} / {iron_target} Spieltage in Folge",
        "description_key": "achievements.iron_man_desc",
        "detail_text": f"Rekord: {max_consecutive_sessions} aufeinanderfolgende Spieltage"
    }


def _eval_underdog_hero(active_matches: list) -> dict:
    underdog_wins = [m for m in active_matches if m["is_win"] and m["expected_win_prob"] < 0.32]
    underdog_tier = "gold" if len(underdog_wins) >= 3 else ("silver" if len(underdog_wins) >= 2 else ("bronze" if len(underdog_wins) >= 1 else "locked"))
    return {
        "id": "underdog_hero",
        "icon": "🦸",
        "title_key": "achievements.underdog_title",
        "tier": underdog_tier,
        "unlocked": len(underdog_wins) > 0,
        "progress_text": f"{len(underdog_wins)} Underdog-Siege (<32% Chance)",
        "description_key": "achievements.underdog_desc",
        "detail_text": f"{len(underdog_wins)}x gegen statistische Quoten (< 32%) gewonnen"
    }


def _eval_weisse_wand(active_matches: list) -> dict:
    clean_sheets = [m for m in active_matches if m["is_win"] and m["goals_against"] == 0]
    cs_tiers = [(5, "gold"), (3, "silver"), (1, "bronze")]
    cs_unlocked = None
    cs_target = 1
    for target, tier in cs_tiers:
        if len(clean_sheets) >= target:
            cs_unlocked = tier
            cs_target = target
            break

    return {
        "id": "weisse_wand",
        "icon": "🧱",
        "title_key": "achievements.clean_sheet_title",
        "tier": cs_unlocked if cs_unlocked else "locked",
        "unlocked": cs_unlocked is not None,
        "progress_text": f"{len(clean_sheets)} / {cs_target} Zu-Null-Siege",
        "description_key": "achievements.clean_sheet_desc",
        "detail_text": f"{len(clean_sheets)}x ohne Gegentor gewonnen"
    }


def _eval_highest_rank(connection, player_id: int, active_matches: list, user_has_glicko_tier: bool):
    if not user_has_glicko_tier:
        return None

    if len(active_matches) == 0:
        rank_unlocked = False
        rank_tier = "locked"
        best_rank = 999
        days_at_rank_1 = 0
    else:
        all_hist = connection.execute("""
            SELECT mr.player_id, mr.rating, m.date
            FROM match_ratings mr
            JOIN matches m ON m.match_id = mr.match_id
            WHERE mr.rating_type = 'total'
            ORDER BY m.date ASC
        """).fetchall()

        active_dates = set(m["date"] for m in active_matches)
        date_groups = {}
        for r in all_hist:
            date_groups.setdefault(r["date"], []).append((r["player_id"], r["rating"]))

        best_rank = 999
        days_at_rank_1 = 0
        for d, p_list in date_groups.items():
            if d not in active_dates:
                continue
            p_list.sort(key=lambda x: -x[1])
            for rank_idx, (pid, _) in enumerate(p_list, 1):
                if pid == player_id:
                    if rank_idx < best_rank:
                        best_rank = rank_idx
                    if rank_idx == 1:
                        days_at_rank_1 += 1

        rank_unlocked = best_rank <= 3
        rank_tier = "gold" if best_rank == 1 else ("silver" if best_rank == 2 else ("bronze" if best_rank == 3 else "locked"))

    return {
        "id": "highest_rank",
        "icon": "👑",
        "title_key": "achievements.highest_rank_title",
        "tier": rank_tier,
        "unlocked": rank_unlocked,
        "progress_text": f"Beste Platzierung: #{best_rank}" if best_rank <= 50 else "Noch nicht Top 3",
        "description_key": "achievements.highest_rank_desc",
        "detail_text": f"Platz #{best_rank} erreicht ({days_at_rank_1} Spieltage auf Platz 1)" if rank_unlocked else f"Beste Platzierung: #{best_rank}"
    }


def _eval_perfect_month(active_matches: list, active_global_matches: dict, all_rows: list, reference_date=None) -> dict:
    global_months = {}
    for mid, m in active_global_matches.items():
        ym = m["date"][:7]
        global_months.setdefault(ym, set()).add(mid)

    player_month_matches = {}
    for m in active_matches:
        ym = m["date"][:7]
        player_month_matches.setdefault(ym, []).append(m)

    all_history_months = sorted(list(set(r["date"][:7] for r in all_rows)))
    first_history_month = all_history_months[0] if all_history_months else None

    current_ym = (reference_date or datetime.now()).strftime("%Y-%m")
    perfect_months = 0
    perfect_months_formatted = []
    for ym in sorted(global_months.keys()):
        if ym == first_history_month:
            continue
        if ym >= current_ym:
            continue
        g_mids = global_months[ym]
        if not g_mids:
            continue
        p_ms = player_month_matches.get(ym, [])
        p_mids = set(m["match_id"] for m in p_ms)
        if g_mids.issubset(p_mids) and all(m["is_win"] for m in p_ms):
            perfect_months += 1
            try:
                y, m_idx = map(int, ym.split("-"))
                m_name = MONTH_NAMES_DE.get(m_idx, str(m_idx))
                perfect_months_formatted.append(f"{m_name} {y}")
            except Exception:
                perfect_months_formatted.append(ym)

    pm_tier = "platin" if perfect_months >= 4 else ("gold" if perfect_months >= 3 else ("silver" if perfect_months >= 2 else ("bronze" if perfect_months >= 1 else "locked")))
    pm_target = 4 if perfect_months >= 3 else (3 if perfect_months >= 2 else (2 if perfect_months >= 1 else 1))

    if perfect_months > 0:
        months_str = ", ".join(perfect_months_formatted)
        pm_detail = f"Makelloser Monat: {months_str}" if len(perfect_months_formatted) == 1 else f"Makellose Monate: {months_str}"
        pm_progress = f"{perfect_months} / {pm_target} Perfekte Monate" if perfect_months < 4 else f"{perfect_months} Perfekte Monate erreicht!"
    else:
        pm_detail = "Alle Spiele eines abgeschlossenen Kalendermonats mitspielen und gewinnen"
        pm_progress = "0 / 1 Perfekte Monate"

    return {
        "id": "perfect_month",
        "icon": "📅",
        "title_key": "achievements.perfect_month_title",
        "tier": pm_tier,
        "unlocked": perfect_months > 0,
        "progress_text": pm_progress,
        "description_key": "achievements.perfect_month_desc",
        "detail_text": pm_detail,
        "months": perfect_months_formatted,
    }


def _eval_cursebreaker(partner_games: dict, players: dict, tier_order: dict) -> list:
    partner_broken_curses = []
    for tm_id, g_list in partner_games.items():
        loss_streak = 0
        best_curse = None
        for g in g_list:
            if g["is_loss"]:
                loss_streak += 1
            elif g["is_win"]:
                if loss_streak >= 4:
                    is_underdog = g["expected_win_prob"] <= 0.50
                    if loss_streak >= 6 and is_underdog:
                        tier = "platin"
                    elif loss_streak >= 6:
                        tier = "gold"
                    elif loss_streak == 5:
                        tier = "silver"
                    else:
                        tier = "bronze"

                    cur_event = {
                        "streak": loss_streak,
                        "tier": tier,
                        "is_underdog": is_underdog,
                        "date": g["date"],
                        "match_id": g["match_id"]
                    }
                    if best_curse is None or (tier_order[tier], loss_streak) > (tier_order[best_curse["tier"]], best_curse["streak"]):
                        best_curse = cur_event
                loss_streak = 0
            else:
                loss_streak = 0

        if best_curse is not None:
            tm_name = players[tm_id]["aliases"][0] if tm_id in players else f"Spieler {tm_id}"
            partner_broken_curses.append({
                "partner_id": tm_id,
                "partner_name": tm_name,
                "tier": best_curse["tier"],
                "streak": best_curse["streak"],
                "is_underdog": best_curse["is_underdog"],
                "date": best_curse["date"]
            })

    partner_broken_curses.sort(key=lambda x: (-tier_order[x["tier"]], -x["streak"]))

    results = []
    if partner_broken_curses:
        for p_info in partner_broken_curses:
            underdog_note = " (als Underdog)" if p_info["is_underdog"] else ""
            results.append({
                "id": f"cursebreaker_{p_info['partner_id']}",
                "icon": "⚡",
                "title": f"Fluchbrecher: {p_info['partner_name']}",
                "title_key": "achievements.cursebreaker_partner_title",
                "title_params": {"partner": p_info["partner_name"]},
                "tier": p_info["tier"],
                "unlocked": True,
                "progress_text": f"{p_info['streak']} Niederlagen in Folge beendet",
                "description_key": "achievements.cursebreaker_desc",
                "detail_text": f"Fluch mit {p_info['partner_name']} nach {p_info['streak']} gemeinsamen Niederlagen gebrochen!{underdog_note}",
                "detail_key": "achievements.cursebreaker_partner_detail",
                "detail_params": {"partner": p_info["partner_name"], "streak": p_info["streak"]}
            })
    else:
        results.append({
            "id": "cursebreaker_placeholder",
            "icon": "⚡",
            "title_key": "achievements.cursebreaker_title",
            "tier": "locked",
            "unlocked": False,
            "progress_text": "Kein gebrochener Fluch",
            "description_key": "achievements.cursebreaker_desc",
            "detail_text": "Mindestens 4 gemeinsame Niederlagen in Folge mit einem Partner, dann gemeinsam gewonnen."
        })
    return results


def _eval_buddies(partner_games: dict, players: dict, tier_order: dict) -> list:
    buddies_unlocked = []
    for tm_id, g_list in partner_games.items():
        cnt = len(g_list)
        if cnt >= 10:
            tier = "platin" if cnt >= 50 else ("gold" if cnt >= 35 else ("silver" if cnt >= 20 else "bronze"))
            tm_name = players[tm_id]["aliases"][0] if tm_id in players else f"Spieler {tm_id}"
            buddies_unlocked.append((tm_id, tm_name, cnt, tier))

    buddies_unlocked.sort(key=lambda x: (-tier_order[x[3]], -x[2]))
    results = []
    if buddies_unlocked:
        for tm_id, tm_name, cnt, tier in buddies_unlocked:
            results.append({
                "id": f"buddies_{tm_id}",
                "icon": "🤝",
                "title": f"Buddies: {tm_name}",
                "title_key": "achievements.buddies_partner_title",
                "title_params": {"partner": tm_name},
                "tier": tier,
                "unlocked": True,
                "progress_text": f"{cnt} gemeinsame Spiele",
                "description_key": "achievements.buddies_desc",
                "detail_key": "achievements.buddies_partner_detail",
                "detail_params": {"partner": tm_name, "count": cnt},
                "detail_text": f"{cnt} gemeinsame Spiele im selben Team mit {tm_name}"
            })
    else:
        results.append({
            "id": "buddies_placeholder",
            "icon": "🤝",
            "title_key": "achievements.buddies_title",
            "tier": "locked",
            "unlocked": False,
            "progress_text": "Noch keine 10 gemeinsamen Spiele",
            "description_key": "achievements.buddies_desc",
            "detail_text": "Absolviere 10, 20, 35 oder 50 Spiele im selben Team mit einem Mitspieler."
        })
    return results


def _eval_golden_duo(partner_games: dict, players: dict, tier_order: dict) -> list:
    golden_duo_unlocked = []
    for tm_id, g_list in partner_games.items():
        wins_together = len([g for g in g_list if g["is_win"]])
        if wins_together >= 10:
            tier = "platin" if wins_together >= 50 else ("gold" if wins_together >= 35 else ("silver" if wins_together >= 20 else "bronze"))
            tm_name = players[tm_id]["aliases"][0] if tm_id in players else f"Spieler {tm_id}"
            golden_duo_unlocked.append((tm_id, tm_name, wins_together, tier))

    golden_duo_unlocked.sort(key=lambda x: (-tier_order[x[3]], -x[2]))
    results = []
    if golden_duo_unlocked:
        for tm_id, tm_name, wins_cnt, tier in golden_duo_unlocked:
            results.append({
                "id": f"golden_duo_{tm_id}",
                "icon": "✨",
                "title": f"Goldenes Duo: {tm_name}",
                "title_key": "achievements.golden_duo_partner_title",
                "title_params": {"partner": tm_name},
                "tier": tier,
                "unlocked": True,
                "progress_text": f"{wins_cnt} gemeinsame Siege",
                "description_key": "achievements.golden_duo_desc",
                "detail_key": "achievements.golden_duo_partner_detail",
                "detail_params": {"partner": tm_name, "count": wins_cnt},
                "detail_text": f"{wins_cnt} gemeinsame Siege im selben Team mit {tm_name}"
            })
    else:
        results.append({
            "id": "golden_duo_placeholder",
            "icon": "✨",
            "title_key": "achievements.golden_duo_title",
            "tier": "locked",
            "unlocked": False,
            "progress_text": "Noch keine 10 gemeinsamen Siege",
            "description_key": "achievements.golden_duo_desc",
            "detail_text": "Erringe 10, 20, 35 oder 50 Siege im selben Team mit einem Mitspieler."
        })
    return results


def _eval_thick_and_thin(partner_games: dict, players: dict, tier_order: dict) -> list:
    thick_thin_unlocked = []
    for tm_id, g_list in partner_games.items():
        losses_together = len([g for g in g_list if g["is_loss"]])
        if losses_together >= 10:
            tier = "platin" if losses_together >= 50 else ("gold" if losses_together >= 35 else ("silver" if losses_together >= 20 else "bronze"))
            tm_name = players[tm_id]["aliases"][0] if tm_id in players else f"Spieler {tm_id}"
            thick_thin_unlocked.append((tm_id, tm_name, losses_together, tier))

    thick_thin_unlocked.sort(key=lambda x: (-tier_order[x[3]], -x[2]))
    results = []
    if thick_thin_unlocked:
        for tm_id, tm_name, losses_cnt, tier in thick_thin_unlocked:
            results.append({
                "id": f"thick_and_thin_{tm_id}",
                "icon": "🌧️",
                "title": f"Durch Dick und Dünn: {tm_name}",
                "title_key": "achievements.thick_and_thin_partner_title",
                "title_params": {"partner": tm_name},
                "tier": tier,
                "unlocked": True,
                "progress_text": f"{losses_cnt} gemeinsame Niederlagen",
                "description_key": "achievements.thick_and_thin_desc",
                "detail_key": "achievements.thick_and_thin_partner_detail",
                "detail_params": {"partner": tm_name, "count": losses_cnt},
                "detail_text": f"{losses_cnt} gemeinsame Niederlagen durchgestanden mit {tm_name}"
            })
    else:
        results.append({
            "id": "thick_and_thin_placeholder",
            "icon": "🌧️",
            "title_key": "achievements.thick_and_thin_title",
            "tier": "locked",
            "unlocked": False,
            "progress_text": "Noch keine 10 gemeinsamen Niederlagen",
            "description_key": "achievements.thick_and_thin_desc",
            "detail_text": "Stehe 10, 20, 35 oder 50 Niederlagen gemeinsam mit einem Mitspieler durch."
        })
    return results


def _eval_underdog_duo(partner_games: dict, players: dict, tier_order: dict) -> list:
    underdog_duo_unlocked = []
    for tm_id, g_list in partner_games.items():
        ud_wins = len([g for g in g_list if g["is_win"] and g["expected_win_prob"] < 0.32])
        if ud_wins >= 3:
            tier = "platin" if ud_wins >= 15 else ("gold" if ud_wins >= 9 else ("silver" if ud_wins >= 6 else "bronze"))
            tm_name = players[tm_id]["aliases"][0] if tm_id in players else f"Spieler {tm_id}"
            underdog_duo_unlocked.append((tm_id, tm_name, ud_wins, tier))

    underdog_duo_unlocked.sort(key=lambda x: (-tier_order[x[3]], -x[2]))
    results = []
    if underdog_duo_unlocked:
        for tm_id, tm_name, ud_cnt, tier in underdog_duo_unlocked:
            results.append({
                "id": f"underdog_duo_{tm_id}",
                "icon": "🦊",
                "title": f"Underdog-Duo: {tm_name}",
                "title_key": "achievements.underdog_duo_partner_title",
                "title_params": {"partner": tm_name},
                "tier": tier,
                "unlocked": True,
                "progress_text": f"{ud_cnt} Underdog-Siege (<32%)",
                "description_key": "achievements.underdog_duo_desc",
                "detail_key": "achievements.underdog_duo_partner_detail",
                "detail_params": {"partner": tm_name, "count": ud_cnt},
                "detail_text": f"{ud_cnt} Underdog-Siege (< 32% Siegwahrscheinlichkeit) zusammen mit {tm_name}"
            })
    else:
        results.append({
            "id": "underdog_duo_placeholder",
            "icon": "🦊",
            "title_key": "achievements.underdog_duo_title",
            "tier": "locked",
            "unlocked": False,
            "progress_text": "Noch keine 3 Underdog-Siege als Duo",
            "description_key": "achievements.underdog_duo_desc",
            "detail_text": "Erringe 3, 6, 9 oder 15 Underdog-Siege (< 32%) gemeinsam mit einem Mitspieler."
        })
    return results


def _eval_teamplayer(partner_games: dict, player_id: int, players: dict, accounts_connection) -> dict:
    acc_conn_to_use = accounts_connection
    close_local_acc = False
    if acc_conn_to_use is None:
        try:
            acc_conn_to_use = get_accounts_connection()
            close_local_acc = True
        except Exception:
            acc_conn_to_use = None

    linked_players = set()
    bronze_ever_reached = False
    if acc_conn_to_use is not None:
        try:
            linked_players = get_approved_linked_players(acc_conn_to_use)
            bronze_ever_reached = has_player_unlocked_achievement(acc_conn_to_use, player_id, "teamplayer:bronze")
        except Exception:
            linked_players = set()

    target_linked_pids = sorted([pid for pid in linked_players if pid != player_id])
    target_count = len(target_linked_pids)
    games_with = {pid: len(partner_games.get(pid, [])) for pid in target_linked_pids}
    min_games = min(games_with.values()) if target_linked_pids else 0

    has_minimum_accounts = target_count >= 15
    if has_minimum_accounts:
        if min_games >= 3:
            tp_tier = "gold"
            next_req = 3
        elif min_games >= 2:
            tp_tier = "silver"
            next_req = 3
        elif min_games >= 1:
            tp_tier = "bronze"
            next_req = 2
        else:
            tp_tier = "neutral"
            next_req = 1
    else:
        tp_tier = "neutral"
        next_req = 1

    if has_minimum_accounts and min_games >= 1:
        if acc_conn_to_use is not None:
            try:
                record_player_unlocked_achievement(acc_conn_to_use, player_id, "teamplayer:bronze")
            except Exception:
                pass
        bronze_ever_reached = True

    if tp_tier in ("bronze", "silver", "gold", "platin"):
        tp_unlocked = True
    elif tp_tier == "neutral":
        tp_unlocked = bronze_ever_reached
    else:
        tp_unlocked = False

    if close_local_acc and acc_conn_to_use is not None:
        try:
            acc_conn_to_use.close()
        except Exception:
            pass

    missing_pids = [pid for pid in target_linked_pids if games_with.get(pid, 0) < next_req]
    missing_names = [players[pid]["aliases"][0] if pid in players else f"Spieler {pid}" for pid in missing_pids]
    played_at_least_1 = sum(1 for pid in target_linked_pids if games_with.get(pid, 0) >= 1)

    if not has_minimum_accounts:
        tp_prog = f"{target_count} / 15 verknüpfte Accounts"
        tp_detail = f"Mit {played_at_least_1} von {target_count} verknüpften Spielern gespielt. Aktivierung ab mindestens 15 Accounts."
    else:
        if tp_tier == "neutral":
            tp_prog = f"{played_at_least_1} / {target_count} verknüpfte Spieler bespielt"
            names_preview = ", ".join(missing_names[:3]) + ("..." if len(missing_names) > 3 else "")
            tp_detail = f"Noch fehlend (min. 1 Spiel): {names_preview}" if missing_names else f"Mit {played_at_least_1} / {target_count} Spielern gespielt."
        else:
            tp_prog = f"Mit allen {target_count} Spielern gespielt (Tier: {tp_tier.capitalize()})"
            if missing_names:
                names_preview = ", ".join(missing_names[:3]) + ("..." if len(missing_names) > 3 else "")
                tp_detail = f"Für nächstes Tier fehlen noch Spiele mit: {names_preview}"
            else:
                tp_detail = f"Mit allen {target_count} verknüpften Spielern mindestens {min_games} Spiele absolviert!"

    return {
        "id": "teamplayer",
        "icon": "🌐",
        "title_key": "achievements.teamplayer_title",
        "tier": tp_tier,
        "unlocked": tp_unlocked,
        "progress_text": tp_prog,
        "description_key": "achievements.teamplayer_desc",
        "detail_text": tp_detail,
        "missing_players": missing_names
    }


def _eval_closed_society(player_id: int, active_matches: list) -> dict:
    lineup_dates = {}
    for m in active_matches:
        roster = frozenset([player_id] + m["own_team_ids"])
        lineup_dates.setdefault(roster, set()).add(m["date"])

    max_roster_dates = max((len(d_set) for d_set in lineup_dates.values()), default=0)
    cs_tiers = [(10, "platin"), (6, "gold"), (4, "silver"), (2, "bronze")]
    cs_unlocked = None
    for target, tier in cs_tiers:
        if max_roster_dates >= target:
            cs_unlocked = tier
            break

    if cs_unlocked:
        return {
            "id": "closed_society",
            "icon": "🥂",
            "title_key": "achievements.closed_society_title",
            "tier": cs_unlocked,
            "unlocked": True,
            "progress_text": f"{max_roster_dates} Spieltage mit exakt gleichem Team",
            "description_key": "achievements.closed_society_desc",
            "detail_text": f"Mit einem identischen Team an {max_roster_dates} verschiedenen Spieltagen angetreten."
        }
    else:
        return {
            "id": "closed_society",
            "icon": "🥂",
            "title_key": "achievements.closed_society_title",
            "tier": "locked",
            "unlocked": False,
            "progress_text": f"{max_roster_dates} / 2 Spieltage mit gleichem Team",
            "description_key": "achievements.closed_society_desc",
            "detail_text": "Spiele mit dem exakt gleichen Team an 2, 4, 6 oder 10 verschiedenen Spieltagen."
        }


def _eval_comeback_king(connection, player_id: int, active_matches: list, user_has_glicko_tier: bool) -> dict:
    p_hist = get_player_rating_history(connection, player_id).get("total", [])
    active_dates_set = set(m["date"] for m in active_matches)
    active_hist = [h for h in p_hist if h.get("date") in active_dates_set]

    windows = [
        (30, "1 Monat", "1 month"),
        (90, "3 Monate", "3 months"),
        (180, "6 Monate", "6 months")
    ]

    points = []
    for h in active_hist:
        try:
            dt = datetime.strptime(h["date"], "%Y-%m-%d")
            points.append((dt, float(h["rating"])))
        except Exception:
            pass

    best_comeback = None
    tier_val = {"gold": 3, "silver": 2, "bronze": 1}

    for days, w_label_de, w_label_en in windows:
        for i in range(len(points)):
            dt_i, r_i = points[i]
            for j in range(i + 1, len(points)):
                dt_j, r_j = points[j]
                if (dt_j - dt_i).days > days:
                    continue
                drop = r_i - r_j
                if drop >= 100.0:
                    for k in range(j + 1, len(points)):
                        dt_k, r_k = points[k]
                        if (dt_k - dt_j).days > days:
                            continue
                        gain = r_k - r_j
                        if gain > drop:
                            tier = "gold" if drop >= 300.0 else ("silver" if drop >= 200.0 else "bronze")
                            event = {
                                "drop": drop,
                                "gain": gain,
                                "window_de": w_label_de,
                                "window_en": w_label_en,
                                "days": days,
                                "tier": tier,
                                "date_low": dt_j.strftime("%Y-%m-%d")
                            }
                            if best_comeback is None or (tier_val[tier], drop) > (tier_val[best_comeback["tier"]], best_comeback["drop"]):
                                best_comeback = event

    if best_comeback is not None:
        drop_val = round(best_comeback["drop"])
        gain_val = round(best_comeback["gain"])
        w_lbl = best_comeback["window_de"]
        return {
            "id": "comeback_king",
            "icon": "🦅",
            "title_key": "achievements.comeback_king_title",
            "tier": best_comeback["tier"],
            "unlocked": True,
            "progress_text": f"-{drop_val} / +{gain_val} Rating ({w_lbl})" if user_has_glicko_tier else f"Comeback ({w_lbl})",
            "description_key": "achievements.comeback_king_desc",
            "detail_text": f"-{drop_val} Rating verloren, danach +{gain_val} Rating zurückgeholt (Zeitraum: {w_lbl})" if user_has_glicko_tier else f"Nach deutlichem Formtief erfolgreich zurückgekämpft (Zeitraum: {w_lbl})"
        }
    else:
        return {
            "id": "comeback_king",
            "icon": "🦅",
            "title_key": "achievements.comeback_king_title",
            "tier": "locked",
            "unlocked": False,
            "progress_text": "Noch kein Comeback",
            "description_key": "achievements.comeback_king_desc",
            "detail_text": "Verliere ≥ 100 Rating in 1, 3 oder 6 Monaten und hole mehr als das im Folgezeitraum zurück."
        }


def get_player_achievements(connection, player_id, user_has_glicko_tier=True, accounts_connection=None, reference_date=None):
    """Compute and return all unlocked and locked achievements for a player."""
    players = get_players(connection)
    if player_id not in players:
        return []

    active_matches, active_global_matches, all_rows = _load_player_matches(connection, player_id)
    total_games = len(active_matches)

    # Group matches by teammate
    partner_games = {}
    for m in active_matches:
        for tm in m["own_team_ids"]:
            partner_games.setdefault(tm, []).append(m)

    achievements = [
        _eval_century_club(total_games),
        _eval_winning_streak(active_matches),
        _eval_iron_man(active_matches, active_global_matches),
        _eval_underdog_hero(active_matches),
        _eval_weisse_wand(active_matches),
    ]

    rank_ach = _eval_highest_rank(connection, player_id, active_matches, user_has_glicko_tier)
    if rank_ach is not None:
        achievements.append(rank_ach)

    achievements.append(_eval_perfect_month(active_matches, active_global_matches, all_rows, reference_date))
    achievements.extend(_eval_cursebreaker(partner_games, players, TIER_ORDER))
    achievements.extend(_eval_buddies(partner_games, players, TIER_ORDER))
    achievements.extend(_eval_golden_duo(partner_games, players, TIER_ORDER))
    achievements.extend(_eval_thick_and_thin(partner_games, players, TIER_ORDER))
    achievements.extend(_eval_underdog_duo(partner_games, players, TIER_ORDER))
    achievements.append(_eval_teamplayer(partner_games, player_id, players, accounts_connection))
    achievements.append(_eval_closed_society(player_id, active_matches))
    achievements.append(_eval_comeback_king(connection, player_id, active_matches, user_has_glicko_tier))

    return achievements


def get_user_unseen_achievements_count(user_id: int, player_id: int, accounts_connection=None, primary_connection=None) -> int:
    """Compute how many unlocked achievements the user has not yet viewed."""
    if not player_id:
        return 0

    close_acc = False
    if accounts_connection is None:
        accounts_connection = get_accounts_connection()
        close_acc = True

    close_prim = False
    if primary_connection is None:
        primary_connection = get_connection()
        close_prim = True

    try:
        seen_keys = get_user_seen_achievements(accounts_connection, user_id)
        achievements = get_player_achievements(
            primary_connection,
            player_id,
            user_has_glicko_tier=True,
            accounts_connection=accounts_connection
        )
        unseen = 0
        for ach in achievements:
            if ach.get("unlocked") and ach.get("tier") != "neutral":
                key = f"{ach['id']}:{ach.get('tier', '')}"
                if key not in seen_keys:
                    unseen += 1
        return unseen
    finally:
        if close_acc:
            accounts_connection.close()
        if close_prim:
            primary_connection.close()
