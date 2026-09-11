"""Whole-History Rating (WHR) for team-based recreational football.

This module implements Rémi Coulom's Whole-History Rating (2008) adapted
for multi-player team sports (5v5 / 6v6). Unlike sequential Glicko-2,
WHR fits the entire match history simultaneously using maximum a posteriori (MAP)
estimation over a continuous Brownian-motion (random walk) skill trajectory.
"""

import bisect
from datetime import datetime, timedelta
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from scripts.database.database import get_connection
from scripts.database.db_matches import get_all_match_teams, get_matches, get_match_teams
from scripts.database.db_players import get_players
from scripts.database.db_ratings import get_calibrations, get_ratings
from scripts.glicko.glicko2 import (
    BOX,
    DEFAULT_RATING,
    DEFAULT_RD,
    DEFAULT_SIGMA,
    GLICKO2_SCALE,
    HF,
    TOTAL,
)
from scripts.glicko.glicko2_calculator import group_matches_by_date
from scripts.analysis.history_snapshots import get_matchday_metadata_map
from scripts.frontend.view_models import _collect_player_match_events

# Scaling constant: 400 / ln(10) ≈ 173.7178
SCALE_C = GLICKO2_SCALE

# Skill variance drift rate per scheduled matchday session (rating^2 / matchday).
# 50.0 corresponds to ~0.25 RD growth per missed matchday session, coherent with Glicko-2 inactivity ticks.
DEFAULT_W2_PER_MATCHDAY = 50.0
DEFAULT_W2_PER_DAY = DEFAULT_W2_PER_MATCHDAY  # Backward compatibility alias

# Base prior variance for uncalibrated players (default_rd^2)
DEFAULT_PRIOR_VAR = DEFAULT_RD ** 2


def _parse_date(date_str: str) -> datetime:
    """Parse YYYY-MM-DD string into a datetime object."""
    return datetime.strptime(date_str[:10], "%Y-%m-%d")


def solve_tridiagonal(diag: np.ndarray, off_diag: np.ndarray, rhs: np.ndarray) -> np.ndarray:
    """Solve symmetric tridiagonal linear system A x = rhs using the Thomas algorithm.

    A is symmetric positive-definite:
      diag: main diagonal (length n)
      off_diag: sub- and super-diagonal (length n - 1)
      rhs: right hand side vector (length n)
    """
    n = len(rhs)
    if n == 0:
        return np.array([], dtype=float)
    if n == 1:
        return np.array([rhs[0] / diag[0]], dtype=float)

    c_prime = np.zeros(n - 1, dtype=float)
    d_prime = np.zeros(n, dtype=float)

    # Forward sweep
    denom = diag[0]
    if abs(denom) < 1e-12:
        denom = 1e-12
    c_prime[0] = off_diag[0] / denom
    d_prime[0] = rhs[0] / denom

    for i in range(1, n - 1):
        denom = diag[i] - off_diag[i - 1] * c_prime[i - 1]
        if abs(denom) < 1e-12:
            denom = 1e-12
        c_prime[i] = off_diag[i] / denom
        d_prime[i] = (rhs[i] - off_diag[i - 1] * d_prime[i - 1]) / denom

    denom = diag[n - 1] - off_diag[n - 2] * c_prime[n - 2]
    if abs(denom) < 1e-12:
        denom = 1e-12
    d_prime[n - 1] = (rhs[n - 1] - off_diag[n - 2] * d_prime[n - 2]) / denom

    # Back substitution
    x = np.zeros(n, dtype=float)
    x[n - 1] = d_prime[n - 1]
    for i in range(n - 2, -1, -1):
        x[i] = d_prime[i] - c_prime[i] * x[i + 1]

    return x


def tridiagonal_inverse_diagonal(diag: np.ndarray, off_diag: np.ndarray) -> np.ndarray:
    """Compute the diagonal elements of the inverse of a symmetric tridiagonal matrix A.

    Used to compute posterior variance (RD^2) for each date.
    """
    n = len(diag)
    if n == 0:
        return np.array([], dtype=float)
    if n == 1:
        return np.array([1.0 / max(diag[0], 1e-12)], dtype=float)

    # For n <= 100, full matrix inversion is numerically bulletproof and executes in < 0.05ms
    A = np.diag(diag) + np.diag(off_diag, k=1) + np.diag(off_diag, k=-1)
    try:
        inv_A = np.linalg.inv(A)
        variances = np.diag(inv_A)
        return np.maximum(variances, 1e-12)
    except np.linalg.LinAlgError:
        return np.full(n, DEFAULT_PRIOR_VAR, dtype=float)


class TeamWHR:
    """Whole-History Rating (WHR) engine for multiplayer team games."""

    def __init__(
        self,
        w2_per_matchday: float = DEFAULT_W2_PER_MATCHDAY,
        scale_c: float = SCALE_C,
        default_rating: float = DEFAULT_RATING,
        default_rd: float = DEFAULT_RD,
        ignored_rating: float = DEFAULT_RATING,
        **kwargs,
    ):
        if "w2_per_day" in kwargs:
            w2_per_matchday = kwargs["w2_per_day"]
        self.w2_per_matchday = w2_per_matchday
        self.w2_per_day = w2_per_matchday
        self.scale_c = scale_c
        self.default_rating = default_rating
        self.default_rd = default_rd
        self.ignored_rating = ignored_rating

        # Loaded data
        self.matches: List[Dict[str, Any]] = []
        self.players: Dict[int, str] = {}
        self.calibrations: Dict[int, Dict[str, float]] = {}

        # Player indexing: player_id -> list of sorted dates [d0, d1, ...]
        self.player_dates: Dict[int, List[str]] = {}
        self.date_to_idx: Dict[str, int] = {}
        # player_id -> np.ndarray of ratings (one per date)
        self.r_profile: Dict[int, np.ndarray] = {}
        # player_id -> np.ndarray of RD uncertainties (one per date)
        self.rd_profile: Dict[int, np.ndarray] = {}

    def load_data(
        self,
        connection: Any,
        pitch_filter: Optional[str] = None,
    ) -> None:
        """Load all matches and rosters from the database."""
        raw_matches = get_matches(connection)
        all_teams = get_all_match_teams(connection)
        self.players = get_players(connection)
        self.calibrations = get_calibrations(connection)

        self.matches = []
        dates_by_player: Dict[int, set] = {}

        for match_id, m in raw_matches.items():
            pitch = m["pitch"]
            if pitch_filter and pitch_filter != TOTAL and pitch != pitch_filter:
                continue

            team_a, team_b = all_teams.get(match_id, ([], []))
            if not team_a or not team_b:
                continue

            goals_a = m["goals_a"]
            goals_b = m["goals_b"]
            if goals_a > goals_b:
                score_a = 1.0
            elif goals_a < goals_b:
                score_a = 0.0
            else:
                score_a = 0.5

            self.matches.append({
                "match_id": match_id,
                "date": m["date"],
                "pitch": pitch,
                "team_a": team_a,
                "team_b": team_b,
                "total_a": m["players_a"],
                "total_b": m["players_b"],
                "score_a": score_a,
            })

            m_date = m["date"]
            for pid in team_a + team_b:
                if pid not in dates_by_player:
                    dates_by_player[pid] = set()
                dates_by_player[pid].add(m_date)

        # Build sorted dates and initial profile
        self.player_dates = {
            pid: sorted(list(dates)) for pid, dates in dates_by_player.items()
        }

        # Build global ordered matchday index
        all_unique_dates = sorted(list({m["date"] for m in self.matches}))
        self.date_to_idx = {d: i for i, d in enumerate(all_unique_dates)}

        self.r_profile = {}
        self.rd_profile = {}
        for pid, dates in self.player_dates.items():
            init_r = self.calibrations.get(pid, {}).get("rating", self.default_rating)
            init_rd = self.calibrations.get(pid, {}).get("rd", self.default_rd)
            self.r_profile[pid] = np.full(len(dates), init_r, dtype=float)
            self.rd_profile[pid] = np.full(len(dates), init_rd, dtype=float)

    def get_player_rating_at(self, player_id: int, date: str) -> float:
        """Return the current rating estimate of player on a given date."""
        dates = self.player_dates.get(player_id)
        if not dates:
            return self.calibrations.get(player_id, {}).get("rating", self.default_rating)
        try:
            idx = dates.index(date)
            return self.r_profile[player_id][idx]
        except ValueError:
            target_dt = _parse_date(date)
            diffs = [abs((_parse_date(d) - target_dt).total_seconds()) for d in dates]
            closest_idx = int(np.argmin(diffs))
            return self.r_profile[player_id][closest_idx]

    def _team_rating(self, player_ids: List[int], total_players: int, date: str) -> float:
        """Calculate mean team rating including ignored / guest players."""
        known_ratings = [self.get_player_rating_at(pid, date) for pid in player_ids]
        ignored_count = max(0, total_players - len(player_ids))
        total_sum = sum(known_ratings) + ignored_count * self.ignored_rating
        effective_count = len(player_ids) + ignored_count
        return total_sum / max(effective_count, 1)

    def solve(
        self,
        max_iterations: int = 40,
        tolerance: float = 1e-3,
    ) -> int:
        """Solve for the MAP ratings across all players and dates simultaneously."""
        if not self.matches or not self.player_dates:
            return 0

        player_matches: Dict[Tuple[int, str], List[Tuple[Dict[str, Any], str]]] = {}
        for m in self.matches:
            m_date = m["date"]
            for pid in m["team_a"]:
                key = (pid, m_date)
                if key not in player_matches:
                    player_matches[key] = []
                player_matches[key].append((m, "a"))
            for pid in m["team_b"]:
                key = (pid, m_date)
                if key not in player_matches:
                    player_matches[key] = []
                player_matches[key].append((m, "b"))

        all_player_ids = list(self.player_dates.keys())
        iteration = 0

        for iteration in range(1, max_iterations + 1):
            max_delta = 0.0

            for pid in all_player_ids:
                dates = self.player_dates[pid]
                k_dates = len(dates)
                if k_dates == 0:
                    continue

                r_vec = self.r_profile[pid]

                diag = np.zeros(k_dates, dtype=float)
                off_diag = np.zeros(k_dates - 1, dtype=float)
                rhs = np.zeros(k_dates, dtype=float)

                # Prior Contribution
                calib = self.calibrations.get(pid, {})
                init_r = calib.get("rating", self.default_rating)
                init_rd = calib.get("rd", self.default_rd)
                init_var = init_rd ** 2

                diag[0] += 1.0 / init_var
                rhs[0] -= (r_vec[0] - init_r) / init_var

                for k in range(k_dates - 1):
                    idx_curr = self.date_to_idx.get(dates[k], k)
                    idx_next = self.date_to_idx.get(dates[k + 1], k + 1)
                    dt_matchdays = max(1, idx_next - idx_curr)
                    v_k = self.w2_per_matchday * dt_matchdays
                    inv_v = 1.0 / v_k

                    diff = r_vec[k + 1] - r_vec[k]

                    diag[k] += inv_v
                    diag[k + 1] += inv_v
                    off_diag[k] -= inv_v

                    rhs[k] += diff * inv_v
                    rhs[k + 1] -= diff * inv_v

                # Likelihood Contribution
                for k, date in enumerate(dates):
                    matches_for_date = player_matches.get((pid, date), [])
                    for m, team_role in matches_for_date:
                        r_team_a = self._team_rating(m["team_a"], m["total_a"], date)
                        r_team_b = self._team_rating(m["team_b"], m["total_b"], date)

                        diff_ab = (r_team_a - r_team_b) / self.scale_c
                        if diff_ab > 35:
                            p_a = 1.0
                        elif diff_ab < -35:
                            p_a = 0.0
                        else:
                            p_a = 1.0 / (1.0 + math.exp(-diff_ab))

                        p_b = 1.0 - p_a
                        s_a = m["score_a"]

                        team_size = m["total_a"] if team_role == "a" else m["total_b"]
                        team_size = max(1, team_size)
                        team_factor = 1.0 / math.sqrt(team_size)

                        if team_role == "a":
                            grad_m = (s_a - p_a) * team_factor / self.scale_c
                        else:
                            grad_m = ((1.0 - s_a) - p_b) * team_factor / self.scale_c

                        curv_m = (p_a * p_b) * team_factor / (self.scale_c ** 2)

                        rhs[k] += grad_m
                        diag[k] += curv_m

                delta_r = solve_tridiagonal(diag, off_diag, rhs)

                max_step = np.max(np.abs(delta_r))
                if max_step > 80.0:
                    delta_r = delta_r * (80.0 / max_step)

                r_vec += delta_r
                max_delta = max(max_delta, float(np.max(np.abs(delta_r))))

            if max_delta < tolerance:
                break

        # Compute uncertainties
        for pid in all_player_ids:
            dates = self.player_dates[pid]
            k_dates = len(dates)
            if k_dates == 0:
                continue

            diag = np.zeros(k_dates, dtype=float)
            off_diag = np.zeros(k_dates - 1, dtype=float)

            init_rd = self.calibrations.get(pid, {}).get("rd", self.default_rd)
            diag[0] += 1.0 / (init_rd ** 2)

            for k in range(k_dates - 1):
                idx_curr = self.date_to_idx.get(dates[k], k)
                idx_next = self.date_to_idx.get(dates[k + 1], k + 1)
                dt_matchdays = max(1, idx_next - idx_curr)
                v_k = self.w2_per_matchday * dt_matchdays
                inv_v = 1.0 / v_k
                diag[k] += inv_v
                diag[k + 1] += inv_v
                off_diag[k] -= inv_v

            for k, date in enumerate(dates):
                for m, team_role in player_matches.get((pid, date), []):
                    r_team_a = self._team_rating(m["team_a"], m["total_a"], date)
                    r_team_b = self._team_rating(m["team_b"], m["total_b"], date)
                    diff_ab = (r_team_a - r_team_b) / self.scale_c
                    p_a = 1.0 / (1.0 + math.exp(-max(-35, min(35, diff_ab))))
                    team_size = max(1, m["total_a"] if team_role == "a" else m["total_b"])
                    team_factor = 1.0 / math.sqrt(team_size)
                    curv_m = (p_a * (1.0 - p_a)) * team_factor / (self.scale_c ** 2)
                    diag[k] += curv_m

            variances = tridiagonal_inverse_diagonal(diag, off_diag)
            self.rd_profile[pid] = np.sqrt(variances)

        return iteration


def compute_whr_ratings(
    connection: Any,
    pitch_filter: str = TOTAL,
) -> Dict[str, Any]:
    """Calculate WHR ratings and comparative metrics against sequential Glicko-2."""
    whr = TeamWHR()
    whr.load_data(connection, pitch_filter=pitch_filter)
    iterations = whr.solve()

    live_ratings = get_ratings(connection)
    results = []

    for pid, dates in whr.player_dates.items():
        if not dates:
            continue

        p_info = whr.players.get(pid, {})
        aliases = p_info.get("aliases", []) if isinstance(p_info, dict) else []
        alias = aliases[0] if aliases else f"Player {pid}"
        final_whr_r = float(whr.r_profile[pid][-1])
        final_whr_rd = float(whr.rd_profile[pid][-1])

        glicko_entry = live_ratings.get(pid, {}).get(pitch_filter, {})
        glicko_r = float(glicko_entry.get("rating", DEFAULT_RATING))
        glicko_rd = float(glicko_entry.get("rd", DEFAULT_RD))

        delta = round(final_whr_r - glicko_r, 1)

        history = []
        for d, r, rd in zip(dates, whr.r_profile[pid], whr.rd_profile[pid]):
            history.append({
                "date": d,
                "rating": round(float(r), 1),
                "rd": round(float(rd), 1),
            })

        results.append({
            "player_id": pid,
            "alias": alias,
            "games_count": len(history),
            "glicko_rating": round(glicko_r, 1),
            "glicko_rd": round(glicko_rd, 1),
            "whr_rating": round(final_whr_r, 1),
            "whr_rd": round(final_whr_rd, 1),
            "whr_conservative": round(final_whr_r - 3 * final_whr_rd, 1),
            "glicko_conservative": round(glicko_r - 3 * glicko_rd, 1),
            "delta": delta,
            "history": history,
        })

    results.sort(key=lambda x: x["whr_rating"], reverse=True)

    g_log_losses, w_log_losses = [], []
    g_brier_scores, w_brier_scores = [], []

    for m in whr.matches:
        date = m["date"]
        actual = m["score_a"]

        whr_a = whr._team_rating(m["team_a"], m["total_a"], date)
        whr_b = whr._team_rating(m["team_b"], m["total_b"], date)
        p_whr = 1.0 / (1.0 + math.exp(-max(-35, min(35, (whr_a - whr_b) / SCALE_C))))

        team_a_glicko = [live_ratings.get(p, {}).get(pitch_filter, {}).get("rating", DEFAULT_RATING) for p in m["team_a"]]
        team_b_glicko = [live_ratings.get(p, {}).get(pitch_filter, {}).get("rating", DEFAULT_RATING) for p in m["team_b"]]
        g_a = sum(team_a_glicko) / max(len(team_a_glicko), 1)
        g_b = sum(team_b_glicko) / max(len(team_b_glicko), 1)
        p_glicko = 1.0 / (1.0 + math.exp(-max(-35, min(35, (g_a - g_b) / SCALE_C))))

        eps = 1e-6
        p_whr_clamped = min(max(p_whr, eps), 1.0 - eps)
        p_glicko_clamped = min(max(p_glicko, eps), 1.0 - eps)

        if actual == 1.0:
            w_log_losses.append(-math.log(p_whr_clamped))
            g_log_losses.append(-math.log(p_glicko_clamped))
        elif actual == 0.0:
            w_log_losses.append(-math.log(1.0 - p_whr_clamped))
            g_log_losses.append(-math.log(1.0 - p_glicko_clamped))
        else:
            w_log_losses.append(-0.5 * math.log(p_whr_clamped) - 0.5 * math.log(1.0 - p_whr_clamped))
            g_log_losses.append(-0.5 * math.log(p_glicko_clamped) - 0.5 * math.log(1.0 - p_glicko_clamped))

        w_brier_scores.append((p_whr - actual) ** 2)
        g_brier_scores.append((p_glicko - actual) ** 2)

    metrics = {
        "whr_log_loss": round(float(np.mean(w_log_losses)), 4) if w_log_losses else 0.0,
        "glicko_log_loss": round(float(np.mean(g_log_losses)), 4) if g_log_losses else 0.0,
        "whr_brier": round(float(np.mean(w_brier_scores)), 4) if w_brier_scores else 0.0,
        "glicko_brier": round(float(np.mean(g_brier_scores)), 4) if g_brier_scores else 0.0,
    }

    return {
        "players": results,
        "iterations": iterations,
        "pitch": pitch_filter,
        "metrics": metrics,
    }


def get_whr_models(connection: Any) -> Dict[str, TeamWHR]:
    """Fit and return TeamWHR models for TOTAL, BOX, and HF."""
    models = {}
    for ptype in (TOTAL, BOX, HF):
        m = TeamWHR()
        m.load_data(connection, pitch_filter=ptype)
        m.solve()
        models[ptype] = m
    return models


def get_whr_ratings_dict(
    connection: Any,
    models: Optional[Dict[str, TeamWHR]] = None,
) -> Dict[int, Dict[str, Dict[str, float]]]:
    """Return player ratings structured identically to db_ratings.get_ratings(connection).

    Format:
        {
            player_id: {
                TOTAL: {"rating": float, "rd": float, "sigma": float},
                BOX: {"rating": float, "rd": float, "sigma": float},
                HF: {"rating": float, "rd": float, "sigma": float},
            }
        }
    """
    if models is None:
        models = get_whr_models(connection)

    players = get_players(connection)
    calibrations = get_calibrations(connection)

    ratings: Dict[int, Dict[str, Dict[str, float]]] = {}
    for pid in players:
        ratings[pid] = {}
        calib = calibrations.get(pid, {})
        default_r = calib.get("rating", DEFAULT_RATING)
        default_rd = calib.get("rd", DEFAULT_RD)
        default_sigma = calib.get("sigma", DEFAULT_SIGMA)

        for ptype in (TOTAL, BOX, HF):
            model = models[ptype]
            if pid in model.player_dates and len(model.player_dates[pid]) > 0:
                final_r = float(model.r_profile[pid][-1])
                final_rd = float(model.rd_profile[pid][-1])
                ratings[pid][ptype] = {
                    "rating": round(final_r, 1),
                    "rd": round(final_rd, 1),
                    "sigma": float(DEFAULT_SIGMA),
                }
            else:
                ratings[pid][ptype] = {
                    "rating": float(default_r),
                    "rd": float(default_rd),
                    "sigma": float(default_sigma),
                }

    return ratings


def build_whr_match_history(
    connection: Any,
    players: Dict[int, Any],
    player_id: Optional[int] = None,
    rating_type: str = TOTAL,
    models: Optional[Dict[str, TeamWHR]] = None,
) -> List[Dict[str, Any]]:
    """Build match history list using retrospective WHR ratings."""
    if models is None:
        models = get_whr_models(connection)

    whr_model = models.get(rating_type, models.get(TOTAL))
    calibrations = get_calibrations(connection)
    matches = get_matches(connection)
    all_teams = get_all_match_teams(connection)

    history = []

    for match_id, match in matches.items():
        m_pitch = match["pitch"].lower()
        if rating_type == BOX and m_pitch != "box":
            continue
        if rating_type == HF and m_pitch != "hf":
            continue

        if match_id in all_teams:
            team_a, team_b = all_teams[match_id]
        else:
            team_a, team_b = get_match_teams(connection, match_id)

        if player_id is not None and player_id not in team_a and player_id not in team_b:
            continue

        match_date = match["date"]

        def _get_player_whr(pid: int) -> Tuple[float, float, float]:
            """Return (rating, rd, delta_drift) for player on match date."""
            if pid in whr_model.player_dates and match_date in whr_model.player_dates[pid]:
                idx = whr_model.player_dates[pid].index(match_date)
                r = float(whr_model.r_profile[pid][idx])
                rd = float(whr_model.rd_profile[pid][idx])
                prev_r = float(whr_model.r_profile[pid][idx - 1]) if idx > 0 else 1500.0
                drift = r - prev_r
                return r, rd, drift
            elif pid in whr_model.player_dates and len(whr_model.player_dates[pid]) > 0:
                r = float(whr_model.r_profile[pid][-1])
                rd = float(whr_model.rd_profile[pid][-1])
                return r, rd, 0.0
            else:
                calib = calibrations.get(pid, {})
                r = float(calib.get("rating", DEFAULT_RATING))
                rd = float(calib.get("rd", DEFAULT_RD))
                return r, rd, 0.0

        team_a_whr = [_get_player_whr(pid) for pid in team_a]
        team_b_whr = [_get_player_whr(pid) for pid in team_b]

        total_players_a = match["players_a"]
        total_players_b = match["players_b"]
        external_a = total_players_a - len(team_a)
        external_b = total_players_b - len(team_b)

        # Team mean rating
        sum_r_a = sum(p[0] for p in team_a_whr) + external_a * DEFAULT_RATING
        mean_r_a = sum_r_a / max(total_players_a, 1)
        sum_r_b = sum(p[0] for p in team_b_whr) + external_b * DEFAULT_RATING
        mean_r_b = sum_r_b / max(total_players_b, 1)

        # Team average RD
        sum_rd_sq_a = sum(p[1] ** 2 for p in team_a_whr) + external_a * (DEFAULT_RD ** 2)
        mean_rd_a = math.sqrt(sum_rd_sq_a / max(total_players_a, 1))
        sum_rd_sq_b = sum(p[1] ** 2 for p in team_b_whr) + external_b * (DEFAULT_RD ** 2)
        mean_rd_b = math.sqrt(sum_rd_sq_b / max(total_players_b, 1))

        # Expected score
        diff_ab = (mean_r_a - mean_r_b) / SCALE_C
        p_a = 1.0 / (1.0 + math.exp(-max(-35, min(35, diff_ab))))
        p_b = 1.0 - p_a

        # Average retrospective form drift for teams
        drift_a = sum(p[2] for p in team_a_whr) / max(len(team_a_whr), 1) if team_a_whr else 0.0
        drift_b = sum(p[2] for p in team_b_whr) / max(len(team_b_whr), 1) if team_b_whr else 0.0

        def _format_player(pid: int, info: Tuple[float, float, float]) -> Dict[str, Any]:
            p_data = players.get(pid, {})
            aliases = p_data.get("aliases", []) if isinstance(p_data, dict) else []
            name = aliases[0] if aliases else f"Player {pid}"
            return {
                "name": name,
                "rating": round(info[0], 1),
                "rd": round(info[1], 1),
                "player_id": pid,
            }

        team_a_players = [_format_player(pid, info) for pid, info in zip(team_a, team_a_whr)]
        team_b_players = [_format_player(pid, info) for pid, info in zip(team_b, team_b_whr)]
        for t in (team_a_players, team_b_players):
            t.sort(key=lambda x: (x["rating"] is not None, x["rating"] if x["rating"] is not None else 0), reverse=True)

        is_win = match["goals_a"] > match["goals_b"]
        is_loss = match["goals_a"] < match["goals_b"]
        is_draw = match["goals_a"] == match["goals_b"]

        p_team = "a" if (player_id and player_id in team_a) else ("b" if (player_id and player_id in team_b) else None)
        own_ids = [pid for pid in (team_a if p_team == "a" else team_b) if pid != player_id] if p_team else []
        opp_ids = list(team_b if p_team == "a" else team_a) if p_team else []

        history.append({
            "match_id": match_id,
            "date": match_date,
            "pitch": match["pitch"],
            "goals_a": match["goals_a"],
            "goals_b": match["goals_b"],
            "team_a": [players[pid]["aliases"][0] for pid in team_a],
            "team_b": [players[pid]["aliases"][0] for pid in team_b],
            "team_a_players": team_a_players,
            "team_b_players": team_b_players,
            "external_a": external_a,
            "external_b": external_b,
            "team_a_ids": team_a,
            "team_b_ids": team_b,
            "own_team_ids": own_ids,
            "opp_team_ids": opp_ids,
            "is_win": is_win,
            "is_loss": is_loss,
            "is_draw": is_draw,
            "goals_for": match["goals_a"] if p_team == "a" else (match["goals_b"] if p_team == "b" else None),
            "goals_against": match["goals_b"] if p_team == "a" else (match["goals_a"] if p_team == "b" else None),
            "team_a_rating": round(mean_r_a, 1),
            "team_a_rd": round(mean_rd_a, 1),
            "team_b_rating": round(mean_r_b, 1),
            "team_b_rd": round(mean_rd_b, 1),
            "team_a_expected": p_a,
            "team_b_expected": p_b,
            "delta_a": round(drift_a, 1) if drift_a != 0.0 else None,
            "delta_b": round(drift_b, 1) if drift_b != 0.0 else None,
            "rating_delta": round(mean_r_a - mean_r_b, 1),
            "player_delta": None,
            "player_team": p_team,
            "is_session_pending": False,
            "is_session_final": False,
            "session_match_num": 1,
            "session_matches_total": 1,
            "session_tooltip": "WHR Retrospektiv: Kontinuierliche Glättung über die Gesamthistorie",
        })

    return history


def _get_whr_state_at(
    model: TeamWHR,
    pid: int,
    target_date: str,
    default_r: float = DEFAULT_RATING,
    default_rd: float = DEFAULT_RD,
) -> Tuple[float, float]:
    """Evaluate continuous-time WHR rating and RD at an arbitrary matchday date.

    Uses exact profile if played on target_date, Brownian bridge interpolation if
    between played matchdays, and Brownian drift after the last played matchday.
    """
    dates = model.player_dates.get(pid, [])
    if not dates:
        return default_r, default_rd

    if target_date in dates:
        idx = dates.index(target_date)
        return float(model.r_profile[pid][idx]), float(model.rd_profile[pid][idx])

    past_indices = [i for i, d in enumerate(dates) if d < target_date]
    future_indices = [i for i, d in enumerate(dates) if d > target_date]

    if not past_indices:
        # Before first played game in this track
        return default_r, default_rd

    idx_prev = past_indices[-1]
    d_prev = dates[idx_prev]
    r_prev = float(model.r_profile[pid][idx_prev])
    rd_prev = float(model.rd_profile[pid][idx_prev])

    all_d = sorted(model.date_to_idx.keys())
    if target_date in model.date_to_idx:
        tau_target = model.date_to_idx[target_date]
    else:
        tau_idx = bisect.bisect_right(all_d, target_date) - 1
        tau_target = max(0, min(tau_idx, len(all_d) - 1))

    if not future_indices:
        # After last played game: drift forward
        tau_prev = model.date_to_idx.get(d_prev, 0)
        dt_matchdays = max(0, tau_target - tau_prev)
        var = (rd_prev ** 2) + model.w2_per_matchday * dt_matchdays
        return r_prev, math.sqrt(var)

    # Between two played games: Brownian bridge
    idx_next = future_indices[0]
    d_next = dates[idx_next]
    tau_prev = model.date_to_idx.get(d_prev, 0)
    tau_next = model.date_to_idx.get(d_next, 0)
    total_d_tau = max(1, tau_next - tau_prev)
    alpha = max(0.0, min(1.0, (tau_target - tau_prev) / total_d_tau))

    r_next = float(model.r_profile[pid][idx_next])
    rd_next = float(model.rd_profile[pid][idx_next])

    r_interp = (1.0 - alpha) * r_prev + alpha * r_next
    bridge_var = alpha * (1.0 - alpha) * total_d_tau * model.w2_per_matchday
    var_interp = (1.0 - alpha) * (rd_prev ** 2) + alpha * (rd_next ** 2) + bridge_var
    return r_interp, math.sqrt(var_interp)


def compute_whr_historical_snapshots(
    connection: Any,
    models: Optional[Dict[str, TeamWHR]] = None,
) -> Dict[str, Any]:
    """Compute chronological retrospective WHR rating snapshots after each matchday (session),
    plus aggregated month-end snapshots.

    Format matches history_snapshots.compute_historical_snapshots for 100% time-scrollbar compatibility.
    """
    if models is None:
        models = get_whr_models(connection)

    matches = get_matches(connection)
    players = get_players(connection)
    calibrations = get_calibrations(connection)
    metadata_map = get_matchday_metadata_map(connection, matches=matches)
    sessions = group_matches_by_date(matches)
    sorted_dates = sorted(sessions.keys())
    match_teams_map = get_all_match_teams(connection)

    sorted_matches_all = sorted(matches.values(), key=lambda m: (m["date"], m["match_id"]))
    player_events = _collect_player_match_events(connection, sorted_matches_all, players)

    # Cumulative stats tracking per player and pitch
    cumulative_stats: Dict[int, Dict[str, Dict[str, int]]] = {}
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

        # 2. Assemble leaderboard snapshot with retrospective WHR ratings and deltas
        leaderboard = []
        for pid, pdata in players.items():
            calib = calibrations.get(pid, {})
            def_r = calib.get("rating", DEFAULT_RATING)
            def_rd = calib.get("rd", DEFAULT_RD)
            p_stats = cumulative_stats.get(pid, {})

            player_entry: Dict[str, Any] = {
                "player_id": pid,
                "alias": pdata["aliases"][0] if pdata.get("aliases") else f"Player {pid}",
            }

            for pkey in (TOTAL, BOX, HF):
                whr_m = models[pkey]
                s_item = p_stats.get(pkey, {"games": 0, "wins": 0, "losses": 0, "draws": 0})
                g = s_item["games"]
                w = s_item["wins"]
                losses = s_item["losses"]
                wp = round((w / g * 100.0), 1) if g > 0 else 0.0

                r_val, rd_val = _get_whr_state_at(whr_m, pid, date_str, def_r, def_rd)
                c_val = r_val - 3.0 * rd_val

                all_p_evts = player_events.get(pid, {}).get(pkey, [])
                evts_up_to_date = [e for e in all_p_evts if e["date"] <= date_str]

                def _calc_whr_subset_delta(subset_evts: List[Dict[str, Any]], cutoff_d: Optional[str] = None) -> Dict[str, Any]:
                    sub_g = len(subset_evts)
                    sub_w = sum(1 for e in subset_evts if e.get("is_win"))
                    sub_l = sum(1 for e in subset_evts if e.get("is_loss"))
                    sub_wp = round((sub_w / sub_g * 100.0), 1) if sub_g > 0 else 0.0

                    if cutoff_d is not None:
                        b_r, b_rd = _get_whr_state_at(whr_m, pid, cutoff_d, def_r, def_rd)
                    elif subset_evts:
                        first_e = subset_evts[0]
                        first_date = first_e["date"]
                        dates_before = [d for d in whr_m.player_dates.get(pid, []) if d < first_date]
                        if dates_before:
                            b_r, b_rd = _get_whr_state_at(whr_m, pid, dates_before[-1], def_r, def_rd)
                        else:
                            b_r, b_rd = def_r, def_rd
                    else:
                        return {
                            "conservative": 0.0,
                            "rating": 0.0,
                            "rd": 0.0,
                            "games": 0,
                            "wins": 0,
                            "losses": 0,
                            "win_percent": 0.0,
                        }

                    b_c = b_r - 3.0 * b_rd
                    return {
                        "conservative": round(c_val - b_c, 1),
                        "rating": round(r_val - b_r, 1),
                        "rd": round(rd_val - b_rd, 1),
                        "games": sub_g,
                        "wins": sub_w,
                        "losses": sub_l,
                        "win_percent": sub_wp,
                    }

                session_evts = [e for e in evts_up_to_date if e["date"] == date_str]
                month_evts = [e for e in evts_up_to_date if e["date"] >= cutoff_month]
                quarter_evts = [e for e in evts_up_to_date if e["date"] >= cutoff_quarter]
                year_evts = [e for e in evts_up_to_date if e["date"] >= cutoff_year]

                deltas = {
                    "game": _calc_whr_subset_delta(session_evts, cutoff_d=None),
                    "month": _calc_whr_subset_delta(month_evts, cutoff_d=cutoff_month),
                    "quarter": _calc_whr_subset_delta(quarter_evts, cutoff_d=cutoff_quarter),
                    "year": _calc_whr_subset_delta(year_evts, cutoff_d=cutoff_year),
                }

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

    # Group into month-end snapshots
    month_groups: Dict[str, List[Dict[str, Any]]] = {}
    for snap in matchdays_snapshots:
        month_groups.setdefault(snap["month_key"], []).append(snap)

    months_snapshots = []
    for month_key in sorted(month_groups.keys()):
        m_snaps = month_groups[month_key]
        last_snap = m_snaps[-1]
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

    matchdays_snapshots.reverse()
    months_snapshots.reverse()

    return {
        "matchdays": matchdays_snapshots,
        "months": months_snapshots,
    }


def compute_whr_leaderboard_deltas(
    connection: Any,
    models: Optional[Dict[str, TeamWHR]] = None,
    snapshots: Optional[Dict[str, Any]] = None,
) -> Dict[int, Dict[str, Dict[str, Any]]]:
    """Compute leaderboard deltas dict {pid: {pitch: {interval: delta_dict}}} from WHR snapshots."""
    if snapshots is None:
        snapshots = compute_whr_historical_snapshots(connection, models=models)

    matchdays = snapshots.get("matchdays", [])
    if not matchdays:
        return {}

    latest_leaderboard = matchdays[0].get("leaderboard", [])
    deltas: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for p in latest_leaderboard:
        pid = p["player_id"]
        deltas[pid] = {
            "total": p.get(TOTAL, {}).get("deltas", {}),
            "box": p.get(BOX, {}).get("deltas", {}),
            "hf": p.get(HF, {}).get("deltas", {}),
        }
    return deltas


def print_whr_summary():
    """Run WHR on the active database and print a comprehensive console table."""
    conn = get_connection()
    try:
        report = compute_whr_ratings(conn, pitch_filter=TOTAL)
    finally:
        conn.close()

    players = report["players"]
    print(f"\n{'='*75}")
    print(" RB48 WHOLE-HISTORY RATING (WHR) PROTOTYPE REPORT")
    print(f" Pitch: TOTAL | Converged in {report['iterations']} Newton iterations")
    print(f"{'='*75}")
    print(f" Explanatory Log-Loss: WHR {report['metrics']['whr_log_loss']} vs Glicko-2 {report['metrics']['glicko_log_loss']}")
    print(f" Explanatory Brier:    WHR {report['metrics']['whr_brier']} vs Glicko-2 {report['metrics']['glicko_brier']}")
    print(f"{'-'*75}")
    print(f"{'Rank':<5} {'Player':<20} {'Glicko-2':<12} {'WHR':<12} {'Delta':<8} {'Games'}")
    print(f"{'-'*75}")

    for idx, p in enumerate(players, start=1):
        g_str = f"{p['glicko_rating']} (±{int(p['glicko_rd'])})"
        w_str = f"{p['whr_rating']} (±{int(p['whr_rd'])})"
        d_str = f"+{p['delta']}" if p['delta'] > 0 else f"{p['delta']}"
        print(f"{idx:<5} {p['alias'][:19]:<20} {g_str:<12} {w_str:<12} {d_str:<8} {p['games_count']}")

    print(f"{'='*75}\n")


if __name__ == "__main__":
    print_whr_summary()
