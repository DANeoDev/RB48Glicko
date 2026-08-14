# RB48Glicko

A Glicko-2 based rating system for recreational football.

RB48Glicko tracks players, match results, ratings and player statistics in a
SQLite database. The system is designed around match-by-match rating updates
and will eventually provide player profiles and automated team matchmaking.

---

## Current Status

The core rating system is functional.

Currently implemented:

- SQLite database for players, matches and ratings
- Player IDs and multiple aliases per player
- Player positions
- Match import from CSV files
- Glicko-2 rating calculation
- Custom team-based Glicko-2 calculation
- Pre-match rating snapshots for every match
- Full Glicko recalculation
- Incremental Glicko updates for newly imported matches
- Database backups before full recalculation
- Player statistics
- Calibration ratings
- Debugging tools for inspecting rating changes

The next major step is a user interface / website for viewing and interacting
with the data.

---

## Project Structure

The project is roughly divided into three layers:

Match CSV files
      │
      ▼
import_matches.py
      │
      ▼
   SQLite DB
      │
      ├── Players
      ├── Matches
      ├── Match Players
      ├── Ratings
      ├── Match Ratings
      └── Calibrations
      │
      ▼
Glicko calculation / statistics / future UI


## 1. Current Workflow

### Adding matches

Match result files are imported into the SQLite database using:

`import_matches.py`

### Calculating ratings

For a complete recalculation:

`glicko2_calculator.py`

For normal incremental updates after adding new matches:

`glicko2_updater.py`

### Statistics

Statistics are generated from the database and combine player, match, rating and result data.

## 2. Database

The SQLite database is the central data source:

`data/rb48.db`

Main tables:

- `players` — unique players
- `aliases` — aliases belonging to players
- `positions` — player positions
- `matches` — match information and results
- `match_players` — players participating in each match
- `ratings` — current rating of each player
- `match_ratings` — rating state before each match
- `calibrations` — initial rating adjustments

Different types of information are stored separately and connected through IDs and foreign keys.

## 3. Player Data

Each player has a unique `player_id`.

Aliases are stored separately, allowing multiple names to refer to the same player.

For example:

Player 1:
- Daniel
- Daniel Peters
- Da_Pe

Positions are also stored separately, allowing players to have multiple positions while marking one as their preferred position.

## 4. Match Data

Each match has a unique `match_id`.

The `matches` table stores the match itself, including:

- date
- pitch
- number of players
- goals
- result

The `match_players` table connects individual players to a match and records which team they played for.

This keeps match information independent from the rating calculations.

## 5. Glicko-2 Rating System

## 5. Glicko-2 Rating System

RB48Glicko uses a customized implementation of the Glicko-2 rating system adapted for recreational football.

Each player has three rating values:

- Rating — The player's estimated playing strength. Higher ratings indicate stronger expected performance.

- Rating Deviation (RD) — The system's uncertainty about the player's rating. Lower RD means the rating is more reliable; higher RD means greater uncertainty.

- Volatility (Sigma) — How much the player's performance is expected to fluctuate over time. Higher volatility means the player is expected to have less consistent performances.

### Initial Values

Players start with:

- Rating: `1500`
- RD: `161.8`
- Sigma: `0.06`

The standard Glicko-2 starting RD of 350 was reduced to 161.8 because RB48Glicko is intended for a recreational football group where players starting uncertainty is assumed to be a lot lower than in the intended Glicko2 chess context.
(A player showing up for a match in this group already provides a lot more information than a random player playing his first competitive chess game)

The Sigma value of `0.06` is the standard Glicko-2 default and is currently left unchanged. It may be adjusted in the future if more match data suggests that a different level of performance volatility is more appropriate for recreational football.

### Rating Updates

Teams are represented by their average rating.

For each player, a virtual player is created using the team's rating together with the player's individual RD and Sigma. The Glicko-2 calculation then determines the rating change against the opposing team.

The resulting change is applied to the player's actual rating.

RD decreases as information about a player accumulates. Players who do not participate receive a small custom RD increase between matches, reflecting increasing uncertainty during inactivity.

## 6. Rating History

The `match_ratings` table stores the rating state of every player immediately before each match.

This makes it possible to reconstruct the rating situation at any point in the match history.

The `ratings` table contains only the current rating of each player.

## 7. Full Recalculation

`glicko2_calculator.py` recalculates the complete rating history from the beginning.

A full recalculation is useful when:

- Glicko parameters are changed
- calibration values are changed
- the rating algorithm is modified
- historical match data is corrected

The existing database is backed up before the rating data is rebuilt.

## 8. Incremental Update

`glicko2_updater.py` processes only matches that have not yet been rated.

This is the normal workflow after importing new matches.

The updater uses the current ratings as its starting point and adds the new matches to the existing rating history.

## 9. Backups

Before destructive operations such as a full Glicko recalculation, the complete SQLite database is backed up.

This allows the previous state of the project to be restored if something goes wrong.

## 9. Planned Features

- Web interface with player profiles
- Rating history and statistics
- Individual player/team combinations
- Interface for entering match results
- Automatic statistics pages
- Matchmaker for balanced teams
- Position-aware team balancing
- Separate ratings for different pitches
- Further tuning of Glicko parameters as more match data becomes available