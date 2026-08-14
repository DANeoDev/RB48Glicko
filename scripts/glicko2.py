"""
Glicko-2 rating system implementation.

This module contains only the mathematical Glicko-2 engine.
It does not know anything about players, CSV files, teams,
aliases, or match history.
"""

from dataclasses import dataclass
import math


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_RATING = 1500.0
DEFAULT_RD = 161.80339
IGNORED_RD = 261.803399
DEFAULT_SIGMA = 0.06
INACTIVITY_RD_TICK = 0.6180339

DEFAULT_TAU = 1.0
DEFAULT_EPSILON = 0.000001

GLICKO2_SCALE = 173.7178

TOTAL = "total"
BOX = "box"
HF = "hf"

WIN = 1.0
DRAW = 0.5
LOSS = 0.0


# ---------------------------------------------------------------------------
# Rating object
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Rating:
    """
    Represents a player's Glicko-2 rating.

    rating:
        The player's rating value.

    rd:
        Rating deviation (uncertainty).

    sigma:
        Rating volatility.
    """

    rating: float = DEFAULT_RATING
    rd: float = DEFAULT_RD
    sigma: float = DEFAULT_SIGMA

@dataclass(slots=True)
class _GlickoRating:
    mu: float
    phi: float
    sigma: float


# ---------------------------------------------------------------------------
# Glicko-2 Engine
# ---------------------------------------------------------------------------

class Glicko2:

    def __init__(
        self,
        default_rating: float = DEFAULT_RATING,
        default_rd: float = DEFAULT_RD,
        default_sigma: float = DEFAULT_SIGMA,
        tau: float = DEFAULT_TAU,
        epsilon: float = DEFAULT_EPSILON,
    ):
        self.default_rating = default_rating
        self.default_rd = default_rd
        self.default_sigma = default_sigma

        self.tau = tau
        self.epsilon = epsilon


    def create_rating(
        self,
        rating: float | None = None,
        rd: float | None = None,
        sigma: float | None = None,
    ) -> Rating:

        return Rating(
            rating=self.default_rating if rating is None else rating,
            rd=self.default_rd if rd is None else rd,
            sigma=self.default_sigma if sigma is None else sigma,
        )


    # -----------------------------------------------------------------------
    # Scale conversion
    #
    # Glicko-2 internally works with a transformed scale.
    # These methods isolate that conversion.
    # -----------------------------------------------------------------------

    def _scale_down(self, player: Rating) -> _GlickoRating:

        return _GlickoRating(
            mu=(player.rating - DEFAULT_RATING) / GLICKO2_SCALE,
            phi=player.rd / GLICKO2_SCALE,
            sigma=player.sigma,
        )


    def _scale_up(self, player: Rating) -> _GlickoRating:

        return Rating(
            rating=player.mu * GLICKO2_SCALE + DEFAULT_RATING,
            rd=player.phi * GLICKO2_SCALE,
            sigma=player.sigma,
        )

        # -----------------------------------------------------------------------
    # Glicko-2 mathematical helpers
    # -----------------------------------------------------------------------

    def _reduce_impact(self, opponent: _GlickoRating) -> float:
        """
        Calculate the impact of an opponent's rating deviation.

        Higher uncertainty in the opponent means their result influences
        your rating less.
        """

        return 1 / math.sqrt(
            1 + (3 * opponent.phi ** 2) / (math.pi ** 2)
        )


    def _expected_score(
        self,
        player: _GlickoRating,
        opponent: _GlickoRating,
        impact: float,
    ) -> float:
        """
        Calculate expected score against an opponent.
        """

        return 1 / (
            1 + math.exp(
                -impact * (player.mu - opponent.mu)
            )
        )


    def _determine_sigma(
        self,
        player: Rating,
        difference: float,
        variance: float,
    ) -> float:
        """
        Determine new volatility (sigma).

        This is the iterative step of the Glicko-2 algorithm.
        """

        phi = player.phi

        difference_squared = difference ** 2

        alpha = math.log(player.sigma ** 2)


        def f(x):

            temp = (
                phi ** 2
                + variance
                + math.exp(x)
            )

            a = (
                math.exp(x)
                * (difference_squared - temp)
                / (2 * temp ** 2)
            )

            b = (x - alpha) / (self.tau ** 2)

            return a - b


        a = alpha


        if difference_squared > phi ** 2 + variance:

            b = math.log(
                difference_squared
                - phi ** 2
                - variance
            )

        else:

            k = 1

            while f(alpha - k * math.sqrt(self.tau ** 2)) < 0:
                k += 1

            b = alpha - k * math.sqrt(self.tau ** 2)


        f_a = f(a)
        f_b = f(b)


        while abs(b - a) > self.epsilon:

            c = (
                a
                + (a - b)
                * f_a
                / (f_b - f_a)
            )

            f_c = f(c)


            if f_c * f_b < 0:

                a = b
                f_a = f_b

            else:

                f_a /= 2


            b = c
            f_b = f_c


        return math.exp(a / 2)

        # -----------------------------------------------------------------------
    # Public rating update
    # -----------------------------------------------------------------------

    def update_rating(
        self,
        player: Rating,
        series: list[tuple[float, Rating]],
    ) -> Rating:
        """
        Update a player's rating after one rating period.

        series contains:
            (actual_score, opponent_rating)

        Example:
            [
                (WIN, opponent),
                (LOSS, opponent),
            ]
        """

        player = self._scale_down(player)


        if not series:

            new_phi = math.sqrt(
                player.phi ** 2
                + player.sigma ** 2
            )

            return self._scale_up(
                _GlickoRating(
                    mu=player.mu,
                    phi=new_phi,
                    sigma=player.sigma,
                )
            )


        variance_inverse = 0
        difference = 0


        for score, opponent in series:

            opponent = self._scale_down(opponent)


            impact = self._reduce_impact(opponent)

            expected = self._expected_score(
                player,
                opponent,
                impact,
            )


            variance_inverse += (
                impact ** 2
                * expected
                * (1 - expected)
            )


            difference += (
                impact
                * (score - expected)
            )


        variance = 1 / variance_inverse

        difference /= variance_inverse


        sigma = self._determine_sigma(
            player,
            difference,
            variance,
        )


        # Update RD

        phi_star = math.sqrt(
            player.phi ** 2
            + sigma ** 2
        )


        # Update rating

        new_phi = 1 / math.sqrt(
            1 / phi_star ** 2
            + 1 / variance
        )


        new_mu = (
            player.mu
            + new_phi ** 2
            * (difference/variance)
        )


        return self._scale_up(
            _GlickoRating(
                mu=new_mu,
                phi=new_phi,
                sigma=sigma,
            )
        )

        # -----------------------------------------------------------------------
    # Convenience methods
    # -----------------------------------------------------------------------

    def update_1vs1(
        self,
        player1: Rating,
        player2: Rating,
        drawn: bool = False,
    ) -> tuple[Rating, Rating]:
        """
        Update two players after a 1v1 match.

        Useful for testing the engine.
        """

        player1_result = DRAW if drawn else WIN
        player2_result = DRAW if drawn else LOSS


        new_player1 = self.update_rating(
            player1,
            [
                (player1_result, player2)
            ],
        )


        new_player2 = self.update_rating(
            player2,
            [
                (player2_result, player1)
            ],
        )


        return new_player1, new_player2



    def quality_1vs1(
        self,
        player1: Rating,
        player2: Rating,
    ) -> float:
        """
        Estimate match quality between two players.

        Returns:
            1.0 = perfectly balanced
            0.0 = completely mismatched
        """

        player1_scaled = self._scale_down(player1)
        player2_scaled = self._scale_down(player2)


        expected1 = self._expected_score(
            player1_scaled,
            player2_scaled,
            self._reduce_impact(player2_scaled),
        )


        expected2 = self._expected_score(
            player2_scaled,
            player1_scaled,
            self._reduce_impact(player1_scaled),
        )


        expected = (
            expected1
            + expected2
        ) / 2


        return 2 * (
            0.5
            - abs(0.5 - expected)
        )