# RB48Glicko
Table of players with Glicko rating computed by match results

HOW TO RUN AS OF NOW: 
update_matchhistory --> update_players --> glicko2_calculator

Components: 

Folder of match-results: match_id,pitch,team_a,team_b,goals_a,goals_b,winner (R for remis)
creates --> 
- Table of Players (unique IDs,aliases, position (Def, Mid, Att), initial_assesment).
#List of player IDs 
#player_id, [aliases] = list of aliases for the player, [postions] = list of positions where * indicates preferred one ; is seperator,  
#example: 1, [daniel; daniel_peters; da_pe], [def; mid*; att], 
aliases: name entries from match data associated with this player. (For example: Moritz, Mo can both refer to same ID)
Position is assigned at player creation, multiple Positions can be assigned, one main position must be assigned.

- match-history (single table with all collected match-results)
 created from update_matchhistory.py

Glicko calculator
Final Table including Glicko Rating (Total, Pitch) and various related entries 

Reach Goals: 
- Website with Player-profiles; individual ratings for unique Player team pairings, etc
- Interface for entering match results 
- Matchmaker: Creates fair teams considering Glicko (Pitch), Position

Rating System:

This project uses a customized implementation of the Glicko-2 rating system, adapted for recreational football.

**Rating Updates**

Each match is treated as an individual rating event.

Instead of rating every player directly against every opponent, each team is represented by its average strength:

The average rating of all six players is used as the team's playing strength.
For every player, a virtual player is created that inherits:
the team's average rating,
the player's personal Rating Deviation (RD),
the player's personal volatility (σ).

The Glicko-2 engine calculates the rating change for this virtual player against the opposing team's average rating. Only the resulting rating delta is then applied to the player's actual rating.

This approach allows every member of a team to receive the same performance evaluation while still respecting each player's individual uncertainty (RD) and volatility.

**Rating Deviation (RD)**

RD represents how certain the system is about a player's rating.

Players start with a moderate initial RD (currently 161.8) rather than the traditional Glicko-2 value of 350. The original value assumes that a completely new player is almost entirely unknown to the rating system. In this project, however, most players already belong to a relatively stable local football community, so it is reasonable to begin with a lower level of uncertainty. 
After every match, Glicko-2 naturally decreases a player's RD as more information becomes available.
Players who do not participate in a match receive a small custom RD increase (currently +0.618 per missed match), up to a configurable maximum RD.

This custom inactivity rule replaces Glicko-2's original rating-period inflation and is better suited for continuous match-by-match updates.

Volatility (σ)

Player volatility (σ) is handled by the standard Glicko-2 algorithm.

It measures how inconsistent a player's performances are over time. In practice, σ changes only slowly and usually remains close to its initial value unless a player consistently performs far above or below expectations.