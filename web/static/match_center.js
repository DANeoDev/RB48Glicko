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


    function getExternalCount(team) {
        const input = document.getElementById(`external-${team}`);
        return input ? (parseInt(input.value, 10) || 0) : 0;
    }


    function setExternalCount(team, count) {
        const input = document.getElementById(`external-${team}`);
        if (input) {
            input.value = Math.max(0, count);
        }
    }


    function updateCount(team) {
        const element = document.getElementById(`count-${team}`);

        if (element) {
            const total = selectedIds(team).length + getExternalCount(team);
            element.textContent = `(${total})`;
        }
    }


    function wireRemoveExternal(button) {
        button.addEventListener('click', () => {
            const row = button.closest('.selected-player');
            const teamBox = button.closest('.team-box');
            const team = row?.dataset.team || (teamBox?.querySelector('.player-search')?.id?.replace('search-', '') || 'a');
            row?.remove();
            setExternalCount(team, getExternalCount(team) - 1);
            updateCount(team);
        });
    }


    function addExternalPlayer(team) {
        const list = document.getElementById(`list-${team}`);
        if (!list) return;

        setExternalCount(team, getExternalCount(team) + 1);

        const row = document.createElement('div');
        row.className = 'selected-player external-player-item';
        row.dataset.team = team;

        const name = document.createElement('span');
        name.className = 'selected-player-name';
        name.style.fontStyle = 'italic';
        name.style.color = 'var(--text-muted)';
        name.textContent = `👤 ${window.matchCenterTranslations?.externalPlayer || 'Externer Spieler (+1)'}`;

        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'remove-player remove-external';
        remove.textContent = '×';

        wireRemoveExternal(remove);

        row.append(name, remove);
        list.appendChild(row);

        updateCount(team);
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

        document.querySelectorAll('.remove-player:not(.remove-external)').forEach(button => {
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

        document.querySelectorAll('.remove-external').forEach(button => {
            wireRemoveExternal(button);
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
        const mcForm = document.getElementById('mc-form');
        const addModal = document.getElementById('add-modal');
        const errorEl = document.getElementById('add-modal-error');
        const titleEl = document.getElementById('add-modal-title');
        const detectedRow = document.getElementById('add-detected-row');
        const choiceDiv = document.getElementById('choice');
        const teamChoiceDiv = document.getElementById('team-add-choice');
        const choiceCreateBtn = document.getElementById('choice-create-player-btn');
        const choiceExternalBtn = document.getElementById('choice-external-player-btn');
        const aliasForm = document.getElementById('alias-form');
        const newForm = document.getElementById('new-form');
        const newAliasInput = document.getElementById('new-alias');
        const newSubmitBtn = document.getElementById('new-submit');

        let addPlayerName = '';
        let addTargetTeam = null;

        if (!addModal) {
            return;
        }

        function clearErrors() {
            if (errorEl) {
                errorEl.style.display = 'none';
                errorEl.textContent = '';
            }
        }

        function showModalError(msg) {
            if (errorEl) {
                errorEl.textContent = msg;
                errorEl.style.display = 'block';
            } else {
                alert(msg);
            }
        }

        // Called from parser (unmatched player name)
        function openAdd(name) {
            addTargetTeam = null;
            addPlayerName = name;
            clearErrors();
            if (titleEl) titleEl.textContent = window.matchCenterTranslations?.addPlayer || 'Add player';
            if (detectedRow) {
                detectedRow.style.display = 'block';
                const nameEl = document.getElementById('add-name');
                if (nameEl) nameEl.textContent = name;
            }
            if (teamChoiceDiv) teamChoiceDiv.style.display = 'none';
            if (choiceDiv) choiceDiv.style.display = 'block';
            if (aliasForm) aliasForm.style.display = 'none';
            if (newForm) newForm.style.display = 'none';
            addModal.style.display = 'flex';
        }

        // Called from "+ Add new player" button on Team A / Team B
        window.openPlayerModal = function (team) {
            addTargetTeam = team;
            addPlayerName = '';
            clearErrors();

            const teamLabel = team === 'a' ? 'Team A' : team === 'b' ? 'Team B' : '';
            if (titleEl) {
                titleEl.textContent = teamLabel ? `${window.matchCenterTranslations?.addPlayer || 'Add player'} (${teamLabel})` : (window.matchCenterTranslations?.addPlayer || 'Add player');
            }
            if (detectedRow) {
                detectedRow.style.display = 'none';
            }
            if (choiceDiv) choiceDiv.style.display = 'none';
            if (aliasForm) aliasForm.style.display = 'none';
            if (newForm) newForm.style.display = 'none';
            if (teamChoiceDiv) teamChoiceDiv.style.display = 'block';

            addModal.style.display = 'flex';
        };

        choiceCreateBtn?.addEventListener('click', () => {
            if (teamChoiceDiv) teamChoiceDiv.style.display = 'none';
            if (newForm) newForm.style.display = 'block';

            const searchInput = document.getElementById(`search-${addTargetTeam}`);
            const query = searchInput ? searchInput.value.trim() : '';
            if (newAliasInput) {
                newAliasInput.value = query;
            }
            setTimeout(() => {
                newAliasInput?.focus();
            }, 50);
        });

        choiceExternalBtn?.addEventListener('click', () => {
            if (addTargetTeam) {
                addExternalPlayer(addTargetTeam);
            }
            addModal.style.display = 'none';
            clearErrors();
        });

        document.querySelectorAll('.add-btn').forEach(button => {
            button.addEventListener('click', () => openAdd(button.dataset.name));
        });

        document.querySelectorAll('.ignore-btn').forEach(button => {
            button.addEventListener('click', () => {
                if (!mcForm) return;
                mcForm.append(
                    hidden('action', 'ignore_parser_player'),
                    hidden('target_alias', button.dataset.name)
                );
                mcForm.submit();
            });
        });

        document.getElementById('add-cancel')?.addEventListener('click', () => {
            addModal.style.display = 'none';
            clearErrors();
        });

        addModal.addEventListener('click', (e) => {
            if (e.target === addModal) {
                addModal.style.display = 'none';
                clearErrors();
            }
        });

        document.getElementById('alias-choice')?.addEventListener('click', () => {
            if (choiceDiv) choiceDiv.style.display = 'none';
            if (aliasForm) aliasForm.style.display = 'block';
        });

        document.getElementById('new-choice')?.addEventListener('click', () => {
            if (choiceDiv) choiceDiv.style.display = 'none';
            if (newForm) newForm.style.display = 'block';
            if (newAliasInput) newAliasInput.value = addPlayerName;
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
            if (!mcForm) return;
            mcForm.append(
                hidden('action', 'add_parser_alias'),
                hidden('new_alias', addPlayerName),
                hidden('target_player_id', document.getElementById('alias-id').value)
            );
            mcForm.submit();
        });

        const mainPosSelect = document.getElementById('new-main-position');
        if (mainPosSelect) {
            mainPosSelect.addEventListener('change', () => {
                const val = mainPosSelect.value;
                if (val) {
                    const chk = document.querySelector(`input[name="new_positions"][value="${val}"]`);
                    if (chk) chk.checked = true;
                }
            });
        }

        newSubmitBtn?.addEventListener('click', async () => {
            const alias = newAliasInput ? newAliasInput.value.trim() : '';
            if (!alias) {
                showModalError('Please enter a player name / alias.');
                newAliasInput?.focus();
                return;
            }

            const mainPos = mainPosSelect ? mainPosSelect.value : '';
            const calibration = document.querySelector('input[name="new_calibration"]:checked')?.value || 'average';
            const certainty = document.querySelector('input[name="new_certainty"]:checked')?.value || 'uncertain';
            const positions = Array.from(document.querySelectorAll('input[name="new_positions"]:checked')).map(i => i.value);

            // If opened from "+ Add new player" under Team A / Team B, create and add dynamically!
            if (addTargetTeam) {
                newSubmitBtn.disabled = true;
                clearErrors();

                const formData = new FormData();
                formData.set('action', 'create_player');
                formData.set('new_alias', alias);
                formData.set('calibration', calibration);
                formData.set('certainty', certainty);
                formData.set('target_team', addTargetTeam);
                if (mainPos) formData.set('main_position', mainPos);
                positions.forEach(pos => formData.append('new_positions', pos));

                try {
                    const response = await fetch('/match-center', {
                        method: 'POST',
                        headers: {
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: formData
                    });

                    const data = await response.json();
                    if (response.ok && data.success) {
                        const pid = String(data.player_id);
                        matchPlayers[pid] = {
                            aliases: [data.alias],
                            main_position: data.main_position || mainPos || null
                        };

                        addTeamPlayer(addTargetTeam, pid);

                        // Clear search input if it had the alias
                        const searchInput = document.getElementById(`search-${addTargetTeam}`);
                        if (searchInput) searchInput.value = '';

                        addModal.style.display = 'none';
                        clearErrors();
                    } else {
                        showModalError(data.error || 'Failed to create player.');
                    }
                } catch (err) {
                    console.error('Error creating player:', err);
                    showModalError('Error connecting to server. Please try again.');
                } finally {
                    newSubmitBtn.disabled = false;
                }
            } else if (mcForm) {
                // Parser flow
                mcForm.append(
                    hidden('action', 'create_parser_player'),
                    hidden('new_alias', alias),
                    hidden('calibration', calibration),
                    hidden('certainty', certainty)
                );
                if (mainPos) {
                    mcForm.append(hidden('main_position', mainPos));
                }
                positions.forEach(pos => {
                    mcForm.append(hidden('new_positions', pos));
                });
                mcForm.submit();
            }
        });
    }


    // ------------------------------------------------------------
    // Suggested Teams & Transfer into Enter a Match
    // ------------------------------------------------------------
    function initGeneratedTeamTransfer() {
        const generated = document.getElementById('generated-teams');
        const transferBtn = document.getElementById('transfer-teams-btn');

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
                        setExternalCount(teamKey, 0);
                        team.forEach(pid => {
                            addTeamPlayer(teamKey, pid);
                        });
                        updateCount(teamKey);
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
    // Save Match & Update Glicko (Modal without page jumping)
    // ------------------------------------------------------------
    function initMatchSaveForm() {
        const matchForm = document.getElementById('match-form');
        const saveModal = document.getElementById('match-saved-modal');
        const saveMsg = document.getElementById('saved-modal-message');
        const saveDoneBtn = document.getElementById('saved-modal-done');

        if (!matchForm || !saveModal) {
            return;
        }

        saveDoneBtn?.addEventListener('click', () => {
            saveModal.style.display = 'none';
        });

        saveModal.addEventListener('click', (e) => {
            if (e.target === saveModal) {
                saveModal.style.display = 'none';
            }
        });

        matchForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const teamAInputs = document.querySelectorAll('#list-a input[name="team_a"]');
            const teamBInputs = document.querySelectorAll('#list-b input[name="team_b"]');
            const extA = getExternalCount('a');
            const extB = getExternalCount('b');

            if ((teamAInputs.length + extA === 0) || (teamBInputs.length + extB === 0)) {
                alert('Both teams need at least one player.');
                return;
            }

            const formData = new FormData(matchForm);
            formData.set('action', 'save');

            const submitBtn = matchForm.querySelector('button[type="submit"]');
            if (submitBtn) {
                submitBtn.disabled = true;
            }

            try {
                const response = await fetch('/match-center', {
                    method: 'POST',
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: formData
                });

                const data = await response.json();
                if (response.ok && data.success) {
                    if (saveMsg) {
                        saveMsg.textContent = data.message || `Match ${data.match_id} saved successfully and Glicko ratings updated!`;
                    }
                    saveModal.style.display = 'flex';

                    // Update next match ID badge if present
                    const nextBadge = document.querySelector('#enter-match strong');
                    if (nextBadge && data.next_match_id) {
                        nextBadge.textContent = data.next_match_id;
                    }
                } else {
                    alert(data.error || 'Failed to save match.');
                }
            } catch (err) {
                console.error('Error saving match:', err);
                matchForm.submit();
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                }
            }
        });
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
    initMatchSaveForm();
    initFutureDateModal();

})();
