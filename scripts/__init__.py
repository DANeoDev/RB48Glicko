"""RB48Glicko backend package.

The project was reorganized into functional subpackages. The aliases below
keep older internal imports working while the codebase is migrated to the
canonical package paths. They are module aliases, not duplicate source files.
"""

import importlib
import sys


# Register dependencies before modules that still use legacy imports.
_ALIAS_ORDER = [
    ("glicko2", "scripts.glicko.glicko2"),
    ("db_players", "scripts.database.db_players"),
    ("db_ratings", "scripts.database.db_ratings"),
    ("db_matches", "scripts.database.db_matches"),
    ("database", "scripts.database.database"),
    ("glicko2_calculator", "scripts.glicko.glicko2_calculator"),
    ("glicko2_updater", "scripts.glicko.glicko2_updater"),
    ("import_matches", "scripts.matches.import_matches"),
    ("matchhistory_sync", "scripts.matches.matchhistory_sync"),
    ("match_entry", "scripts.matches.match_entry"),
    ("matchmaker", "scripts.matchmaking.matchmaker"),
    ("model_analysis", "scripts.analysis.model_analysis"),
    ("view_models", "scripts.frontend.view_models"),
    ("wipe_matchdata", "scripts.database.maintenance.wipe_matchdata"),
    ("wipe_ratings", "scripts.database.maintenance.wipe_ratings"),
]

for _old_name, _new_name in _ALIAS_ORDER:
    sys.modules.setdefault(
        f"{__name__}.{_old_name}",
        importlib.import_module(_new_name),
    )

del _old_name, _new_name, _ALIAS_ORDER, importlib, sys
