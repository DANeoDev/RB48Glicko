# RB48Glicko

A Glicko-2 based rating system for recreational football.

RB48Glicko tracks players, match results, ratings and statistics in a SQLite
database and provides a web interface for exploring and interacting with the
resulting data.

The project combines a customized Glicko-2 implementation with a database
backend, match-data processing, statistical analysis and a Flask-based web
interface. A separate simulation environment is also being developed to test
the rating system against matches generated from known, hidden player
strengths.

---

## Current Status

The core rating system and web application are functional and under active
development.

Currently implemented:

Currently implemented:

- SQLite database for players, matches, ratings and statistics
- Player management with unique IDs, aliases and positions
- Match entry through the web interface, including AI-assisted extraction from images and text via an external AI API
- Manual match import via CSV files
- Customized Glicko-2 rating system adapted for recreational team football
- Team-based rating calculation with separate ratings for different match types / pitches
- Custom inactivity handling and initial player rating calibration
- Full historical rating recalculation and incremental updates for new matches
- Player profiles with rating history, match history and statistics
- Match Center for viewing and managing match data
- Matchmaker for creating balanced teams
- Model-analysis tools for evaluating rating predictions and calibration
- Separate simulation environment for testing the rating system with synthetic match data

The project is still evolving, particularly in the areas of matchmaking,
model analysis and simulation.

---

## Demo / Simulation

RB48Glicko includes a separate `demo-simulation` version of the project.

The purpose of the simulation is to provide a reproducible environment in
which the rating system can be evaluated without exposing or depending on
the project's real match database.

The simulation generates synthetic players and matches from predefined,
hidden player strengths. The generated results are then processed through
the same general rating pipeline used by RB48Glicko.

This makes it possible to compare:

- the hidden "true" player strength
- the strength estimated by Glicko-2
- predicted match probabilities
- actual match outcomes
- rating convergence over time
- calibration of predicted probabilities

The demo uses a separate SQLite database and simulation-specific scripts.
These files are kept separate from the normal application workflow.

A simulated dataset will be available in the `demo-simulation` branch once
the demo environment is complete.

---

## Project Architecture

At a high level, RB48Glicko follows this data flow:

    Match input
          │
          ├── Web interface
          │     ├── Manual entry
          │     ├── Image parsing ──► AI API
          │     └── Text parsing  ──► AI API
          │
          └── CSV files
                 │
                 ▼
           Match processing
                 │
                 ▼
              SQLite
                 │
                 ├── Players
                 ├── Aliases
                 ├── Positions
                 ├── Matches
                 ├── Match Players
                 ├── Ratings
                 ├── Match Ratings
                 └── Calibrations
                 │
                 ▼
          Glicko calculation
                 │
                 ├── Rating history
                 ├── Player statistics
                 ├── Model analysis
                 └── Web interface


The codebase is roughly organized into the following areas:

- `scripts/database/` — database access and maintenance
- `scripts/glicko/` — Glicko-2 implementation and rating calculations
- `scripts/matches/` — match import and match-data processing
- `scripts/matchmaking/` — team balancing and matchmaker functionality
- `scripts/analysis/` — statistical and model analysis
- `scripts/frontend/` — data preparation for the web interface
- `web/` — Flask application, templates and frontend assets
- `scripts/simulation/` — synthetic data generation and simulation tools

---

## 1. Match Data Workflow

Match results can enter the system through several different workflows.

### Manual entry

Matches can be entered directly through the web interface. This provides
full control over the players, teams, result and other match information.

### AI-assisted entry

The web interface can also use an external AI API to parse match information
from images or text.

For example, a match result can be provided as an image containing the
recorded teams and result, or as unstructured text. The AI parser extracts
the relevant information and converts it into structured match data.

This is intended as an accelerator of the input process. The parsed information can 
be reviewed and corrected through the
interface before it is stored.

This makes it possible to enter matches from existing records without having
to manually transcribe every player and result.

### CSV import

Match data can also be imported directly from CSV files.

CSV files provide a convenient structured format for bulk imports and for
reproducible data processing.

Regardless of how a match enters the system, the resulting structured match
data is stored in the SQLite database and becomes available to the rating,
statistics and web application layers.

---

## 2. Database

The SQLite database stores the persistent application data.

The default local database is:

    data/rb48.db

The main tables are:

- `players` — unique players
- `aliases` — aliases belonging to players
- `positions` — player positions
- `matches` — match information and results
- `match_players` — players participating in each match
- `ratings` — current rating of each player
- `match_ratings` — rating state immediately before each match
- `calibrations` — initial rating adjustments

Player, match and rating information are kept separate and connected through
IDs and foreign keys.

---

## 3. Player Data

Each player has a unique `player_id`.

Aliases are stored separately, allowing multiple names to refer to the same
player.

For example:

    Player 1
    ├── Daniel
    ├── Daniel Peters
    └── Da_Pe

Positions are also stored separately. A player can have multiple positions
while one position can be marked as the preferred position.

This separation allows player identity to remain independent from the names
used in individual match records.

---

## 4. Match Data

Each match has a unique `match_id`.

The `matches` table stores information about the match itself, including:

- date
- pitch / match type
- number of players
- goals
- result

The `match_players` table connects individual players to each match and
records which team they played for.

This keeps match information independent from the rating calculations and
allows the rating system to be recalculated from the underlying match
history.

---

## 5. Glicko-2 Rating System

RB48Glicko uses a customized implementation of the Glicko-2 rating system
adapted for recreational football.

Each player has three Glicko-2 values:

### Rating

The estimated playing strength of the player.

A higher rating indicates stronger expected performance.

### Rating Deviation (RD)

The uncertainty associated with the player's rating.

A lower RD means that the rating is considered more reliable, while a higher
RD indicates greater uncertainty.

### Volatility (Sigma)

The expected degree of variation in a player's performances.

A higher volatility means that the player's performance is expected to vary
more substantially between rating periods.

### Initial Values

Players start with:

- Rating: `1500`
- RD: `161.8`
- Sigma: `0.06`

The standard Glicko-2 starting RD of 350 was reduced to 161.8 because the
context of RB48Glicko differs substantially from the original competitive
rating scenarios for which Glicko was designed.

In this recreational football environment, participating in a match already
provides considerably more information about a player's playing level than
the initial uncertainty assumed by the standard Glicko-2 configuration.

The Sigma value of `0.06` is the standard Glicko-2 default and is currently
left unchanged. It can be adjusted in the future if additional match data
suggests that a different level of performance volatility is appropriate.

---

## 6. Team-Based Rating Calculation

Unlike a conventional one-versus-one rating system, RB48Glicko evaluates
matches between teams.

A team's rating is calculated from the ratings of its participating players.

The team rating is represented by the arithmetic mean of the players'
ratings.

The team RD uses a quadratic mean of the participating players' RDs. This
gives players with greater rating uncertainty a proportionally larger
influence on the team's uncertainty.

For the individual update, a virtual player is constructed using the team's
rating together with the individual player's RD and Sigma.

The Glicko-2 calculation is then performed against the opposing team's
virtual rating, and the resulting change is applied to the individual
player's actual rating.

This allows a team-based match to update individual player ratings while
still accounting for differences in individual rating uncertainty.

---

## 7. Rating Updates and Inactivity

RB48Glicko supports both complete recalculation and incremental rating
updates.

Rating deviation decreases as information about a player accumulates.

Players who do not participate in matches receive a custom RD increase
between matches. This reflects the increasing uncertainty about a player's
current ability during periods of inactivity.

Different rating categories can track inactivity separately depending on
the type of match in which the player participates.

---

## 8. Rating History

The `match_ratings` table stores the rating state of every relevant player
immediately before each match.

This provides a historical snapshot of the rating system and makes it
possible to reconstruct the rating situation at any point in the match
history.

The current rating is stored separately in the `ratings` table.

This distinction is important because it allows the application to answer
questions such as:

- What rating did a player have before a particular match?
- What win probability did the rating system imply at that time?
- How did a match change the player's rating?
- How did rating uncertainty evolve over time?

---

## 9. Full Recalculation

`glicko2_calculator.py` recalculates the complete rating history from the
beginning of the available match data.

A full recalculation is useful when:

- Glicko parameters are changed
- calibration values are changed
- the rating algorithm is modified
- historical match data is corrected

Before destructive recalculation, the existing database is backed up so that
the previous state can be restored if necessary.

---

## 10. Incremental Updates

`glicko2_updater.py` processes matches that have not yet been rated.

This is the normal workflow after new matches have been imported.

Instead of recalculating the complete history, the updater uses the current
ratings as its starting point and processes only the newly available matches.

This makes normal updates considerably faster while retaining the same
rating history structure.

---

## 11. Calibration and Model Analysis

RB48Glicko includes tools for evaluating how well the rating system reflects
actual match outcomes.

The system can compare predicted match probabilities with observed results
and analyze the calibration of those predictions.

This is particularly useful because a rating system should not only produce
an ordering of players, but should also produce meaningful estimates of
relative win probabilities.

Model-analysis tools are being developed to investigate:

- predicted versus observed win rates
- calibration of favourite predictions
- rating differences
- goal-difference distributions
- performance across different pitch types
- convergence of ratings
- other properties of the rating model

The simulation environment provides an additional way to evaluate these
properties because the underlying player strengths are known.

---

## 12. Web Application

RB48Glicko includes a Flask-based web application for interacting with the
rating system.

The current interface provides functionality for:

- viewing player rankings
- viewing player profiles
- exploring rating history
- viewing player statistics
- viewing match history
- entering match results
- parsing match information from images or text
- managing match data
- using the matchmaker
- exploring model-analysis results

The web application is intended to provide both a practical interface for
the football group and a visual way of exploring the behavior of the rating
system.

---

## 13. Matchmaker

RB48Glicko includes a matchmaker for creating balanced teams.

The matchmaker uses player ratings and additional player information to
construct teams intended to have similar expected playing strength.

Position information can also be used when balancing teams.

The matchmaker is an ongoing area of development, particularly with regard
to evaluating how "fair" generated teams actually are.

---

## 14. Simulation Environment

The simulation environment is designed as a controlled test environment for
the rating system.

Synthetic players are assigned hidden underlying strengths. Matches are then
generated from those strengths, producing a dataset where the true
properties of the players are known even though the rating system itself
does not receive that information.

The rating system can then be run on the generated matches and compared
against the hidden ground truth.

This allows experiments that would be difficult or impossible with real
football data alone, including testing:

- rating convergence
- rating accuracy
- probability calibration
- effects of different starting conditions
- effects of inactivity
- behavior with different player-strength distributions
- behavior over large numbers of matches

The simulation code lives under:

    scripts/simulation/

The simulation uses a separate database so that generated data does not
interfere with the real RB48Glicko dataset.

---

## 15. Backups and Data Safety

Before destructive operations such as a full Glicko recalculation, the
complete SQLite database is backed up.

This provides a recovery point if a recalculation or database operation
produces an unexpected result.

Generated data and local databases are intentionally kept outside the public
source history.

---

## Project Goals

The long-term goal of RB48Glicko is to provide a complete rating and
matchmaking system for recreational football while also serving as a
practical environment for experimenting with rating algorithms and
statistical model evaluation.

The project combines:

- Python
- Flask
- SQLite
- Glicko-2
- external AI API integration
- data processing
- statistical analysis
- visualization
- team matchmaking
- synthetic simulation

The system is being developed iteratively, with real match data providing
the practical use case and the simulation environment providing a controlled
way to test and evaluate the underlying rating model.