"""Analysis module for computing player achievements and milestones."""

import math
from scripts.database.db_players import get_players
from scripts.database.db_ratings import get_player_rating_history


def get_player_achievements(connection, player_id, user_has_glicko_tier=True):
    """Compute and return all unlocked and locked achievements for a player."""
    players = get_players(connection)
    if player_id not in players:
        return []

    player_name = players[player_id]["aliases"][0]

    # Fetch all matches with match_players
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
    for m in matches.values():
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
            
            avg_a = sum(team_a_r) / len(team_a_r) if team_a_r else 1500
            avg_b = sum(team_b_r) / len(team_b_r) if team_b_r else 1500
            
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

    total_games = len(player_matches)
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
        "detail_text": f"Aktuell: {total_games} Spiele"
    })

    # 2. Iron Man (Milestone: consecutive session attendance)
    distinct_dates = sorted(list(set(m["date"] for m in matches.values())))
    player_dates = set(m["date"] for m in player_matches)
    
    max_consecutive_sessions = 0
    curr_streak = 0
    for d in distinct_dates:
        if d in player_dates:
            curr_streak += 1
            if curr_streak > max_consecutive_sessions:
                max_consecutive_sessions = curr_streak
        else:
            curr_streak = 0

    iron_tiers = [(10, "gold"), (5, "silver"), (3, "bronze")]
    iron_unlocked = None
    iron_target = 3
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

    # 3. Underdog Hero (Won a match where win expectation was <= 40%)
    underdog_wins = [m for m in player_matches if m["is_win"] and m["expected_win_prob"] <= 0.40]
    achievements.append({
        "id": "underdog_hero",
        "icon": "🦸",
        "title_key": "achievements.underdog_title",
        "tier": "gold" if len(underdog_wins) >= 3 else ("bronze" if len(underdog_wins) >= 1 else "locked"),
        "unlocked": len(underdog_wins) > 0,
        "progress_text": f"{len(underdog_wins)} Underdog-Siege (≤40% Chance)",
        "description_key": "achievements.underdog_desc",
        "detail_text": f"{len(underdog_wins)}x gegen statistische Quoten gewonnen"
    })

    # 4. Weiße Wand (Zu null gewonnen: goals_against == 0 and is_win)
    clean_sheets = [m for m in player_matches if m["is_win"] and m["goals_against"] == 0]
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
        all_hist = connection.execute("""
            SELECT mr.player_id, mr.rating, m.date
            FROM match_ratings mr
            JOIN matches m ON m.match_id = mr.match_id
            WHERE mr.rating_type = 'total'
            ORDER BY m.date ASC
        """).fetchall()

        date_groups = {}
        for r in all_hist:
            date_groups.setdefault(r["date"], []).append((r["player_id"], r["rating"]))

        best_rank = 999
        days_at_rank_1 = 0
        for d, p_list in date_groups.items():
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

    # 6. Breaking Destiny (Ended a losing curse or beat kryptonite rival)
    destiny_broken_count = 0
    partner_losses = {}
    for m in player_matches:
        if m["is_win"]:
            for tm in m["own_team_ids"]:
                if partner_losses.get(tm, 0) >= 3:
                    destiny_broken_count += 1
                    partner_losses[tm] = 0
            for opp in m["opp_team_ids"]:
                if partner_losses.get(f"opp_{opp}", 0) >= 3:
                    destiny_broken_count += 1
                    partner_losses[f"opp_{opp}"] = 0
        elif m["is_loss"]:
            for tm in m["own_team_ids"]:
                partner_losses[tm] = partner_losses.get(tm, 0) + 1
            for opp in m["opp_team_ids"]:
                partner_losses[f"opp_{opp}"] = partner_losses.get(f"opp_{opp}", 0) + 1

    achievements.append({
        "id": "breaking_destiny",
        "icon": "⚡",
        "title_key": "achievements.breaking_destiny_title",
        "tier": "gold" if destiny_broken_count >= 2 else ("bronze" if destiny_broken_count >= 1 else "locked"),
        "unlocked": destiny_broken_count > 0,
        "progress_text": f"{destiny_broken_count}x Fluch gebrochen",
        "description_key": "achievements.breaking_destiny_desc",
        "detail_text": f"{destiny_broken_count}x nach Serie von Niederlagen triumphiert"
    })

    # 7. Comeback King (Biggest rating rebound after a dip)
    p_hist = get_player_rating_history(connection, player_id).get("total", [])
    rh_p = [h["rating"] for h in p_hist]
    has_comeback = False
    max_recovery = 0
    if len(rh_p) >= 3:
        min_so_far = rh_p[0]
        for r in rh_p:
            if r < min_so_far:
                min_so_far = r
            recovery = r - min_so_far
            if recovery > max_recovery:
                max_recovery = recovery
        has_comeback = max_recovery >= 30

    achievements.append({
        "id": "comeback_king",
        "icon": "🦅",
        "title_key": "achievements.comeback_king_title",
        "tier": "gold" if max_recovery >= 60 else ("silver" if max_recovery >= 30 else "locked"),
        "unlocked": has_comeback,
        "progress_text": f"+{round(max_recovery)} Rating-Rebound" if max_recovery > 0 else "0 Rebound",
        "description_key": "achievements.comeback_king_desc",
        "detail_text": f"Größte Erholung nach Formtief: +{round(max_recovery)} Rating-Punkte"
    })

    # 8. Perfect Session (Won all matches on a matchday with >= 2 matches)
    date_matches = {}
    for m in player_matches:
        date_matches.setdefault(m["date"], []).append(m)

    perfect_sessions = 0
    for d, ms in date_matches.items():
        if len(ms) >= 2 and all(m["is_win"] for m in ms):
            perfect_sessions += 1

    achievements.append({
        "id": "perfect_session",
        "icon": "✨",
        "title_key": "achievements.perfect_session_title",
        "tier": "gold" if perfect_sessions >= 3 else ("silver" if perfect_sessions >= 1 else "locked"),
        "unlocked": perfect_sessions > 0,
        "progress_text": f"{perfect_sessions} Perfekte Spieltage",
        "description_key": "achievements.perfect_session_desc",
        "detail_text": f"{perfect_sessions}x alle Spiele an einem Spieltag gewonnen (min. 2 Spiele)"
    })

    return achievements
