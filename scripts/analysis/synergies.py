"""Analysis module for community synergies, duos, and rivalries."""

from scripts.database.db_players import get_players


def get_community_synergies(connection, min_games=5):
    """Calculate community-wide duo chemistry, kryptonite rivalries, and balanced matchups."""
    players = get_players(connection)
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

    duo_stats = {}      # (p1, p2) -> {games, wins, draws, losses, goals_for, goals_against}
    rival_stats = {}    # (p1, p2) -> {games, p1_wins, draws, p2_wins, p1_goals, p2_goals}

    for m in matches.values():
        ga, gb = m["goals_a"], m["goals_b"]
        a_win = ga > gb
        b_win = gb > ga
        draw = ga == gb

        # Teammate duos (Team A)
        team_a = sorted(m["team_a"])
        for i in range(len(team_a)):
            for j in range(i + 1, len(team_a)):
                pair = (team_a[i], team_a[j])
                if pair not in duo_stats:
                    duo_stats[pair] = {"games": 0, "wins": 0, "draws": 0, "losses": 0, "goals_for": 0, "goals_against": 0}
                duo_stats[pair]["games"] += 1
                if a_win:
                    duo_stats[pair]["wins"] += 1
                elif draw:
                    duo_stats[pair]["draws"] += 1
                else:
                    duo_stats[pair]["losses"] += 1
                duo_stats[pair]["goals_for"] += ga
                duo_stats[pair]["goals_against"] += gb

        # Teammate duos (Team B)
        team_b = sorted(m["team_b"])
        for i in range(len(team_b)):
            for j in range(i + 1, len(team_b)):
                pair = (team_b[i], team_b[j])
                if pair not in duo_stats:
                    duo_stats[pair] = {"games": 0, "wins": 0, "draws": 0, "losses": 0, "goals_for": 0, "goals_against": 0}
                duo_stats[pair]["games"] += 1
                if b_win:
                    duo_stats[pair]["wins"] += 1
                elif draw:
                    duo_stats[pair]["draws"] += 1
                else:
                    duo_stats[pair]["losses"] += 1
                duo_stats[pair]["goals_for"] += gb
                duo_stats[pair]["goals_against"] += ga

        # Opponent rivalries (Team A vs Team B)
        for pa in team_a:
            for pb in team_b:
                p1, p2 = min(pa, pb), max(pa, pb)
                if (p1, p2) not in rival_stats:
                    rival_stats[(p1, p2)] = {"games": 0, "p1_wins": 0, "draws": 0, "p2_wins": 0, "p1_goals": 0, "p2_goals": 0}
                st = rival_stats[(p1, p2)]
                st["games"] += 1
                if draw:
                    st["draws"] += 1
                elif (pa == p1 and a_win) or (pb == p1 and b_win):
                    st["p1_wins"] += 1
                else:
                    st["p2_wins"] += 1

                if pa == p1:
                    st["p1_goals"] += ga
                    st["p2_goals"] += gb
                else:
                    st["p1_goals"] += gb
                    st["p2_goals"] += ga

    # Format best and worst duos
    formatted_duos = []
    for (p1, p2), st in duo_stats.items():
        if st["games"] < min_games:
            continue
        alias1 = players[p1]["aliases"][0] if p1 in players else f"Player #{p1}"
        alias2 = players[p2]["aliases"][0] if p2 in players else f"Player #{p2}"
        win_rate = (st["wins"] / st["games"]) * 100
        goal_diff = st["goals_for"] - st["goals_against"]
        formatted_duos.append({
            "player1_id": p1,
            "player1_name": alias1,
            "player2_id": p2,
            "player2_name": alias2,
            "games": st["games"],
            "wins": st["wins"],
            "draws": st["draws"],
            "losses": st["losses"],
            "win_rate": round(win_rate, 1),
            "goal_diff": goal_diff
        })

    # Best duos: sorted by win_rate desc, then games desc
    best_duos = sorted(formatted_duos, key=lambda d: (-d["win_rate"], -d["games"]))[:10]

    # Worst duos (Lowest chemistry): sorted by win_rate asc, then games desc
    worst_duos = sorted(formatted_duos, key=lambda d: (d["win_rate"], -d["games"]))[:10]

    # Kryptonite rivals (Lopsided opponent records)
    kryptonite_rivals = []
    balanced_matchups = []
    for (p1, p2), st in rival_stats.items():
        if st["games"] < min_games:
            continue
        alias1 = players[p1]["aliases"][0] if p1 in players else f"Player #{p1}"
        alias2 = players[p2]["aliases"][0] if p2 in players else f"Player #{p2}"
        p1_rate = (st["p1_wins"] / st["games"]) * 100
        p2_rate = (st["p2_wins"] / st["games"]) * 100

        if abs(p1_rate - p2_rate) >= 40:
            dominant_id, dominant_name, dominant_wins = (p1, alias1, st["p1_wins"]) if p1_rate > p2_rate else (p2, alias2, st["p2_wins"])
            victim_id, victim_name, victim_wins = (p2, alias2, st["p2_wins"]) if p1_rate > p2_rate else (p1, alias1, st["p1_wins"])
            kryptonite_rivals.append({
                "dominant_id": dominant_id,
                "dominant_player": dominant_name,
                "victim_id": victim_id,
                "victim_player": victim_name,
                "games": st["games"],
                "dominant_wins": dominant_wins,
                "victim_wins": victim_wins,
                "draws": st["draws"],
                "dominance_rate": round(max(p1_rate, p2_rate), 1)
            })
        elif abs(st["p1_wins"] - st["p2_wins"]) <= 1:
            balanced_matchups.append({
                "player1_id": p1,
                "player1_name": alias1,
                "player2_id": p2,
                "player2_name": alias2,
                "games": st["games"],
                "p1_wins": st["p1_wins"],
                "p2_wins": st["p2_wins"],
                "draws": st["draws"]
            })

    kryptonite_rivals.sort(key=lambda r: (-r["dominance_rate"], -r["games"]))
    balanced_matchups.sort(key=lambda b: -b["games"])

    return {
        "best_duos": best_duos,
        "worst_duos": worst_duos,
        "kryptonite_rivals": kryptonite_rivals[:10],
        "balanced_matchups": balanced_matchups[:10]
    }
