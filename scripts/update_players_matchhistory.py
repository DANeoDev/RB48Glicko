# PLACEHOLDER - this will update palyers.csv and matchhistory.csv

#pseudocode: 
# import contents of matches folder
# read names in team_a, team_b of each row of each file, pass cleannames (lower case, connected by "_") of names 
# for each cleanname check in players.csv:
# does cleanname match an existing cleanname assigned to a player id? 
# if yes: do nothing
# if no:
#   
#   does cleanname match to a starting part of a cleanname assigned to a player id? 
#     --> promppt (example): Do you want to add "mo" as an identifier for mo_re, [moritz_regenstein]? yes --> add mo to the list of cleannames for mo_re, no --> print "invalid entry, please update the names of match_id"
#   does cleanname match to a starting part of multiple cleanname assigned to a player_id's? --> print "invalid entry, please update the names of match_id" (example: Kons matches to ko_st, [konstantin_steuer] and ko_ex, [konstantin_example]
#
# Code Skeleton: 

import all data in folder matches
import data/players.csv #makes current data available

def normalize_name(entry): #normalizes name of team members of each game
def resolve_player(normalized_name): #scans for existing aliases, passes player_id or no result
def assigner(normalized_name): #the function that creates new player_id's or assigns an alias to an existing player_id. Input: entry, logic uses normalize_name and alias_scanner, Output: list of player_id

# then we have to update the data/players.csv in a way that doesnt overwrite the old file, but only adds new information (since we don't want to lose information which had been added by hand, such as positions or aliases)




