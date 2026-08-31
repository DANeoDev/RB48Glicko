"""Compatibility shim for the legacy Match Center save hook.

The current match-entry pipeline writes the canonical match CSV itself in
scripts.matches.match_entry.add_match().  Older web.app versions called
sync_matchhistory_csv() afterwards, so this module remains as a harmless
compatibility layer while the application still imports that legacy name.
"""


def sync_matchhistory_csv(connection):
    """Legacy no-op: add_match() already writes the match-history CSV."""
    return None
