"""Analysis module for computing player achievements and milestones."""

from datetime import datetime
from scripts.database.db_players import get_players
from scripts.database.db_ratings import get_player_rating_history
from scripts.accounts.database import (
    get_accounts_connection,
    get_approved_linked_players,
    get_user_seen_achievements,
)


def get_player_achievements(connection, player_id, user_has_glicko_tier=True, accounts_connection=None):
    """Compute and return all unlocked and locked achievements for a player."""
    players = get_players(connection)
    if player_id not in players:
        return []

    # Fetch all matches with match_players in chronological order
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

    # Rule: Ignore the first 5 matches of the global match history
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

    active_matches = player_matches
    total_games = len(active_matches)
    achievements = []

    # 1. Century Club (Milestone: 25, 50, 100 Games)
    century_tiers = [(100, "gold"), (50, "silver"), (25, "bronze")]
    unlocked_tier = None
    next_target = 25
    for target, tier in century_tiers:
        if total_games >= target:
            unlocked_tier = tier
            next_target = target
            break

    achievements.append({
        "id": "century_club",
        "icon": "💯",
        "title_key": "achievements.century_title",
        "tier": unlocked_tier if unlocked_tier else "locked",
        "unlocked": unlocked_tier is not None,
        "progress_text": f"{total_games} / {next_target} Spiele" if not unlocked_tier or total_games < 100 else f"{total_games} Spiele absolviert",
        "description_key": "achievements.century_desc",
        "detail_text": f"Aktuell: {total_games} Spiele absolviert"
    })

    # 2. Iron Man (Milestone: consecutive session attendance)
    # Thresholds: Bronze 5, Silber 10, Gold 15, Platin 25
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

    achievements.append({
        "id": "iron_man",
        "icon": "🛡️",
        "title_key": "achievements.iron_man_title",
        "tier": iron_unlocked if iron_unlocked else "locked",
        "unlocked": iron_unlocked is not None,
        "progress_text": f"{max_consecutive_sessions} / {iron_target} Spieltage in Folge",
        "description_key": "achievements.iron_man_desc",
        "detail_text": f"Rekord: {max_consecutive_sessions} aufeinanderfolgende Spieltage"
    })

    # 3. Underdog Hero (Won a match where win expectation was < 32%)
    underdog_wins = [m for m in active_matches if m["is_win"] and m["expected_win_prob"] < 0.32]
    underdog_tier = "gold" if len(underdog_wins) >= 3 else ("silver" if len(underdog_wins) >= 2 else ("bronze" if len(underdog_wins) >= 1 else "locked"))
    achievements.append({
        "id": "underdog_hero",
        "icon": "🦸",
        "title_key": "achievements.underdog_title",
        "tier": underdog_tier,
        "unlocked": len(underdog_wins) > 0,
        "progress_text": f"{len(underdog_wins)} Underdog-Siege (<32% Chance)",
        "description_key": "achievements.underdog_desc",
        "detail_text": f"{len(underdog_wins)}x gegen statistische Quoten (< 32%) gewonnen"
    })

    # 4. Weiße Wand (Zu null gewonnen: goals_against == 0 and is_win)
    clean_sheets = [m for m in active_matches if m["is_win"] and m["goals_against"] == 0]
    cs_tiers = [(5, "gold"), (3, "silver"), (1, "bronze")]
    cs_unlocked = None
    cs_target = 1
    for target, tier in cs_tiers:
        if len(clean_sheets) >= target:
            cs_unlocked = tier
            cs_target = target
            break

    achievements.append({
        "id": "weisse_wand",
        "icon": "🧱",
        "title_key": "achievements.clean_sheet_title",
        "tier": cs_unlocked if cs_unlocked else "locked",
        "unlocked": cs_unlocked is not None,
        "progress_text": f"{len(clean_sheets)} / {cs_target} Zu-Null-Siege",
        "description_key": "achievements.clean_sheet_desc",
        "detail_text": f"{len(clean_sheets)}x ohne Gegentor gewonnen"
    })

    # 5. Highest Rank (Platzierung #1, #2, #3 auf der Rangliste - Tier Gated)
    if user_has_glicko_tier:
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

        achievements.append({
            "id": "highest_rank",
            "icon": "👑",
            "title_key": "achievements.highest_rank_title",
            "tier": rank_tier,
            "unlocked": rank_unlocked,
            "progress_text": f"Beste Platzierung: #{best_rank}" if best_rank <= 50 else "Noch nicht Top 3",
            "description_key": "achievements.highest_rank_desc",
            "detail_text": f"Platz #{best_rank} erreicht ({days_at_rank_1} Spieltage auf Platz 1)" if rank_unlocked else f"Beste Platzierung: #{best_rank}"
        })

    # 6. Makelloser Monat
    # Rule: All matches played in that calendar month must have been attended and won.
    # Tiers per additional perfect month: 1 (bronze), 2 (silver), 3 (gold), 4+ (platin)
    global_months = {}
    for mid, m in active_global_matches.items():
        ym = m["date"][:7]
        global_months.setdefault(ym, set()).add(mid)

    player_month_matches = {}
    for m in active_matches:
        ym = m["date"][:7]
        player_month_matches.setdefault(ym, []).append(m)

    perfect_months = 0
    for ym, g_mids in global_months.items():
        if not g_mids:
            continue
        p_ms = player_month_matches.get(ym, [])
        p_mids = set(m["match_id"] for m in p_ms)
        # Did the player participate in ALL global matches that month, and win every single one?
        if g_mids.issubset(p_mids) and all(m["is_win"] for m in p_ms):
            perfect_months += 1

    pm_tier = "platin" if perfect_months >= 4 else ("gold" if perfect_months >= 3 else ("silver" if perfect_months >= 2 else ("bronze" if perfect_months >= 1 else "locked")))
    pm_target = 4 if perfect_months >= 3 else (3 if perfect_months >= 2 else (2 if perfect_months >= 1 else 1))
    achievements.append({
        "id": "perfect_month",
        "icon": "📅",
        "title_key": "achievements.perfect_month_title",
        "tier": pm_tier,
        "unlocked": perfect_months > 0,
        "progress_text": f"{perfect_months} / {pm_target} Perfekte Monate" if perfect_months < 4 else f"{perfect_months} Perfekte Monate",
        "description_key": "achievements.perfect_month_desc",
        "detail_text": f"{perfect_months}x alle Spiele eines Kalendermonats mitgespielt und gewonnen" if perfect_months > 0 else "Alle Spiele eines Kalendermonats mitspielen und gewinnen"
    })

    # Group matches by teammate
    partner_games = {}
    for m in active_matches:
        for tm in m["own_team_ids"]:
            partner_games.setdefault(tm, []).append(m)

    tier_order = {"platin": 4, "gold": 3, "silver": 2, "bronze": 1}

    # 7. Fluchbrecher (Cursebreaker)
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

    if partner_broken_curses:
        for p_info in partner_broken_curses:
            underdog_note = " (als Underdog)" if p_info["is_underdog"] else ""
            achievements.append({
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
        achievements.append({
            "id": "cursebreaker_placeholder",
            "icon": "⚡",
            "title_key": "achievements.cursebreaker_title",
            "tier": "locked",
            "unlocked": False,
            "progress_text": "Kein gebrochener Fluch",
            "description_key": "achievements.cursebreaker_desc",
            "detail_text": "Mindestens 4 gemeinsame Niederlagen in Folge mit einem Partner, dann gemeinsam gewonnen."
        })

    # 8. Teammate: Buddies (10 / 20 / 35 / 50 gemeinsame Spiele)
    buddies_tiers = [(50, "platin"), (35, "gold"), (20, "silver"), (10, "bronze")]
    buddies_unlocked = []
    for tm_id, g_list in partner_games.items():
        cnt = len(g_list)
        if cnt >= 10:
            tier = "platin" if cnt >= 50 else ("gold" if cnt >= 35 else ("silver" if cnt >= 20 else "bronze"))
            tm_name = players[tm_id]["aliases"][0] if tm_id in players else f"Spieler {tm_id}"
            buddies_unlocked.append((tm_id, tm_name, cnt, tier))

    buddies_unlocked.sort(key=lambda x: (-tier_order[x[3]], -x[2]))
    if buddies_unlocked:
        for tm_id, tm_name, cnt, tier in buddies_unlocked:
            achievements.append({
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
        achievements.append({
            "id": "buddies_placeholder",
            "icon": "🤝",
            "title_key": "achievements.buddies_title",
            "tier": "locked",
            "unlocked": False,
            "progress_text": "Noch keine 10 gemeinsamen Spiele",
            "description_key": "achievements.buddies_desc",
            "detail_text": "Absolviere 10, 20, 35 oder 50 Spiele im selben Team mit einem Mitspieler."
        })

    # 9. Teammate: Goldenes Duo (10 / 20 / 35 / 50 gemeinsame Siege)
    golden_duo_unlocked = []
    for tm_id, g_list in partner_games.items():
        wins_together = len([g for g in g_list if g["is_win"]])
        if wins_together >= 10:
            tier = "platin" if wins_together >= 50 else ("gold" if wins_together >= 35 else ("silver" if wins_together >= 20 else "bronze"))
            tm_name = players[tm_id]["aliases"][0] if tm_id in players else f"Spieler {tm_id}"
            golden_duo_unlocked.append((tm_id, tm_name, wins_together, tier))

    golden_duo_unlocked.sort(key=lambda x: (-tier_order[x[3]], -x[2]))
    if golden_duo_unlocked:
        for tm_id, tm_name, wins_cnt, tier in golden_duo_unlocked:
            achievements.append({
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
        achievements.append({
            "id": "golden_duo_placeholder",
            "icon": "✨",
            "title_key": "achievements.golden_duo_title",
            "tier": "locked",
            "unlocked": False,
            "progress_text": "Noch keine 10 gemeinsamen Siege",
            "description_key": "achievements.golden_duo_desc",
            "detail_text": "Erringe 10, 20, 35 oder 50 Siege im selben Team mit einem Mitspieler."
        })

    # 10. Teammate: Durch Dick und Dünn (10 / 20 / 35 / 50 gemeinsame Niederlagen)
    thick_thin_unlocked = []
    for tm_id, g_list in partner_games.items():
        losses_together = len([g for g in g_list if g["is_loss"]])
        if losses_together >= 10:
            tier = "platin" if losses_together >= 50 else ("gold" if losses_together >= 35 else ("silver" if losses_together >= 20 else "bronze"))
            tm_name = players[tm_id]["aliases"][0] if tm_id in players else f"Spieler {tm_id}"
            thick_thin_unlocked.append((tm_id, tm_name, losses_together, tier))

    thick_thin_unlocked.sort(key=lambda x: (-tier_order[x[3]], -x[2]))
    if thick_thin_unlocked:
        for tm_id, tm_name, losses_cnt, tier in thick_thin_unlocked:
            achievements.append({
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
        achievements.append({
            "id": "thick_and_thin_placeholder",
            "icon": "🌧️",
            "title_key": "achievements.thick_and_thin_title",
            "tier": "locked",
            "unlocked": False,
            "progress_text": "Noch keine 10 gemeinsamen Niederlagen",
            "description_key": "achievements.thick_and_thin_desc",
            "detail_text": "Stehe 10, 20, 35 oder 50 Niederlagen gemeinsam mit einem Mitspieler durch."
        })

    # 11. Teammate: Underdog-Duo (3 / 6 / 9 / 15 Underdog-Siege mit < 32%)
    underdog_duo_unlocked = []
    for tm_id, g_list in partner_games.items():
        ud_wins = len([g for g in g_list if g["is_win"] and g["expected_win_prob"] < 0.32])
        if ud_wins >= 3:
            tier = "platin" if ud_wins >= 15 else ("gold" if ud_wins >= 9 else ("silver" if ud_wins >= 6 else "bronze"))
            tm_name = players[tm_id]["aliases"][0] if tm_id in players else f"Spieler {tm_id}"
            underdog_duo_unlocked.append((tm_id, tm_name, ud_wins, tier))

    underdog_duo_unlocked.sort(key=lambda x: (-tier_order[x[3]], -x[2]))
    if underdog_duo_unlocked:
        for tm_id, tm_name, ud_cnt, tier in underdog_duo_unlocked:
            achievements.append({
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
        achievements.append({
            "id": "underdog_duo_placeholder",
            "icon": "🦊",
            "title_key": "achievements.underdog_duo_title",
            "tier": "locked",
            "unlocked": False,
            "progress_text": "Noch keine 3 Underdog-Siege als Duo",
            "description_key": "achievements.underdog_duo_desc",
            "detail_text": "Erringe 3, 6, 9 oder 15 Underdog-Siege (< 32%) gemeinsam mit einem Mitspieler."
        })

    # 12. Teamplayer
    # Rule: With all players linked to an approved account (minimum 15 accounts): 1 (bronze), 2 (silver), 3 (gold) games.
    # Below bronze: displayed as a neutral badge. If new accounts link, badge is kept, tier adjusts, missing players listed.
    linked_players = set()
    try:
        if accounts_connection is not None:
            linked_players = get_approved_linked_players(accounts_connection)
        else:
            acc_conn = get_accounts_connection()
            try:
                linked_players = get_approved_linked_players(acc_conn)
            finally:
                acc_conn.close()
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

    achievements.append({
        "id": "teamplayer",
        "icon": "🌐",
        "title_key": "achievements.teamplayer_title",
        "tier": tp_tier,
        "unlocked": True,  # Neutral badge or bronze+ is always unlocked/displayed
        "progress_text": tp_prog,
        "description_key": "achievements.teamplayer_desc",
        "detail_text": tp_detail,
        "missing_players": missing_names
    })

    # 13. Geschlossene Gesellschaft (Spiele mit dem exakt gleichen Team an 2, 4, 6, 10 verschiedenen Spieltagen)
    lineup_dates = {}
    for m in active_matches:
        roster = frozenset([player_id] + m["own_team_ids"])
        lineup_dates.setdefault(roster, set()).add(m["date"])

    max_roster_dates = max((len(d_set) for d_set in lineup_dates.values()), default=0)
    cs_tiers = [(10, "platin"), (6, "gold"), (4, "silver"), (2, "bronze")]
    cs_unlocked = None
    cs_target = 2
    for target, tier in cs_tiers:
        if max_roster_dates >= target:
            cs_unlocked = tier
            cs_target = target
            break

    if cs_unlocked:
        achievements.append({
            "id": "closed_society",
            "icon": "🥂",
            "title_key": "achievements.closed_society_title",
            "tier": cs_unlocked,
            "unlocked": True,
            "progress_text": f"{max_roster_dates} Spieltage mit exakt gleichem Team",
            "description_key": "achievements.closed_society_desc",
            "detail_text": f"Mit einem identischen Team an {max_roster_dates} verschiedenen Spieltagen angetreten."
        })
    else:
        achievements.append({
            "id": "closed_society",
            "icon": "🥂",
            "title_key": "achievements.closed_society_title",
            "tier": "locked",
            "unlocked": False,
            "progress_text": f"{max_roster_dates} / 2 Spieltage mit gleichem Team",
            "description_key": "achievements.closed_society_desc",
            "detail_text": "Spiele mit dem exakt gleichen Team an 2, 4, 6 oder 10 verschiedenen Spieltagen."
        })

    # 14. Comeback King (Interval-based rating drop and recovery)
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
        achievements.append({
            "id": "comeback_king",
            "icon": "🦅",
            "title_key": "achievements.comeback_king_title",
            "tier": best_comeback["tier"],
            "unlocked": True,
            "progress_text": f"-{drop_val} / +{gain_val} Rating ({w_lbl})" if user_has_glicko_tier else f"Comeback ({w_lbl})",
            "description_key": "achievements.comeback_king_desc",
            "detail_text": f"-{drop_val} Rating verloren, danach +{gain_val} Rating zurückgeholt (Zeitraum: {w_lbl})" if user_has_glicko_tier else f"Nach deutlichem Formtief erfolgreich zurückgekämpft (Zeitraum: {w_lbl})"
        })
    else:
        achievements.append({
            "id": "comeback_king",
            "icon": "🦅",
            "title_key": "achievements.comeback_king_title",
            "tier": "locked",
            "unlocked": False,
            "progress_text": "Noch kein Comeback",
            "description_key": "achievements.comeback_king_desc",
            "detail_text": "Verliere ≥ 100 Rating in 1, 3 oder 6 Monaten und hole mehr als das im Folgezeitraum zurück."
        })

    return achievements


def get_user_unseen_achievements_count(user_id: int, player_id: int, accounts_connection=None, primary_connection=None) -> int:
    """Compute how many unlocked achievements the user has not yet viewed."""
    if not player_id:
        return 0
    from scripts.database.database import get_connection

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
