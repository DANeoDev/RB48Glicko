// Player Filter Drawer & URL Synchronization Module
(function() {
    let activeTeammates = [];
    let activeOpponents = [];

    function getEls() {
        return {
            drawerEl: document.getElementById("filter-drawer"),
            backdropEl: document.getElementById("filter-drawer-backdrop"),
            toggleBtn: document.getElementById("filter-drawer-toggle"),
            countBadge: document.getElementById("filter-active-count"),
            bannerEl: document.getElementById("active-filters-banner"),
            chipsContainer: document.getElementById("active-filter-chips"),
            noMatchesEl: document.getElementById("no-filtered-matches"),
            drawerTmTags: document.getElementById("drawer-teammate-tags") || document.getElementById("teammate-tags"),
            drawerOppTags: document.getElementById("drawer-opponent-tags") || document.getElementById("opponent-tags"),
            popoverTm: document.getElementById("popover-teammate") || document.getElementById("teammate-search-popover"),
            popoverOpp: document.getElementById("popover-opponent") || document.getElementById("opponent-search-popover"),
            searchInputTm: document.getElementById("search-input-teammate") || document.getElementById("teammate-search-input"),
            searchInputOpp: document.getElementById("search-input-opponent") || document.getElementById("opponent-search-input"),
            playerListTm: document.getElementById("player-list-teammate") || document.getElementById("teammate-dropdown-list"),
            playerListOpp: document.getElementById("player-list-opponent") || document.getElementById("opponent-dropdown-list")
        };
    }

    function openDrawer() {
        const { drawerEl, backdropEl } = getEls();
        if (!drawerEl) return;
        closePopovers();
        drawerEl.classList.add("open");
        if (backdropEl) backdropEl.classList.add("open");
        document.body.style.overflow = "hidden";
    }

    function closeDrawer() {
        const { drawerEl, backdropEl } = getEls();
        if (!drawerEl) return;
        closePopovers();
        drawerEl.classList.remove("open");
        if (backdropEl) backdropEl.classList.remove("open");
        document.body.style.overflow = "";
    }

    function toggleDrawer() {
        const { drawerEl } = getEls();
        if (drawerEl && drawerEl.classList.contains("open")) {
            closeDrawer();
        } else {
            openDrawer();
        }
    }

    function closePopovers() {
        const { popoverTm, popoverOpp } = getEls();
        if (popoverTm) popoverTm.style.display = "none";
        if (popoverOpp) popoverOpp.style.display = "none";
    }

    function toggleSearch(type) {
        const { popoverTm, popoverOpp } = getEls();
        const popover = (type === "teammate" || type === "teammates") ? popoverTm : popoverOpp;
        if (popover && popover.style.display === "block") {
            closePopovers();
        } else {
            openSearch(type);
        }
    }

    function openSearch(type) {
        closePopovers();
        const { popoverTm, popoverOpp, searchInputTm, searchInputOpp } = getEls();
        const isTm = (type === "teammate" || type === "teammates");
        const popover = isTm ? popoverTm : popoverOpp;
        const input = isTm ? searchInputTm : searchInputOpp;

        if (popover) {
            popover.style.display = "block";
            renderCandidates(isTm ? "teammate" : "opponent", "");
            if (input) {
                input.value = "";
                setTimeout(() => input.focus(), 50);
            }
        }
    }

    function getPossibleCandidates(type) {
        let matchingMatches = window.allMatchesData || [];
        const isTm = (type === "teammate" || type === "teammates");

        if (isTm) {
            for (const oppId of activeOpponents) {
                matchingMatches = matchingMatches.filter(m => (m.opp_team_ids || []).includes(oppId));
            }
            for (const tmId of activeTeammates) {
                matchingMatches = matchingMatches.filter(m => (m.own_team_ids || []).includes(tmId));
            }

            const candidateIds = new Set();
            for (const m of matchingMatches) {
                for (const pid of (m.own_team_ids || [])) {
                    if (pid !== window.currentPlayerId && !activeTeammates.includes(pid) && !activeOpponents.includes(pid)) {
                        candidateIds.add(pid);
                    }
                }
            }
            return Array.from(candidateIds);
        } else {
            for (const tmId of activeTeammates) {
                matchingMatches = matchingMatches.filter(m => (m.own_team_ids || []).includes(tmId));
            }
            for (const oppId of activeOpponents) {
                matchingMatches = matchingMatches.filter(m => (m.opp_team_ids || []).includes(oppId));
            }

            const candidateIds = new Set();
            for (const m of matchingMatches) {
                for (const pid of (m.opp_team_ids || [])) {
                    if (pid !== window.currentPlayerId && !activeOpponents.includes(pid) && !activeTeammates.includes(pid)) {
                        candidateIds.add(pid);
                    }
                }
            }
            return Array.from(candidateIds);
        }
    }

    function renderCandidates(type, query = "") {
        const candidateIds = getPossibleCandidates(type);
        const { playerListTm, playerListOpp } = getEls();
        const isTm = (type === "teammate" || type === "teammates");
        const listEl = isTm ? playerListTm : playerListOpp;
        if (!listEl) return;

        listEl.innerHTML = "";
        const lowerQ = query.toLowerCase().trim();

        const filtered = candidateIds
            .map(id => ({ id, name: (window.playersMap && window.playersMap[id]) || ("Player #" + id) }))
            .filter(p => !lowerQ || p.name.toLowerCase().includes(lowerQ))
            .sort((a, b) => a.name.localeCompare(b.name, "de", { sensitivity: "base" }));

        const isUl = listEl.tagName.toLowerCase() === "ul";

        if (filtered.length === 0) {
            const emptyEl = document.createElement(isUl ? "li" : "div");
            emptyEl.className = "filter-player-empty";
            emptyEl.textContent = "Keine weiteren Spieler möglich";
            listEl.appendChild(emptyEl);
            return;
        }

        filtered.forEach(p => {
            const itemEl = document.createElement(isUl ? "li" : "div");
            itemEl.className = "filter-player-item";
            itemEl.textContent = p.name;
            itemEl.onclick = (e) => {
                e.stopPropagation();
                addFilter(isTm ? "teammate" : "opponent", p.id);
                closePopovers();
            };
            listEl.appendChild(itemEl);
        });
    }

    function addFilter(type, playerId) {
        playerId = Number(playerId);
        if (isNaN(playerId)) return;

        if (type === "teammate" || type === "teammates") {
            if (!activeTeammates.includes(playerId)) {
                activeTeammates.push(playerId);
                updateUI();
            }
        } else if (type === "opponent" || type === "opponents") {
            if (!activeOpponents.includes(playerId)) {
                activeOpponents.push(playerId);
                updateUI();
            }
        }
    }

    function removeFilter(type, playerId) {
        playerId = Number(playerId);
        if (type === "teammate" || type === "teammates") {
            activeTeammates = activeTeammates.filter(id => id !== playerId);
        } else {
            activeOpponents = activeOpponents.filter(id => id !== playerId);
        }
        updateUI();
    }

    function resetFilters() {
        activeTeammates = [];
        activeOpponents = [];
        closePopovers();
        updateUI();
    }

    function copyFilterLink() {
        const url = window.location.href;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(url).then(() => {
                if (window.showToast) window.showToast("Filter-Link kopiert!");
                else alert("Filter-Link in die Zwischenablage kopiert!");
            }).catch(() => {
                prompt("Link kopieren:", url);
            });
        } else {
            prompt("Link kopieren:", url);
        }
    }

    function updateTags() {
        const { drawerTmTags, drawerOppTags, countBadge, toggleBtn, bannerEl, chipsContainer } = getEls();
        const pMap = window.playersMap || {};

        if (drawerTmTags) {
            drawerTmTags.innerHTML = activeTeammates.map(id => `
                <span class="filter-tag filter-tag-tm">
                    🤝 ${pMap[id] || 'Spieler #' + id}
                    <button type="button" class="filter-tag-remove" onclick="window.PlayerFilter.remove('teammate', ${id})" title="Entfernen">✕</button>
                </span>
            `).join("");
        }

        if (drawerOppTags) {
            drawerOppTags.innerHTML = activeOpponents.map(id => `
                <span class="filter-tag filter-tag-opp">
                    ⚔️ ${pMap[id] || 'Spieler #' + id}
                    <button type="button" class="filter-tag-remove" onclick="window.PlayerFilter.remove('opponent', ${id})" title="Entfernen">✕</button>
                </span>
            `).join("");
        }

        const totalActive = activeTeammates.length + activeOpponents.length;
        if (countBadge) {
            if (totalActive > 0) {
                countBadge.textContent = totalActive;
                countBadge.style.display = "inline-block";
                if (toggleBtn) toggleBtn.classList.add("has-active-filters");
            } else {
                countBadge.style.display = "none";
                if (toggleBtn) toggleBtn.classList.remove("has-active-filters");
            }
        }

        if (bannerEl && chipsContainer) {
            if (totalActive > 0) {
                bannerEl.style.display = "block";
                const tmChips = activeTeammates.map(id => `
                    <span class="filter-tag filter-tag-tm">
                        🤝 ${pMap[id] || 'Spieler #' + id}
                        <button type="button" class="filter-tag-remove" onclick="window.PlayerFilter.remove('teammate', ${id})" title="Entfernen">✕</button>
                    </span>
                `).join("");
                const oppChips = activeOpponents.map(id => `
                    <span class="filter-tag filter-tag-opp">
                        ⚔️ ${pMap[id] || 'Spieler #' + id}
                        <button type="button" class="filter-tag-remove" onclick="window.PlayerFilter.remove('opponent', ${id})" title="Entfernen">✕</button>
                    </span>
                `).join("");
                chipsContainer.innerHTML = tmChips + oppChips;
            } else {
                bannerEl.style.display = "none";
                chipsContainer.innerHTML = "";
            }
        }
    }

    function updateStatsAndMatches() {
        const matchesData = window.allMatchesData || [];
        const hasFilters = activeTeammates.length > 0 || activeOpponents.length > 0;
        let visibleCount = 0;
        let matchingMatches = [];

        matchesData.forEach(m => {
            const ownIds = m.own_team_ids || [];
            const oppIds = m.opp_team_ids || [];
            const hasAllTm = activeTeammates.every(tmId => ownIds.includes(tmId));
            const hasAllOpp = activeOpponents.every(oppId => oppIds.includes(oppId));
            const isMatchVisible = (!hasFilters) || (hasAllTm && hasAllOpp);

            const mid = (m.id !== undefined) ? m.id : m.match_id;
            const matchCard = document.getElementById("match-card-" + mid);

            if (matchCard) {
                if (isMatchVisible) {
                    visibleCount++;
                    matchingMatches.push(m);
                    matchCard.style.display = "";

                    matchCard.querySelectorAll(".match-player").forEach(playerSpan => {
                        const pid = Number(playerSpan.dataset.playerId);
                        const nameSpan = playerSpan.querySelector(".player-name-text") || playerSpan.querySelector(".highlight-player") || playerSpan;
                        if (!nameSpan) return;

                        nameSpan.classList.remove("highlight-filter-tm", "highlight-filter-opp");

                        if (activeTeammates.includes(pid)) {
                            nameSpan.classList.add("highlight-filter-tm");
                            nameSpan.title = "Ausgewählter Mitspieler";
                        } else if (activeOpponents.includes(pid)) {
                            nameSpan.classList.add("highlight-filter-opp");
                            nameSpan.title = "Ausgewählter Gegner";
                        }
                    });
                } else {
                    matchCard.style.display = "none";
                }
            } else if (isMatchVisible) {
                visibleCount++;
                matchingMatches.push(m);
            }
        });

        const { noMatchesEl } = getEls();
        if (noMatchesEl) {
            noMatchesEl.style.display = (hasFilters && visibleCount === 0) ? "block" : "none";
        }

        if (hasFilters && matchingMatches.length > 0) {
            const totalCount = matchesData.length;
            const count = matchingMatches.length;
            const wins = matchingMatches.filter(m => m.is_win).length;
            const losses = matchingMatches.filter(m => m.is_loss).length;
            const draws = matchingMatches.filter(m => m.is_draw).length;
            const winRate = (wins / count) * 100;
            const totalDelta = matchingMatches.reduce((acc, m) => {
                const d = (m.delta !== null && m.delta !== undefined) ? Number(m.delta) : (Number(m.player_delta) || 0);
                return acc + d;
            }, 0);
            const goalsFor = matchingMatches.reduce((acc, m) => acc + (Number(m.goals_for) || 0), 0);
            const goalsAgainst = matchingMatches.reduce((acc, m) => acc + (Number(m.goals_against) || 0), 0);
            const goalDiff = goalsFor - goalsAgainst;
            const avgDiff = (goalDiff / count);

            const statGames = document.getElementById("stat-filtered-games");
            if (statGames) statGames.textContent = count;
            const statSub = document.getElementById("stat-total-games-sub");
            if (statSub) statSub.textContent = `von ${totalCount} Spielen`;
            const statRec = document.getElementById("stat-filtered-record");
            if (statRec) statRec.textContent = `${wins}S - ${draws}U - ${losses}N`;
            const statWin = document.getElementById("stat-filtered-winrate");
            if (statWin) statWin.textContent = `${winRate.toFixed(1)}%`;

            const deltaEl = document.getElementById("stat-filtered-delta");
            if (deltaEl) {
                const sign = totalDelta > 0 ? "+" : "";
                deltaEl.textContent = `${sign}${totalDelta.toFixed(1)}`;
                deltaEl.className = "stat-num " + (totalDelta > 0 ? "delta-pos" : (totalDelta < 0 ? "delta-neg" : ""));
            }

            const goalsEl = document.getElementById("stat-filtered-goals");
            if (goalsEl) {
                const diffSign = goalDiff > 0 ? "+" : "";
                goalsEl.textContent = `${diffSign}${goalDiff}`;
                goalsEl.className = "stat-num " + (goalDiff > 0 ? "delta-pos" : (goalDiff < 0 ? "delta-neg" : ""));
                const avgSign = avgDiff > 0 ? "+" : "";
                const goalsSub = document.getElementById("stat-filtered-goals-sub");
                if (goalsSub) goalsSub.textContent = `(${goalsFor}:${goalsAgainst} · Ø ${avgSign}${avgDiff.toFixed(1)})`;
            }
        }

        // Sync URL query parameters
        try {
            const url = new URL(window.location.href);
            if (activeTeammates.length > 0) {
                url.searchParams.set("teammates", activeTeammates.join(","));
            } else {
                url.searchParams.delete("teammates");
            }
            if (activeOpponents.length > 0) {
                url.searchParams.set("opponents", activeOpponents.join(","));
            } else {
                url.searchParams.delete("opponents");
            }
            window.history.replaceState({}, "", url.toString());

            // Update selector tab links to preserve active filters
            ["total", "box", "hf"].forEach(mode => {
                const link = document.getElementById("btn-tab-" + mode);
                if (link) {
                    const linkUrl = new URL(link.href, window.location.origin);
                    if (activeTeammates.length > 0) linkUrl.searchParams.set("teammates", activeTeammates.join(","));
                    else linkUrl.searchParams.delete("teammates");
                    if (activeOpponents.length > 0) linkUrl.searchParams.set("opponents", activeOpponents.join(","));
                    else linkUrl.searchParams.delete("opponents");
                    link.href = linkUrl.pathname + linkUrl.search;
                }
            });
        } catch (e) {}
    }

    function updateUI() {
        updateTags();
        updateStatsAndMatches();
    }

    function initMatchExpand() {
        document.querySelectorAll(".match").forEach(match => {
            if (match.dataset.expandBound) return;
            match.dataset.expandBound = "true";
            match.addEventListener("click", (e) => {
                if (e.target.closest("a") || e.target.closest("button") || e.target.closest("input")) return;
                match.classList.toggle("expanded");
            });
        });
    }

    function bindEvents() {
        const { searchInputTm, searchInputOpp } = getEls();
        if (searchInputTm && !searchInputTm.dataset.bound) {
            searchInputTm.dataset.bound = "true";
            searchInputTm.addEventListener("input", (e) => renderCandidates("teammate", e.target.value));
            searchInputTm.addEventListener("keydown", (e) => {
                if (e.key === "Escape") closePopovers();
            });
        }
        if (searchInputOpp && !searchInputOpp.dataset.bound) {
            searchInputOpp.dataset.bound = "true";
            searchInputOpp.addEventListener("input", (e) => renderCandidates("opponent", e.target.value));
            searchInputOpp.addEventListener("keydown", (e) => {
                if (e.key === "Escape") closePopovers();
            });
        }
    }

    // Click outside to close popovers
    document.addEventListener("click", (e) => {
        if (!e.target.closest(".filter-add-wrapper")) {
            closePopovers();
        }
    });

    // Close drawer / popovers on Escape
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            closePopovers();
            closeDrawer();
        }
    });

    // Parse URL on load
    try {
        const params = new URLSearchParams(window.location.search);
        const tmParam = params.get("teammates");
        const oppParam = params.get("opponents");

        if (tmParam) {
            activeTeammates = tmParam.split(",").map(Number).filter(n => !isNaN(n) && window.playersMap && window.playersMap[n]);
        }
        if (oppParam) {
            activeOpponents = oppParam.split(",").map(Number).filter(n => !isNaN(n) && window.playersMap && window.playersMap[n]);
        }
    } catch (e) {}

    // Public API
    window.PlayerFilter = {
        openDrawer: openDrawer,
        closeDrawer: closeDrawer,
        toggleDrawer: toggleDrawer,
        openSearch: openSearch,
        toggleSearch: toggleSearch,
        add: addFilter,
        remove: removeFilter,
        reset: resetFilters,
        copyLink: copyFilterLink
    };

    function init() {
        bindEvents();
        initMatchExpand();
        updateUI();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
