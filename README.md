# RB48Glicko
Table of players with Glicko rating computed by match results

Components: 

Folder of match-results (Team vs Team; Team is a list of Players; Pitch (Box, HF))
creates --> 
- Table of Players (unique IDs, position (Def, Mid, Att)). Position is assigned, not read from statistics. Multiple Positions can be assigned.
- match-history (single table with all collected match-results)

Glicko calculator
Final Table including Glicko Rating (Total, Pitch) and various related entries 

Reach Goals: 
- Website with Player-profiles; individual ratings for unique Player team pairings, etc
- Interface for entering match results 
- Matchmaker: Creates fair teams considering Glicko (Pitch), Position
