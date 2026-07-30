# RB48Glicko
Table of players with Glicko rating computed by match results

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
