import json
from datetime import date
from flask import Blueprint, render_template, request, jsonify

from scripts.accounts.database import get_accounts_connection
from scripts.database.database import get_connection
from scripts.database.db_ratings import get_ratings
from scripts.database.db_players import get_players, get_alias_lookup, add_alias, get_ignored_aliases, add_ignored_alias
from scripts.matches.match_entry import (
    add_match,
    next_match_id,
    create_new_player,
    CALIBRATION_LEVELS,
    CERTAINTY_LEVELS,
    process_new_matches,
)
from scripts.matchmaking.matchmaker import generate_match
from scripts.matchmaking.match_parser import (
    parse_match_image,
    parse_match_text,
    resolve_player_names,
    normalize_player_name,
    MatchParserError,
)
from scripts.planner.database import (
    get_event_attendees,
    get_event_by_id,
    get_planner_connection,
    get_planner_events_for_import,
)
from web.routes.planner import resolve_active_roster_player_ids
from web.services.cache import invalidate_stats_cache
from web.services.security import require_admin

match_center_bp = Blueprint("match_center", __name__)


class _EmptyParseResult(dict):
    def __bool__(self):
        return False


def _alias_candidates(players):
    lookup = {}
    for player_id, player in players.items():
        for alias in player.get("aliases", []):
            lookup.setdefault(normalize_player_name(alias).casefold(), []).append(player_id)
    return lookup


def _build_parse_result(parsed, players, ignored_aliases=None):
    ignored_set = {normalize_player_name(a).casefold() for a in (ignored_aliases or set())}
    parsed_names = parsed.get("players", [])
    verified_ids, conflicts, unmatched = resolve_player_names(parsed_names, players, ignored_aliases=ignored_aliases)
    lookup = _alias_candidates(players)

    team_a_ids = []
    external_a = 0
    for raw in parsed.get("team_a", []):
        norm = normalize_player_name(raw).casefold()
        if len(ids := lookup.get(norm, [])) == 1:
            team_a_ids.append(ids[0])
        elif norm in ignored_set:
            external_a += 1

    team_b_ids = []
    external_b = 0
    for raw in parsed.get("team_b", []):
        norm = normalize_player_name(raw).casefold()
        if len(ids := lookup.get(norm, [])) == 1:
            team_b_ids.append(ids[0])
        elif norm in ignored_set:
            external_b += 1

    return {
        "kind": parsed.get("kind", "unknown"),
        "match_date": parsed.get("match_date"),
        "players": parsed_names,
        "team_a": parsed.get("team_a", []),
        "team_b": parsed.get("team_b", []),
        "team_a_ids": team_a_ids,
        "team_b_ids": team_b_ids,
        "external_a": external_a,
        "external_b": external_b,
        "goals_a": parsed.get("goals_a"),
        "goals_b": parsed.get("goals_b"),
        "verified_ids": verified_ids,
        "conflicts": conflicts,
        "unmatched": unmatched,
    }


def _rebuild_parser_result(form, players, files=None, ignored_aliases=None):
    def integer_or_none(value):
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    action = form.get("action")
    if action in ("parse_source", "parse_image"):
        if action == "parse_source" and form.get("match_text", "").strip():
            parsed = parse_match_text(form["match_text"])
        else:
            upload = (files or request.files).get("match_image")
            if not upload or not upload.filename:
                raise MatchParserError("Please paste a WhatsApp message or choose/paste an image first.")
            parsed = parse_match_image(upload.read(), upload.mimetype)
        return _build_parse_result(parsed, players, ignored_aliases=ignored_aliases)

    return _build_parse_result({
        "kind": form.get("parsed_kind", "unknown"),
        "match_date": form.get("parsed_match_date") or None,
        "players": form.getlist("parsed_player"),
        "team_a": [x for x in form.get("parsed_team_a", "").split("||") if x],
        "team_b": [x for x in form.get("parsed_team_b", "").split("||") if x],
        "goals_a": integer_or_none(form.get("parsed_goals_a")),
        "goals_b": integer_or_none(form.get("parsed_goals_b")),
    }, players, ignored_aliases=ignored_aliases)


def _remove_resolved_name(parse_result, name):
    key = normalize_player_name(name).casefold()
    parse_result["conflicts"] = [c for c in parse_result["conflicts"] if c.get("name", "").casefold() != key]
    parse_result["unmatched"] = [u for u in parse_result["unmatched"] if u.get("name", "").casefold() != key]


def _get_prefilled_team_ids(form, team_name, players):
    values = form.getlist(team_name)
    if len(values) == 1 and "," in values[0]:
        values = values[0].split(",")
    return [int(pid) for pid in values if pid.isdigit() and int(pid) in players]


# -----------------------------------------------------------------------------
# Modular Action Handlers for match_center
# -----------------------------------------------------------------------------

def _handle_parse_action(form, files, players, connection):
    """Handle match message or match sheet image parsing via Gemini."""
    try:
        action = form.get("action")
        if action == "parse_source" and form.get("match_text", "").strip():
            parsed = parse_match_text(form["match_text"])
        else:
            upload = files.get("match_image")
            if not upload or not upload.filename:
                raise MatchParserError("Please paste a WhatsApp message or choose/paste an image first.")
            parsed = parse_match_image(upload.read(), upload.mimetype)
        ignored_aliases = get_ignored_aliases(connection)
        parse_result = _build_parse_result(parsed, players, ignored_aliases=ignored_aliases)
        selected_ids = parse_result["verified_ids"]
        parser_success = "This looks like an already played match. Review the imported facts, or check the same players for fairer possible teams." if parse_result["kind"] == "match" else None
        return parse_result, selected_ids, parser_success, None
    except MatchParserError as exc:
        empty_res = _EmptyParseResult(kind="", match_date=None, players=[], team_a=[], team_b=[], team_a_ids=[], team_b_ids=[], external_a=0, external_b=0, goals_a=None, goals_b=None, verified_ids=[], conflicts=[], unmatched=[])
        return empty_res, [], None, str(exc)


def _handle_resolve_conflicts(form, players, connection):
    ignored_aliases = get_ignored_aliases(connection)
    parse_result = _rebuild_parser_result(form, players, ignored_aliases=ignored_aliases)
    selected_ids = list(parse_result["verified_ids"])
    lookup = _alias_candidates(players)
    remaining = []
    for index, conflict in enumerate(parse_result["conflicts"]):
        detail = normalize_player_name(form.get(f"conflict_detail_{index}", ""))
        candidates = lookup.get((detail or conflict["name"]).casefold(), [])
        if len(candidates) == 1:
            selected_ids.append(candidates[0])
        elif len(candidates) > 1:
            remaining.append({"name": conflict["name"], "candidate_ids": candidates, "detail": detail})
        else:
            parse_result["unmatched"].append({"name": detail or conflict["name"], "verified": False})
    parse_result["conflicts"] = remaining
    selected_ids = list(dict.fromkeys(selected_ids))
    parser_success = "Name conflicts resolved. The confirmed identities are now selected." if not remaining else None
    return parse_result, selected_ids, parser_success


def _handle_add_parser_alias(form, connection, players, selected_ids):
    ignored_aliases = get_ignored_aliases(connection)
    parse_result = _rebuild_parser_result(form, players, ignored_aliases=ignored_aliases)
    alias = normalize_player_name(form.get("new_alias", ""))
    try:
        player_id = int(form.get("target_player_id", ""))
        lookup = get_alias_lookup(connection)
        if player_id not in players:
            raise ValueError("Selected player does not exist.")
        if not alias:
            raise ValueError("Alias cannot be empty.")
        if alias.casefold() in {a.casefold() for a in lookup}:
            raise ValueError(f"The alias '{alias}' already exists.")
        add_alias(connection, alias, player_id)
        connection.commit()
        invalidate_stats_cache()
        players = get_players(connection)
        selected_ids = list(dict.fromkeys(selected_ids + [player_id]))
        ignored_aliases = get_ignored_aliases(connection)
        parse_result = _rebuild_parser_result(form, players, ignored_aliases=ignored_aliases)
        _remove_resolved_name(parse_result, alias)
        return players, selected_ids, parse_result, f"Added '{alias}' as an alias and selected the player.", None
    except (ValueError, TypeError) as exc:
        return players, selected_ids, parse_result, None, str(exc)


def _handle_create_parser_player(form, connection, players, selected_ids):
    alias = normalize_player_name(form.get("new_alias", ""))
    positions = form.getlist("new_positions")
    calibration = form.get("calibration", "average")
    certainty = form.get("certainty", "uncertain")
    main_position = form.get("main_position") or form.get("new_main_position")
    try:
        created_id, _ = create_new_player(
            connection,
            alias,
            positions,
            calibration,
            main_position=main_position,
            certainty_level=certainty,
        )
        invalidate_stats_cache()
        players = get_players(connection)
        selected_ids = list(dict.fromkeys(selected_ids + [created_id]))
        ignored_aliases = get_ignored_aliases(connection)
        parse_result = _rebuild_parser_result(form, players, ignored_aliases=ignored_aliases)
        _remove_resolved_name(parse_result, alias)
        return players, selected_ids, parse_result, f"Created {alias} and selected them.", None
    except ValueError as exc:
        ignored_aliases = get_ignored_aliases(connection)
        parse_result = _rebuild_parser_result(form, players, ignored_aliases=ignored_aliases)
        return players, selected_ids, parse_result, None, str(exc)


def _handle_ignore_parser_player(form, connection, players, selected_ids):
    alias = normalize_player_name(form.get("target_alias") or form.get("new_alias") or "")
    try:
        if not alias:
            raise ValueError("Alias cannot be empty.")
        add_ignored_alias(connection, alias)
        connection.commit()
        ignored_aliases = get_ignored_aliases(connection)
        parse_result = _rebuild_parser_result(form, players, ignored_aliases=ignored_aliases)
        _remove_resolved_name(parse_result, alias)
        return players, selected_ids, parse_result, f"Ignored '{alias}'. This tag will count as an external guest player in matches.", None
    except ValueError as exc:
        ignored_aliases = get_ignored_aliases(connection)
        parse_result = _rebuild_parser_result(form, players, ignored_aliases=ignored_aliases)
        return players, selected_ids, parse_result, None, str(exc)


def _handle_import_planner(form, connection, selected_ids):
    planner_event_id = form.get("planner_event_id", type=int)
    if not planner_event_id:
        return selected_ids, None, None, None

    p_conn = get_planner_connection()
    a_conn = get_accounts_connection()
    try:
        ev_row = get_event_by_id(p_conn, planner_event_id)
        if not ev_row:
            return selected_ids, None, None, None
        ev = dict(ev_row)
        attendees = [dict(a) for a in get_event_attendees(p_conn, planner_event_id)]
        alias_lookup = get_alias_lookup(connection)
        active_roster = [a for a in attendees if a.get("status") == "attending"][:ev.get("max_players", 12)]
        imported_ids = resolve_active_roster_player_ids(active_roster, alias_lookup, a_conn)
        new_selected = list(dict.fromkeys(selected_ids + imported_ids))
        imported_date = ev["event_date"].split("T")[0].split(" ")[0] if ev.get("event_date") else None
        imported_pitch = ev.get("pitch", "").lower() if ev.get("pitch") else None
        title = ev.get("title") or "Spieltag"
        msg = f"Kader erfolgreich importiert ({len(imported_ids)} Spieler aus Event '{title}')."
        return new_selected, imported_date, imported_pitch, msg
    finally:
        p_conn.close()
        a_conn.close()


def _handle_create_player(form, is_xhr, connection, players, selected_ids):
    try:
        alias = normalize_player_name(form.get("new_alias", ""))
        positions = form.getlist("new_positions")
        calibration = form.get("calibration", "average")
        certainty = form.get("certainty", "uncertain")
        main_position = form.get("main_position") or form.get("new_main_position")
        target_team = form.get("target_team", "a")
        created_id, values = create_new_player(
            connection,
            alias,
            positions,
            calibration,
            main_position=main_position,
            certainty_level=certainty,
        )
        invalidate_stats_cache()
        selected_ids.append(created_id)
        success = f"Created {alias.strip()} and added them to the match."
        cal_msg = f"Calibration rating: {values['rating']:.1f} (RD {values['rd']:.1f})."
        players = get_players(connection)
        selected_ids = list(dict.fromkeys(selected_ids))
        if is_xhr:
            return players, selected_ids, success, None, cal_msg, jsonify({
                "success": True,
                "player_id": created_id,
                "alias": alias,
                "rating": values["rating"],
                "rd": values["rd"],
                "target_team": target_team,
                "main_position": main_position,
                "message": success,
            })
        return players, selected_ids, success, None, cal_msg, None
    except ValueError as exc:
        err = str(exc)
        if is_xhr:
            return players, selected_ids, None, err, None, (jsonify({"success": False, "error": err}), 400)
        return players, selected_ids, None, err, None, None


def _handle_save_match(data, is_xhr, connection, players):
    try:
        matches_list = None
        if hasattr(data, "get"):
            matches_json = data.get("matches_json")
            if matches_json:
                matches_list = json.loads(matches_json)
            elif data.get("matches"):
                matches_list = data.get("matches")

        if not matches_list:
            matches_list = [{
                "date": data.get("date", date.today().isoformat()),
                "pitch": data.get("pitch", "box"),
                "team_a": _get_prefilled_team_ids(data, "team_a", players) if hasattr(data, "getlist") else [int(p) for p in data.get("team_a", []) if str(p).isdigit() and int(p) in players],
                "team_b": _get_prefilled_team_ids(data, "team_b", players) if hasattr(data, "getlist") else [int(p) for p in data.get("team_b", []) if str(p).isdigit() and int(p) in players],
                "external_a": int(data.get("external_a", "0") or 0),
                "external_b": int(data.get("external_b", "0") or 0),
                "goals_a": int(data.get("goals_a", "0") or 0),
                "goals_b": int(data.get("goals_b", "0") or 0),
            }]

        parsed_matches = []
        for idx, m in enumerate(matches_list, start=1):
            m_date = m.get("date") or (data.get("date") if hasattr(data, "get") else None) or date.today().isoformat()
            m_pitch = m.get("pitch") or (data.get("pitch") if hasattr(data, "get") else None) or "box"
            if m_pitch not in ("box", "hf"):
                raise ValueError(f"Spiel {idx}: Ungültiges Platzformat '{m_pitch}'.")
            date.fromisoformat(m_date)

            raw_team_a = m.get("team_a", [])
            raw_team_b = m.get("team_b", [])
            if isinstance(raw_team_a, str):
                raw_team_a = [p.strip() for p in raw_team_a.split(",") if p.strip()]
            if isinstance(raw_team_b, str):
                raw_team_b = [p.strip() for p in raw_team_b.split(",") if p.strip()]

            m_team_a = [int(p) for p in raw_team_a if str(p).isdigit() and int(p) in players]
            m_team_b = [int(p) for p in raw_team_b if str(p).isdigit() and int(p) in players]
            m_ext_a = int(m.get("external_a", 0) or 0)
            m_ext_b = int(m.get("external_b", 0) or 0)

            if m_ext_a < 0 or m_ext_b < 0:
                raise ValueError(f"Spiel {idx}: Externe Spieleranzahl darf nicht negativ sein.")
            if (not m_team_a and m_ext_a == 0) or (not m_team_b and m_ext_b == 0):
                raise ValueError(f"Spiel {idx}: Beide Teams benötigen mindestens einen Spieler.")
            if len(m_team_a) != len(set(m_team_a)) or len(m_team_b) != len(set(m_team_b)):
                raise ValueError(f"Spiel {idx}: Ein Spieler darf nicht mehrfach im selben Team vorkommen.")
            if set(m_team_a) & set(m_team_b):
                raise ValueError(f"Spiel {idx}: Ein Spieler darf nicht in beiden Teams gleichzeitig spielen.")

            goals_a_int = int(m.get("goals_a", 0))
            goals_b_int = int(m.get("goals_b", 0))
            if goals_a_int < 0 or goals_b_int < 0:
                raise ValueError(f"Spiel {idx}: Tore dürfen nicht negativ sein.")

            parsed_matches.append({
                "date": m_date,
                "pitch": m_pitch,
                "team_a": m_team_a,
                "team_b": m_team_b,
                "external_a": m_ext_a,
                "external_b": m_ext_b,
                "goals_a": goals_a_int,
                "goals_b": goals_b_int,
            })

        created_match_ids = []
        for m in parsed_matches:
            match_id = add_match(
                connection,
                m["date"],
                m["pitch"],
                m["team_a"],
                m["team_b"],
                m["goals_a"],
                m["goals_b"],
                len(m["team_a"]) + m["external_a"],
                len(m["team_b"]) + m["external_b"],
            )
            created_match_ids.append(match_id)

        processed = process_new_matches(connection)
        invalidate_stats_cache()

        if len(created_match_ids) == 1:
            success = f"Saved: {created_match_ids[0]} and Glicko ratings updated ({processed} match calculated)."
        else:
            success = f"Saved: {len(created_match_ids)} matches ({', '.join(created_match_ids)}) and Glicko ratings updated for this evening."

        if is_xhr:
            next_id = next_match_id(connection, parsed_matches[-1]["date"])
            return success, None, jsonify({
                "success": True,
                "match_id": created_match_ids[0],
                "match_ids": created_match_ids,
                "message": success,
                "next_match_id": next_id,
            })
        return success, None, None
    except (ValueError, RuntimeError) as exc:
        err = str(exc)
        if is_xhr:
            return None, err, (jsonify({"success": False, "error": err}), 400)
        return None, err, None


# -----------------------------------------------------------------------------
# Main Route Controller
# -----------------------------------------------------------------------------

@match_center_bp.route("/match-center", methods=["GET", "POST"])
@require_admin
def match_center():
    connection = get_connection()
    try:
        players = get_players(connection)
        ratings = get_ratings(connection)

        mode = request.form.get("mode", request.args.get("mode", "total"))
        mode = mode if mode in ("total", "pitch") else "total"
        pitch = request.form.get("pitch", request.args.get("pitch", "box"))
        pitch = pitch if pitch in ("box", "hf") else "box"
        rating_type = "total" if mode == "total" else pitch

        raw_players = request.form.getlist("players") or request.args.getlist("players")
        if len(raw_players) == 1 and "," in raw_players[0]:
            raw_players = [p.strip() for p in raw_players[0].split(",") if p.strip()]
        selected_ids = [int(pid) for pid in raw_players if str(pid).strip().isdigit() and int(pid) in players]

        result = None
        seed = None
        parse_result = _EmptyParseResult(kind="", match_date=None, players=[], team_a=[], team_b=[], team_a_ids=[], team_b_ids=[], external_a=0, external_b=0, goals_a=None, goals_b=None, verified_ids=[], conflicts=[], unmatched=[])
        parse_error = None
        parser_success = None
        success = None
        error = None
        calibration_message = None
        req_data = (request.get_json(silent=True) or {}) if request.is_json else request.form
        action = req_data.get("action") if request.method == "POST" else None
        imported_planner_date = None
        is_xhr = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json

        if request.method == "POST":
            if action in ("parse_image", "parse_source"):
                parse_result, selected_ids, parser_success, parse_error = _handle_parse_action(request.form, request.files, players, connection)

            elif action == "resolve_conflicts":
                parse_result, selected_ids, parser_success = _handle_resolve_conflicts(request.form, players, connection)

            elif action == "add_parser_alias":
                players, selected_ids, parse_result, parser_success, parse_error = _handle_add_parser_alias(request.form, connection, players, selected_ids)

            elif action == "create_parser_player":
                players, selected_ids, parse_result, parser_success, parse_error = _handle_create_parser_player(request.form, connection, players, selected_ids)

            elif action == "ignore_parser_player":
                players, selected_ids, parse_result, parser_success, parse_error = _handle_ignore_parser_player(request.form, connection, players, selected_ids)

            elif action == "import_planner":
                selected_ids, imported_planner_date, imported_planner_pitch, parser_success = _handle_import_planner(request.form, connection, selected_ids)
                if imported_planner_pitch and imported_planner_pitch in ("box", "hf"):
                    pitch = imported_planner_pitch
                    if mode != "total":
                        rating_type = pitch

            elif action == "create_player":
                players, selected_ids, success, error, calibration_message, xhr_resp = _handle_create_player(request.form, is_xhr, connection, players, selected_ids)
                if xhr_resp:
                    return xhr_resp

            elif action in ("save", "save_batch"):
                success, error, xhr_resp = _handle_save_match(req_data, is_xhr, connection, players)
                if xhr_resp:
                    return xhr_resp

            elif action in ("generate", "reroll"):
                try:
                    seed = int(request.form.get("seed")) if request.form.get("seed") is not None else None
                except ValueError:
                    seed = None
                if len(selected_ids) >= 2:
                    result = generate_match(selected_ids, players, ratings, rating_type, seed=seed)

        match_date = imported_planner_date or request.form.get("date", request.args.get("date", request.form.get("parsed_match_date", date.today().isoformat())))
        if parse_result and parse_result.get("match_date"):
            match_date = parse_result["match_date"]

        team_a = _get_prefilled_team_ids(request.form, "team_a", players) if request.method == "POST" and action in ("save", "create_player") else []
        team_b = _get_prefilled_team_ids(request.form, "team_b", players) if request.method == "POST" and action in ("save", "create_player") else []
        try:
            external_a = int(request.form.get("external_a", "0") or 0) if request.method == "POST" and action in ("save", "create_player") else 0
            external_b = int(request.form.get("external_b", "0") or 0) if request.method == "POST" and action in ("save", "create_player") else 0
        except (ValueError, TypeError):
            external_a, external_b = 0, 0
        goals_a = request.form.get("goals_a", "0") if request.method == "POST" else "0"
        goals_b = request.form.get("goals_b", "0") if request.method == "POST" else "0"
        if parse_result and parse_result.get("kind") == "match" and not team_a and not team_b:
            team_a = parse_result.get("team_a_ids", [])
            team_b = parse_result.get("team_b_ids", [])
            external_a = parse_result.get("external_a", 0)
            external_b = parse_result.get("external_b", 0)
            goals_a = parse_result.get("goals_a") if parse_result.get("goals_a") is not None else 0
            goals_b = parse_result.get("goals_b") if parse_result.get("goals_b") is not None else 0

        player_names = {}
        for pid, data in players.items():
            pname = data["aliases"][0] if data["aliases"] else f"Player {pid}"
            player_names[pid] = pname
            player_names[str(pid)] = pname
        player_search_data = [{"id": pid, "name": player_names[pid], "positions": data.get("positions", [])} for pid, data in players.items()]

        p_conn = get_planner_connection()
        try:
            planner_events = get_planner_events_for_import(p_conn)
        finally:
            p_conn.close()

        next_id = next_match_id(connection, match_date)

        return render_template(
            "match_center.html",
            players=players,
            player_names=player_names,
            ratings=ratings,
            selected_ids=selected_ids,
            result=result,
            mode=mode,
            pitch=pitch,
            seed=seed,
            match_date=match_date,
            next_match_id=next_id,
            team_a=team_a,
            team_b=team_b,
            external_a=external_a,
            external_b=external_b,
            goals_a=goals_a,
            goals_b=goals_b,
            success=success,
            error=error,
            parse_result=parse_result,
            parse_error=parse_error,
            parser_success=parser_success,
            calibration_message=calibration_message,
            calibration_levels=CALIBRATION_LEVELS,
            certainty_levels=CERTAINTY_LEVELS,
            player_search_data=player_search_data,
            planner_events=planner_events,
        )
    finally:
        connection.close()
