(function () {

    const matchPlayers = window.matchCenterPlayers || {};


    // ------------------------------------------------------------
    // Player helpers
    // ------------------------------------------------------------

    function playerData(pid) {
        return matchPlayers[String(pid)] || matchPlayers[pid] || {};
    }


    function playerAlias(pid) {
        const player = playerData(pid);

        if (player.aliases && player.aliases.length) {
            return player.aliases[0];
        }

        return `Player ${pid}`;
    }


    function selectedIds(team) {
        return Array.from(
            document.querySelectorAll(
                `#list-${team} input[name="team_${team}"]`
            )
        ).map(input => String(input.value));
    }


    function updateCount(team) {
        const element = document.getElementById(`count-${team}`);

        if (element) {
            element.textContent = `(${selectedIds(team).length})`;
        }
    }


    // ------------------------------------------------------------
    // Add player to team
    // ------------------------------------------------------------

    function addTeamPlayer(team, pid) {

        pid = String(pid);

        if (selectedIds(team).includes(pid)) {
            return;
        }

        const list = document.getElementById(`list-${team}`);

        if (!list) {
            return;
        }

        const row = document.createElement('div');
        row.className = 'selected-player';


        const name = document.createElement('span');
        name.className = 'selected-player-name';
        name.textContent = playerAlias(pid);


        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'remove-player';
        remove.textContent = '×';

        remove.addEventListener('click', () => {
            row.remove();
            updateCount(team);
        });


        const hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.name = `team_${team}`;
        hidden.value = pid;


        row.append(name, remove, hidden);
        list.appendChild(row);

        updateCount(team);
    }


    // ------------------------------------------------------------
    // Player search
    // ------------------------------------------------------------

    function renderSearch(team) {

        const input = document.getElementById(`search-${team}`);
        const results = document.getElementById(`results-${team}`);

        if (!input || !results) {
            return;
        }


        const query = input.value.trim().toLowerCase();

        results.innerHTML = '';


        if (!query) {
            return;
        }


        const selected = new Set(selectedIds(team));


        Object.keys(matchPlayers)
            .filter(pid => !selected.has(String(pid)))
            .map(pid => ({
                pid,
                player: playerData(pid)
            }))
            .filter(({ player }) => {

                const aliases = (player.aliases || [])
                    .join(' ')
                    .toLowerCase();

                return aliases.includes(query);
            })
            .slice(0, 20)
            .forEach(({ pid }) => {

                const item = document.createElement('div');

                item.className = 'search-result';

                // Search suggestions show only the main alias.
                item.textContent = playerAlias(pid);


                item.addEventListener('click', () => {

                    addTeamPlayer(team, pid);

                    input.value = '';
                    results.innerHTML = '';

                });


                results.appendChild(item);
            });
    }


    function initTeamEditor() {
        ['a', 'b'].forEach(team => {

        const input = document.getElementById(`search-${team}`);

        input?.addEventListener(
            'input',
            () => renderSearch(team)
        );

        input?.addEventListener(
            'focus',
            () => {
                if (input.value.trim()) {
                    renderSearch(team);
                }
            }
        );

        });


    // ------------------------------------------------------------
    // Remove initially rendered players
    // ------------------------------------------------------------

        document.querySelectorAll('.remove-player').forEach(button => {

        button.addEventListener('click', () => {

            const row = button.closest('.selected-player');

            const teamBox = button.closest('.team-box');

            const team = teamBox
                ?.querySelector('.player-search')
                ?.id
                ?.replace('search-', '') || 'a';


            row?.remove();

            updateCount(team);
        });

        });
    }


    // ------------------------------------------------------------
    // Paste image into parser
    // ------------------------------------------------------------

    function initParserImagePaste() {
        const imageInput = document.getElementById('match-image');
        const pasteStatus = document.getElementById('paste-status');

        if (!imageInput) {
            return;
        }

        document.addEventListener('paste', event => {

            for (const item of event.clipboardData?.items || []) {

                if (!item.type.startsWith('image/')) {
                    continue;
                }


                const blob = item.getAsFile();

                if (!blob) {
                    continue;
                }


                const extension =
                    blob.type.split('/')[1] || 'png';

                const file = new File(
                    [blob],
                    `pasted-screenshot.${extension}`,
                    { type: blob.type }
                );


                const transfer = new DataTransfer();

                transfer.items.add(file);

                imageInput.files = transfer.files;


                if (pasteStatus) {
                    pasteStatus.textContent =
                        'Screenshot pasted and ready to parse.';
                }


                event.preventDefault();

                break;
            }

        });


        imageInput.addEventListener('change', () => {

            if (pasteStatus && imageInput.files.length) {

                pasteStatus.textContent =
                    `Selected: ${imageInput.files[0].name}`;
            }

        });

    }


    // ------------------------------------------------------------
    // Conflict modal
    // ------------------------------------------------------------

    function initConflictModal() {
        let conflictIndex = null;
        const conflictModal = document.getElementById('conflict-modal');

        if (!conflictModal) {
            return;
        }


    function openConflict(index, name) {

        conflictIndex = index;

        document.getElementById('conflict-name').textContent =
            name;

        document.getElementById('conflict-input').value =
            document.getElementById(`detail-${index}`).value || '';

        conflictModal.style.display = 'flex';

        document.getElementById('conflict-input').focus();
    }


    function closeConflict() {

        conflictModal.style.display = 'none';

        conflictIndex = null;
    }


    document
        .querySelectorAll('.conflict-btn')
        .forEach(button => {

            button.addEventListener(
                'click',
                () => openConflict(
                    button.dataset.index,
                    button.dataset.name
                )
            );

        });


    document
        .getElementById('conflict-save')
        ?.addEventListener('click', () => {

            if (conflictIndex === null) {
                return;
            }

            document.getElementById(
                `detail-${conflictIndex}`
            ).value =
                document.getElementById(
                    'conflict-input'
                ).value.trim();

            closeConflict();
        });


    document
        .getElementById('conflict-cancel')
        ?.addEventListener(
            'click',
            closeConflict
        );
    }


    // ------------------------------------------------------------
    // Add-player modal
    // ------------------------------------------------------------
    function initAddPlayerModal() {
        const form = document.getElementById('mc-form');
        const addModal = document.getElementById('add-modal');
        let addPlayerName = '';

        if (!form || !addModal) {
            return;
        }

        function openAdd(name) {
            addPlayerName = name;
            document.getElementById('add-name').textContent = name;
            document.getElementById('choice').style.display = 'block';
            document.getElementById('alias-form').style.display = 'none';
            document.getElementById('new-form').style.display = 'none';
            addModal.style.display = 'flex';
        }

        document.querySelectorAll('.add-btn').forEach(button => {
            button.addEventListener('click', () => openAdd(button.dataset.name));
        });

        document.getElementById('add-cancel')?.addEventListener('click', () => {
            addModal.style.display = 'none';
        });

        document.getElementById('alias-choice')?.addEventListener('click', () => {
            document.getElementById('choice').style.display = 'none';
            document.getElementById('alias-form').style.display = 'block';
        });

        document.getElementById('new-choice')?.addEventListener('click', () => {
            document.getElementById('choice').style.display = 'none';
            document.getElementById('new-form').style.display = 'block';
            document.getElementById('new-alias').value = addPlayerName;
        });

        // ------------------------------------------------------------
        // Form helpers
        // ------------------------------------------------------------

        function hidden(name, value) {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = name;
            input.value = value;
            return input;
        }

        document.getElementById('alias-submit')?.addEventListener('click', () => {
            form.append(
                hidden('action', 'add_parser_alias'),
                hidden('new_alias', addPlayerName),
                hidden('target_player_id', document.getElementById('alias-id').value)
            );
            form.submit();
        });

        document.getElementById('new-submit')?.addEventListener('click', () => {
            form.append(
                hidden('action', 'create_parser_player'),
                hidden('new_alias', document.getElementById('new-alias').value),
                hidden('calibration', document.querySelector('input[name="new_calibration"]:checked')?.value || 'average')
            );
            document.querySelectorAll('input[name="new_positions"]:checked').forEach(input => {
                form.append(hidden('new_positions', input.value));
            });
            form.submit();
        });
    }


    // ------------------------------------------------------------
    // Suggested Teams & Transfer into Enter a Match
    // ------------------------------------------------------------
    function initGeneratedTeamTransfer() {
        const suggested = document.getElementById('suggested-teams');
        const generated = document.getElementById('generated-teams');
        const transferBtn = document.getElementById('transfer-teams-btn');

        if (suggested) {
            suggested.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }

        if (!generated || !transferBtn) {
            return;
        }

        transferBtn.addEventListener('click', () => {
            try {
                const teams = JSON.parse(generated.textContent);

                document
                    .querySelectorAll('#match-form .team-box')
                    .forEach((box, index) => {
                        const teamKey = index === 0 ? 'a' : 'b';
                        const team = teams[teamKey];
                        const list = box.querySelector('.player-list');

                        if (!list || !team) {
                            return;
                        }

                        list.innerHTML = '';
                        team.forEach(pid => {
                            addTeamPlayer(teamKey, pid);
                        });
                    });

                document
                    .getElementById('enter-match')
                    ?.scrollIntoView({
                        behavior: 'smooth',
                        block: 'start'
                    });

            } catch (error) {
                console.error('Could not transfer generated teams:', error);
            }
        });
    }


    // ------------------------------------------------------------
    // "Add new player" button
    // ------------------------------------------------------------

    function initAddPlayerButton() {
        window.openPlayerModal = function (team) {

        const input =
            document.getElementById(`search-${team}`);

        input?.focus();

        input?.scrollIntoView({
            behavior: 'smooth',
            block: 'center'
        });

        };
    }


    // ------------------------------------------------------------
    // Future Date Easter Egg Modal
    // ------------------------------------------------------------

    function initFutureDateModal() {
        const dateInput = document.getElementById('match-date');
        const futureModal = document.getElementById('future-date-modal');
        const confirmBtn = document.getElementById('future-confirm');
        const resetBtn = document.getElementById('future-reset');

        if (!dateInput || !futureModal) {
            return;
        }

        function getTodayString() {
            const today = new Date();
            const year = today.getFullYear();
            const month = String(today.getMonth() + 1).padStart(2, '0');
            const day = String(today.getDate()).padStart(2, '0');
            return `${year}-${month}-${day}`;
        }

        dateInput.addEventListener('change', () => {
            const selected = dateInput.value;
            const todayStr = getTodayString();

            if (selected && selected > todayStr) {
                futureModal.style.display = 'flex';
            }
        });

        confirmBtn?.addEventListener('click', () => {
            futureModal.style.display = 'none';
        });

        resetBtn?.addEventListener('click', () => {
            dateInput.value = getTodayString();
            futureModal.style.display = 'none';
        });
    }

    initTeamEditor();
    initParserImagePaste();
    initConflictModal();
    initAddPlayerModal();
    initGeneratedTeamTransfer();
    initAddPlayerButton();
    initFutureDateModal();

})();
