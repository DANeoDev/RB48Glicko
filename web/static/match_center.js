document.addEventListener('DOMContentLoaded', () => {
    const enterMatch = document.getElementById('enter-match');
    if (!enterMatch) return;

    const parserForm = document.getElementById('mc-form');
    const parserStateKey = 'rb48_match_center_parser_state';
    const matchmakerForm = [...document.querySelectorAll('form')].find(form =>
        form.querySelector('button[name="action"][value="generate"]')
    );

    if (parserForm && matchmakerForm && parserForm.querySelector('[name="parsed_kind"]')) {
        matchmakerForm.addEventListener('submit', () => {
            const get = name => parserForm.querySelector(`[name="${name}"]`)?.value || '';
            const players = [...parserForm.querySelectorAll('[name="parsed_player"]')].map(x => x.value);
            sessionStorage.setItem(parserStateKey, JSON.stringify({
                kind: get('parsed_kind'),
                date: get('parsed_match_date'),
                teamA: get('parsed_team_a'),
                teamB: get('parsed_team_b'),
                goalsA: get('parsed_goals_a'),
                goalsB: get('parsed_goals_b'),
                players
            }));
        });
    }

    // Restore imported facts after generating teams. The generated Matchmaker
    // result remains separate until the user explicitly chooses to use it.
    const saved = sessionStorage.getItem(parserStateKey);
    if (saved) {
        try {
            const state = JSON.parse(saved);
            const date = document.getElementById('match-date');
            const goalsA = enterMatch.querySelector('[name="goals_a"]');
            const goalsB = enterMatch.querySelector('[name="goals_b"]');
            const hasTeams = enterMatch.querySelectorAll('input[name="team_a"], input[name="team_b"]').length > 0;
            if (!hasTeams) {
                if (date && state.date) date.value = state.date;
                if (goalsA && state.goalsA !== '') goalsA.value = state.goalsA;
                if (goalsB && state.goalsB !== '') goalsB.value = state.goalsB;

                const restoreTeam = (key, team) => {
                    const names = String(state[key] || '').split('||').filter(Boolean);
                    names.forEach(rawName => {
                        const wanted = rawName.trim().toLowerCase();
                        const player = [...document.querySelectorAll('.player')].find(box =>
                            box.querySelector('span')?.textContent?.trim().toLowerCase() === wanted
                        );
                        const checkbox = player?.querySelector('input[type="checkbox"]');
                        if (checkbox && typeof window.addPlayer === 'function') {
                            window.addPlayer(team, checkbox.value, player.querySelector('span').textContent.trim());
                        }
                    });
                };
                restoreTeam('teamA', 'a');
                restoreTeam('teamB', 'b');
            }
            sessionStorage.removeItem(parserStateKey);
        } catch (_) {
            sessionStorage.removeItem(parserStateKey);
        }
    }

    // Possible conflicts are compact: clickable names in one row.
    const conflictList = document.querySelector('.conflict-list');
    if (conflictList) {
        conflictList.style.display = 'flex';
        conflictList.style.flexWrap = 'wrap';
        conflictList.style.gap = '8px 14px';
        conflictList.style.alignItems = 'center';
        const title = conflictList.querySelector(':scope > strong');
        if (title) {
            title.style.width = '100%';
            title.style.marginBottom = '2px';
        }
        conflictList.querySelectorAll('.conflict-row').forEach(row => {
            row.style.display = 'inline-flex';
            row.style.margin = '0';
        });
        conflictList.querySelectorAll('.conflict-row .muted').forEach(status => status.style.display = 'none');
    }

    // "Use these teams" changes the Enter a Match teams only on explicit action.
    const generated = document.getElementById('generated-teams');
    const useTeams = [...document.querySelectorAll('a.primary')].find(a =>
        a.textContent.trim() === 'Use these teams in Enter a Match'
    );
    if (generated && useTeams) {
        let teams;
        try { teams = JSON.parse(generated.textContent); } catch (_) { teams = null; }
        if (!teams) return;

        useTeams.addEventListener('click', event => {
            event.preventDefault();
            const currentTeams = document.querySelectorAll('#enter-match input[name="team_a"], #enter-match input[name="team_b"]');
            const currentGoalsA = enterMatch.querySelector('[name="goals_a"]')?.value || '0';
            const currentGoalsB = enterMatch.querySelector('[name="goals_b"]')?.value || '0';
            const hasCurrentConfiguration = currentTeams.length > 0 || currentGoalsA !== '0' || currentGoalsB !== '0';

            const apply = () => {
                ['a', 'b'].forEach(team => {
                    const list = document.getElementById(`list-${team}`);
                    if (!list) return;
                    list.querySelectorAll('.selected-player').forEach(row => row.remove());
                    (teams[team] || []).forEach(id => {
                        const player = document.querySelector(`.player input[value="${id}"]`)?.closest('.player');
                        const name = player?.querySelector('span')?.textContent?.trim() || `Player ${id}`;
                        if (typeof window.addPlayer === 'function') window.addPlayer(team, id, name);
                    });
                });
                enterMatch.scrollIntoView({ behavior: 'smooth' });
            };

            if (hasCurrentConfiguration) {
                if (confirm('Are you certain you want to overwrite the current configuration?')) apply();
            } else {
                apply();
            }
        });
    }
});
