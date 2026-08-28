document.addEventListener('DOMContentLoaded', () => {
    const matchForm = document.getElementById('match-form');
    if (!matchForm) return;

    const players = window.matchCenterPlayers || {};
    const temporaryAssignments = new Map();
    const externalCounts = { a: 0, b: 0 };

    function escapeHtml(value) {
        return String(value).replace(/[&<>'"]/g, char => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
        }[char]));
    }

    function selectedIds(team) {
        return [...document.querySelectorAll(`#list-${team} input[name="team_${team}"]`)]
            .map(input => String(input.value));
    }

    function addDatabasePlayerToTeam(team, playerId, alias) {
        const id = String(playerId);
        if (selectedIds(team).includes(id)) return;
        const list = document.getElementById(`list-${team}`);
        if (!list) return;

        const row = document.createElement('div');
        row.className = 'selected-player';
        const name = document.createElement('span');
        name.className = 'selected-player-name';
        name.textContent = alias || `Player ${id}`;
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'remove-player';
        remove.textContent = '×';
        remove.addEventListener('click', () => row.remove());
        const hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.name = `team_${team}`;
        hidden.value = id;
        row.append(name, remove, hidden);
        list.appendChild(row);
    }

    function ensureExternalInput(team) {
        let input = matchForm.querySelector(`input[name="external_${team}"]`);
        if (!input) {
            input = document.createElement('input');
            input.type = 'hidden';
            input.name = `external_${team}`;
            input.value = '0';
            matchForm.appendChild(input);
        }
        return input;
    }

    function addExternalPlayer(team, alias) {
        const key = alias.trim().toLowerCase();
        if (!key) return;
        if (temporaryAssignments.has(key)) {
            const existingTeam = temporaryAssignments.get(key);
            alert(existingTeam === team ? 'This temporary player is already on this team.' : 'A player cannot be on both teams.');
            return;
        }

        temporaryAssignments.set(key, team);
        externalCounts[team] += 1;
        ensureExternalInput(team).value = String(externalCounts[team]);

        const list = document.getElementById(`list-${team}`);
        if (!list) return;
        list.querySelectorAll('.external-player').forEach(oldRow => oldRow.remove());

        const row = document.createElement('div');
        row.className = 'selected-player external-player';
        const name = document.createElement('span');
        name.className = 'selected-player-name';
        name.textContent = `+${externalCounts[team]} external player${externalCounts[team] === 1 ? '' : 's'}`;
        name.title = 'Temporary players are not stored as registered players; only the participant count is recorded for this match.';
        row.appendChild(name);
        list.appendChild(row);
    }

    function modalShell(id, html) {
        let modal = document.getElementById(id);
        if (modal) return modal;
        modal = document.createElement('div');
        modal.className = 'modal-bg';
        modal.id = id;
        modal.innerHTML = `<div class="modal">${html}</div>`;
        document.body.appendChild(modal);
        return modal;
    }

    function closeModal(modal) {
        modal.style.display = 'none';
    }

    function openDatabaseModal(team, initialName) {
        const modal = modalShell('manual-database-modal', `
            <h3>Add player to database</h3>
            <p class="muted">Add this name as an alias for an existing player, or create a new player.</p>
            <input id="manual-db-name" type="text" placeholder="Alias / name" value="${escapeHtml(initialName)}">
            <div class="modal-actions">
                <button type="button" class="primary" id="manual-db-alias-choice">Add alias to existing player</button>
                <button type="button" class="secondary" id="manual-db-new-choice">Create new player</button>
                <button type="button" class="secondary" id="manual-db-cancel">Cancel</button>
            </div>
            <div id="manual-db-alias-form" style="display:none;">
                <select id="manual-db-player-id"></select>
                <div class="modal-actions">
                    <button type="button" class="primary" id="manual-db-alias-submit">Add alias &amp; select</button>
                    <button type="button" class="secondary" id="manual-db-alias-back">Back</button>
                </div>
            </div>
            <div id="manual-db-new-form" style="display:none;">
                <div class="positions">
                    ${['GK', 'DEF', 'MID', 'ATT'].map(pos => `<label><input type="checkbox" name="manual-db-position" value="${pos}"> ${pos}</label>`).join('')}
                </div>
                <div class="calibration">
                    ${Object.entries({
                        extremely_weak: ['Extremely weak', '15th percentile'],
                        weak: ['Weak', '35th percentile'],
                        average: ['Average (standard)', ''],
                        strong: ['Strong', '65th percentile'],
                        extremely_strong: ['Extremely strong', '85th percentile']
                    }).map(([key, item]) => `<label><input type="radio" name="manual-db-calibration" value="${key}" ${key === 'average' ? 'checked' : ''}> ${item[0]}${item[1] ? ` (${item[1]})` : ''}</label>`).join('')}
                </div>
                <div class="modal-actions">
                    <button type="button" class="primary" id="manual-db-new-submit">Create &amp; select</button>
                    <button type="button" class="secondary" id="manual-db-new-back">Back</button>
                </div>
            </div>
        `);

        const nameInput = modal.querySelector('#manual-db-name');
        const aliasChoice = modal.querySelector('#manual-db-alias-choice');
        const newChoice = modal.querySelector('#manual-db-new-choice');
        const aliasForm = modal.querySelector('#manual-db-alias-form');
        const newForm = modal.querySelector('#manual-db-new-form');
        const aliasSelect = modal.querySelector('#manual-db-player-id');

        aliasSelect.innerHTML = Object.entries(players).map(([id, player]) => {
            const label = player.aliases?.[0] || `Player ${id}`;
            return `<option value="${escapeHtml(id)}">#${escapeHtml(id)} — ${escapeHtml(label)}</option>`;
        }).join('');

        const showChoices = () => {
            aliasForm.style.display = 'none';
            newForm.style.display = 'none';
            aliasChoice.style.display = '';
            newChoice.style.display = '';
        };
        aliasChoice.onclick = () => {
            aliasForm.style.display = 'block'; newForm.style.display = 'none';
            aliasChoice.style.display = 'none'; newChoice.style.display = 'none';
        };
        newChoice.onclick = () => {
            aliasForm.style.display = 'none'; newForm.style.display = 'block';
            aliasChoice.style.display = 'none'; newChoice.style.display = 'none';
        };
        modal.querySelector('#manual-db-alias-back').onclick = showChoices;
        modal.querySelector('#manual-db-new-back').onclick = showChoices;
        modal.querySelector('#manual-db-cancel').onclick = () => closeModal(modal);
        modal.querySelector('#manual-db-alias-submit').onclick = async () => {
            await submitDatabasePlayer(modal, team, 'alias', nameInput.value.trim(), aliasSelect.value);
        };
        modal.querySelector('#manual-db-new-submit').onclick = async () => {
            const positions = [...modal.querySelectorAll('input[name="manual-db-position"]:checked')].map(input => input.value);
            const calibration = modal.querySelector('input[name="manual-db-calibration"]:checked')?.value || 'average';
            await submitDatabasePlayer(modal, team, 'new', nameInput.value.trim(), null, positions, calibration);
        };

        modal.style.display = 'flex';
        nameInput.focus();
        nameInput.select();
    }

    async function submitDatabasePlayer(modal, team, mode, alias, targetPlayerId, positions = [], calibration = 'average') {
        if (!alias) { alert('Player name cannot be empty.'); return; }
        const body = new URLSearchParams({ alias, mode });
        if (targetPlayerId) body.set('target_player_id', targetPlayerId);
        positions.forEach(position => body.append('positions', position));
        body.set('calibration', calibration);
        try {
            const response = await fetch('/match-center/add-database-player', {
                method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Could not add player.');
            const id = String(data.player_id);
            if (!players[id]) players[id] = { aliases: [], positions: [] };
            if (!players[id].aliases.includes(data.alias)) players[id].aliases.unshift(data.alias);
            if (mode === 'new') players[id].positions = positions;
            addDatabasePlayerToTeam(team, id, players[id].aliases[0] || data.alias);
            closeModal(modal);
        } catch (error) { alert(error.message); }
    }

    function openTemporaryModal(team, initialName) {
        const modal = modalShell('manual-temporary-modal', `
            <h3>Add temporary player</h3>
            <p class="muted">This name will be added to the ignored alias list. It will not become a registered player.</p>
            <input id="manual-temp-name" type="text" placeholder="Player name" value="${escapeHtml(initialName)}">
            <div class="modal-actions">
                <button type="button" class="primary" id="manual-temp-submit">Add temporary player</button>
                <button type="button" class="secondary" id="manual-temp-cancel">Cancel</button>
            </div>
        `);
        const input = modal.querySelector('#manual-temp-name');
        modal.querySelector('#manual-temp-cancel').onclick = () => closeModal(modal);
        modal.querySelector('#manual-temp-submit').onclick = async () => {
            const alias = input.value.trim();
            if (!alias) { alert('Player name cannot be empty.'); return; }
            try {
                const response = await fetch('/match-center/add-temporary-player', {
                    method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: new URLSearchParams({ alias })
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || 'Could not add temporary player.');
                addExternalPlayer(team, data.alias);
                closeModal(modal);
            } catch (error) { alert(error.message); }
        };
        modal.style.display = 'flex';
        input.focus();
        input.select();
    }

    window.openPlayerModal = function (team) {
        const input = document.getElementById(`search-${team}`);
        const initialName = input?.value.trim() || '';
        const modal = modalShell('manual-add-choice-modal', `
            <h3>Add player</h3>
            <p>How should this player be added?</p>
            <div class="modal-actions">
                <button type="button" class="primary" id="manual-add-database">Add player to the database</button>
                <button type="button" class="secondary" id="manual-add-temporary">Add temporary player</button>
                <button type="button" class="secondary" id="manual-add-cancel">Cancel</button>
            </div>
        `);
        modal.querySelector('#manual-add-database').onclick = () => {
            closeModal(modal); openDatabaseModal(team, initialName);
        };
        modal.querySelector('#manual-add-temporary').onclick = () => {
            closeModal(modal); openTemporaryModal(team, initialName);
        };
        modal.querySelector('#manual-add-cancel').onclick = () => closeModal(modal);
        modal.style.display = 'flex';
    };
});
