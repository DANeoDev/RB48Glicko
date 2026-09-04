// Player Correlation Map Module (Interactive SVG Scatter + Breakdown Table)
(function() {
    let currentTab = "teammates"; // 'teammates' | 'opponents'
    const modalEl = document.getElementById("corr-modal");
    const backdropEl = document.getElementById("corr-modal-backdrop");
    const svgEl = document.getElementById("corr-scatter-svg");
    const tooltipEl = document.getElementById("corr-tooltip");
    const tableBodyEl = document.getElementById("corr-table-body");
    const noDataEl = document.getElementById("corr-no-data");
    const tabTmBtn = document.getElementById("corr-tab-teammates");
    const tabOppBtn = document.getElementById("corr-tab-opponents");

    let hideTimeout = null;

    function openModal() {
        if (!modalEl) return;
        modalEl.classList.add("open");
        backdropEl.classList.add("open");
        document.body.style.overflow = "hidden";
        renderMap();
    }

    function closeModal() {
        if (!modalEl) return;
        modalEl.classList.remove("open");
        backdropEl.classList.remove("open");
        document.body.style.overflow = "";
        hideTooltip();
    }

    function switchTab(tab) {
        currentTab = tab;
        if (tabTmBtn && tabOppBtn) {
            if (tab === "teammates") {
                tabTmBtn.classList.add("active");
                tabOppBtn.classList.remove("active");
            } else {
                tabOppBtn.classList.add("active");
                tabTmBtn.classList.remove("active");
            }
        }
        renderMap();
    }

    function calculateStats(mode) {
        const statsMap = {};
        const matchesData = window.allMatchesData || [];
        const pMap = window.playersMap || {};
        const cPlayerId = window.currentPlayerId;

        matchesData.forEach(m => {
            const playerIds = (mode === "teammates") ? m.own_team_ids : m.opp_team_ids;
            playerIds.forEach(pid => {
                if (pid === cPlayerId) return;
                if (!statsMap[pid]) {
                    statsMap[pid] = {
                        playerId: pid,
                        name: pMap[pid] || ("Player #" + pid),
                        games: 0,
                        wins: 0,
                        draws: 0,
                        losses: 0,
                        delta: 0.0,
                        goalsFor: 0,
                        goalsAgainst: 0
                    };
                }
                const st = statsMap[pid];
                st.games++;
                if (m.is_win) st.wins++;
                else if (m.is_loss) st.losses++;
                else if (m.is_draw) st.draws++;
                st.delta += (m.player_delta || 0.0);
                st.goalsFor += (m.goals_for || 0);
                st.goalsAgainst += (m.goals_against || 0);
            });
        });

        const list = Object.values(statsMap).map(st => {
            st.winRate = (st.wins / st.games) * 100;
            st.goalDiff = st.goalsFor - st.goalsAgainst;
            return st;
        });

        // Sort by games descending, then winRate descending
        list.sort((a, b) => b.games - a.games || b.winRate - a.winRate);
        return list;
    }

    function selectPlayerAndFilter(playerId) {
        closeModal();
        if (window.PlayerFilter && window.PlayerFilter.add) {
            const filterType = currentTab === "teammates" ? "teammate" : "opponent";
            window.PlayerFilter.add(filterType, playerId);
        }
    }

    function cancelHideTooltip() {
        if (hideTimeout) {
            clearTimeout(hideTimeout);
            hideTimeout = null;
        }
    }

    function scheduleHideTooltip() {
        cancelHideTooltip();
        hideTimeout = setTimeout(hideTooltip, 120);
    }

    function hideTooltip() {
        cancelHideTooltip();
        if (tooltipEl) tooltipEl.style.display = "none";
    }

    function showTooltip(e, playerList, activePid) {
        cancelHideTooltip();
        if (!tooltipEl || !playerList || playerList.length === 0) return;
        const roleLabel = currentTab === "teammates" ? "🤝 Als Mitspieler" : "⚔️ Als Gegner";
        const hasGlicko = window.userHasGlickoTier;

        if (playerList.length === 1) {
            const st = playerList[0];
            const sign = st.delta > 0 ? "+" : "";
            let colorBadge = "#ff5252";
            if (st.winRate >= 60) colorBadge = "#00e676";
            else if (st.winRate >= 45) colorBadge = "#ffc107";

            tooltipEl.innerHTML = `
                <div style="font-weight: 700; font-size: 13px; color: #80deea; margin-bottom: 2px;">${st.name}</div>
                <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 6px;">${roleLabel}</div>
                <div style="display: flex; gap: 14px; font-size: 11.5px; line-height: 1.4;">
                    <div>
                        <div><strong>${st.games}</strong> ${st.games === 1 ? 'Spiel' : 'Spiele'}</div>
                        <div><span style="color: ${colorBadge}; font-weight: 700;">${st.winRate.toFixed(1)}%</span> Siegquote</div>
                    </div>
                    <div>
                        <div>${st.wins}S - ${st.draws}U - ${st.losses}N</div>
                        ${hasGlicko ? `<div><strong>${sign}${st.delta.toFixed(1)}</strong> Delta</div>` : ''}
                    </div>
                </div>
                <div style="margin-top: 6px; font-size: 10px; color: #a89ec4; text-align: center; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 4px;">
                    🖱️ Klicken zum Filtern
                </div>
            `;
        } else {
            const first = playerList[0];
            let headerColor = "#ff5252";
            if (first.winRate >= 60) headerColor = "#00e676";
            else if (first.winRate >= 45) headerColor = "#ffc107";

            let playersRows = playerList.map(st => {
                const isActive = activePid && st.playerId === activePid;
                const sign = st.delta > 0 ? "+" : "";
                const bg = isActive ? "background: rgba(128, 222, 234, 0.22); border-left: 2px solid #80deea;" : "background: rgba(255,255,255,0.04);";
                return `
                    <div style="${bg} padding: 4px 8px; border-radius: 4px; margin-top: 4px; display: flex; justify-content: space-between; align-items: center; gap: 10px; cursor: pointer; transition: background 0.12s;"
                         onclick="window.PlayerCorrelationMap.selectPlayerAndFilter(${st.playerId})"
                         title="Klicken, um nach ${st.name} zu filtern">
                        <span style="font-weight: 600; color: ${isActive ? '#80deea' : '#ffffff'};">${st.name}</span>
                        <span style="font-size: 11px; color: var(--text-muted);">${st.wins}S-${st.draws}U-${st.losses}N ${hasGlicko ? `· <strong style="color:${st.delta>=0?'#88ff88':'#ff8888'}">${sign}${st.delta.toFixed(1)}</strong>` : ''}</span>
                    </div>
                `;
            }).join("");

            tooltipEl.innerHTML = `
                <div style="font-weight: 700; font-size: 12.5px; color: #ffffff; margin-bottom: 2px;">
                    👥 ${playerList.length} Spieler (${first.games} ${first.games === 1 ? 'Spiel' : 'Spiele'} · <span style="color: ${headerColor};">${first.winRate.toFixed(1)}%</span>)
                </div>
                <div style="font-size: 10.5px; color: var(--text-muted); margin-bottom: 4px;">${roleLabel}</div>
                <div style="max-height: 140px; overflow-y: auto; display: flex; flex-direction: column; gap: 2px;">
                    ${playersRows}
                </div>
                <div style="margin-top: 6px; font-size: 10px; color: #a89ec4; text-align: center; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 4px;">
                    🖱️ Klicke auf einen Spieler zum Filtern
                </div>
            `;
        }

        tooltipEl.style.display = "block";

        const containerEl = document.getElementById("corr-chart-container");
        const containerRect = containerEl.getBoundingClientRect();
        const ttWidth = tooltipEl.offsetWidth || 230;
        const ttHeight = tooltipEl.offsetHeight || 90;

        let posX = e.clientX - containerRect.left;
        let posY = e.clientY - containerRect.top;

        let transY = "-100%";
        if (posY - ttHeight - 16 < 0) {
            posY = posY + 20;
            transY = "0%";
        } else {
            posY = posY - 12;
            transY = "-100%";
        }

        const halfW = ttWidth / 2;
        const marginX = 10;
        let clampedX = Math.max(halfW + marginX, Math.min(containerRect.width - halfW - marginX, posX));

        tooltipEl.style.left = `${clampedX}px`;
        tooltipEl.style.top = `${posY}px`;
        tooltipEl.style.transform = `translate(-50%, ${transY})`;
        tooltipEl.style.margin = "0";
    }

    if (tooltipEl) {
        tooltipEl.addEventListener("mouseenter", cancelHideTooltip);
        tooltipEl.addEventListener("mouseleave", hideTooltip);
    }

    function renderMap() {
        const data = calculateStats(currentTab);

        if (data.length === 0) {
            if (svgEl) svgEl.innerHTML = "";
            if (tableBodyEl) tableBodyEl.innerHTML = "";
            if (noDataEl) noDataEl.style.display = "block";
            return;
        }

        if (noDataEl) noDataEl.style.display = "none";

        // Dimensions
        const width = 700;
        const height = 320;
        const margin = { top: 32, right: 40, bottom: 45, left: 55 };
        const plotW = width - margin.left - margin.right;
        const plotH = height - margin.top - margin.bottom;

        const maxGames = Math.max(...data.map(d => d.games), 5);

        // Build SVG elements
        let svgHtml = `
            <defs>
                <linearGradient id="gradGreen" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stop-color="#00e676" />
                    <stop offset="100%" stop-color="#28a745" />
                </linearGradient>
                <linearGradient id="gradYellow" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stop-color="#ffd54f" />
                    <stop offset="100%" stop-color="#ffb300" />
                </linearGradient>
                <linearGradient id="gradRed" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stop-color="#ff5252" />
                    <stop offset="100%" stop-color="#dc3545" />
                </linearGradient>
            </defs>

            <!-- Background Quadrant Tints -->
            <rect x="${margin.left}" y="${margin.top}" width="${plotW}" height="${plotH * 0.5}" fill="rgba(40, 167, 69, 0.05)" />
            <rect x="${margin.left}" y="${margin.top + plotH * 0.5}" width="${plotW}" height="${plotH * 0.5}" fill="rgba(220, 53, 69, 0.05)" />

            <!-- Y-Axis Grid Lines & Labels -->
        `;

        const yTicks = [100, 75, 50, 25, 0];
        yTicks.forEach(pct => {
            const y = margin.top + (1 - pct / 100) * plotH;
            const is50 = pct === 50;
            svgHtml += `
                <line x1="${margin.left}" y1="${y}" x2="${margin.left + plotW}" y2="${y}" 
                      stroke="${is50 ? '#7B52C5' : '#2d1e4d'}" 
                      stroke-width="${is50 ? '1.5' : '1'}" 
                      stroke-dasharray="${is50 ? '4,4' : 'none'}" />
                <text x="${margin.left - 10}" y="${y + 4}" text-anchor="end" fill="${is50 ? '#80deea' : '#8c80ad'}" font-size="10.5" font-weight="${is50 ? 'bold' : 'normal'}">${pct}%</text>
            `;
        });

        // X-Axis Grid Lines & Labels
        const xStep = maxGames <= 10 ? 1 : (maxGames <= 25 ? 5 : 10);
        for (let g = 0; g <= maxGames; g += xStep) {
            const x = margin.left + (g / maxGames) * plotW;
            svgHtml += `
                <line x1="${x}" y1="${margin.top}" x2="${x}" y2="${margin.top + plotH}" stroke="#2d1e4d" stroke-width="1" />
                <text x="${x}" y="${margin.top + plotH + 18}" text-anchor="middle" fill="#8c80ad" font-size="10.5">${g}</text>
            `;
        }

        // Axis Titles
        svgHtml += `
            <text x="${margin.left + plotW / 2}" y="${height - 6}" text-anchor="middle" fill="#a89ec4" font-size="11.5" font-weight="600">Gespielte Partien →</text>
            <text transform="rotate(-90)" x="${-(margin.top + plotH / 2)}" y="16" text-anchor="middle" fill="#a89ec4" font-size="11.5" font-weight="600">Siegquote (%)</text>
        `;

        // Quadrant Labels
        svgHtml += `
            <text x="${margin.left + plotW - 8}" y="${margin.top + 16}" text-anchor="end" fill="rgba(0, 230, 118, 0.4)" font-size="11" font-weight="bold">
                ${currentTab === 'teammates' ? '🏆 Hohe Synergie' : '💪 Dominanz'}
            </text>
            <text x="${margin.left + plotW - 8}" y="${margin.top + plotH - 10}" text-anchor="end" fill="rgba(255, 82, 82, 0.4)" font-size="11" font-weight="bold">
                ${currentTab === 'teammates' ? '⚠️ Schwächere Synergie' : '⚔️ Angstgegner'}
            </text>
        `;

        // Group stats by identical coordinates (games and winRate)
        const coordGroups = {};
        data.forEach(st => {
            const key = `${st.games}_${st.winRate.toFixed(2)}`;
            if (!coordGroups[key]) coordGroups[key] = [];
            coordGroups[key].push(st);
        });

        // Plot Nodes & Clusters
        Object.values(coordGroups).forEach(group => {
            const games = group[0].games;
            const winRate = group[0].winRate;
            const cx = margin.left + (games / maxGames) * plotW;
            const cy = margin.top + (1 - winRate / 100) * plotH;

            if (group.length === 1) {
                const st = group[0];
                const r = Math.min(16, Math.max(7, 6 + Math.sqrt(st.games) * 2.2));

                let grad = "url(#gradRed)";
                if (st.winRate >= 60) grad = "url(#gradGreen)";
                else if (st.winRate >= 45) grad = "url(#gradYellow)";

                const shortName = st.name.length > 10 ? st.name.substring(0, 9) + "…" : st.name;
                const labelY = (cy < margin.top + 20) ? (cy + r + 13) : (cy - r - 5);

                svgHtml += `
                    <g class="corr-node" data-pid="${st.playerId}" data-coord="${st.games}_${st.winRate.toFixed(2)}">
                        <circle cx="${cx}" cy="${cy}" r="${r}" fill="${grad}" stroke="#ffffff" stroke-width="1.5" opacity="0.92" />
                        <text x="${cx}" y="${labelY}" text-anchor="middle" fill="#ffffff" font-size="10.5" font-weight="600" style="text-shadow: 0 1px 4px rgba(0,0,0,0.9); pointer-events: none;">${shortName}</text>
                    </g>
                `;
            } else {
                // Multi-player cluster (Radial Flower / Spider layout)
                const K = group.length;
                const offsetDist = Math.min(26, 14 + K * 2.5);

                svgHtml += `<g class="corr-cluster" data-coord="${games}_${winRate.toFixed(2)}">`;

                // Center hub circle
                svgHtml += `
                    <circle cx="${cx}" cy="${cy}" r="9.5" fill="#1b1033" stroke="#80deea" stroke-width="1.5" />
                    <text x="${cx}" y="${cy + 3.5}" text-anchor="middle" fill="#80deea" font-size="9.5" font-weight="bold" pointer-events="none">${K}</text>
                `;

                // Petals
                group.forEach((st, i) => {
                    const angle = (2 * Math.PI * i / K) - Math.PI / 2;
                    const px = cx + Math.cos(angle) * offsetDist;
                    const py = cy + Math.sin(angle) * offsetDist;
                    const rp = Math.min(13, Math.max(6.5, 5.5 + Math.sqrt(st.games) * 1.8));

                    svgHtml += `
                        <line x1="${cx}" y1="${cy}" x2="${px}" y2="${py}" stroke="#7B52C5" stroke-width="1" stroke-dasharray="2,2" opacity="0.75" />
                    `;

                    let pGrad = "url(#gradRed)";
                    if (st.winRate >= 60) pGrad = "url(#gradGreen)";
                    else if (st.winRate >= 45) pGrad = "url(#gradYellow)";

                    const shortName = st.name.length > 8 ? st.name.substring(0, 7) + "…" : st.name;

                    const lx = px + Math.cos(angle) * (rp + 6);
                    const ly = py + Math.sin(angle) * (rp + 6) + 3.5;
                    let anchor = "middle";
                    if (Math.cos(angle) > 0.35) anchor = "start";
                    else if (Math.cos(angle) < -0.35) anchor = "end";

                    svgHtml += `
                        <g class="corr-petal-node" data-pid="${st.playerId}" data-coord="${games}_${winRate.toFixed(2)}">
                            <circle cx="${px}" cy="${py}" r="${rp}" fill="${pGrad}" stroke="#ffffff" stroke-width="1.3" opacity="0.95" />
                            <text x="${lx}" y="${ly}" text-anchor="${anchor}" fill="#ffffff" font-size="9.5" font-weight="600" style="text-shadow: 0 1px 4px rgba(0,0,0,0.9); pointer-events: none;">${shortName}</text>
                        </g>
                    `;
                });

                svgHtml += `</g>`;
            }
        });

        svgEl.innerHTML = svgHtml;

        // Attach node events for single nodes
        svgEl.querySelectorAll(".corr-node").forEach(node => {
            const pid = Number(node.dataset.pid);
            const st = data.find(d => d.playerId === pid);
            if (!st) return;

            node.addEventListener("mouseenter", (e) => showTooltip(e, [st], pid));
            node.addEventListener("mousemove", (e) => showTooltip(e, [st], pid));
            node.addEventListener("mouseleave", scheduleHideTooltip);
            node.addEventListener("click", () => selectPlayerAndFilter(pid));
        });

        // Attach events for clusters & petals
        svgEl.querySelectorAll(".corr-cluster").forEach(clusterEl => {
            const coord = clusterEl.dataset.coord;
            const group = coordGroups[coord] || [];
            const hubCircle = clusterEl.querySelector("circle");
            if (hubCircle) {
                hubCircle.addEventListener("mouseenter", (e) => showTooltip(e, group, null));
                hubCircle.addEventListener("mousemove", (e) => showTooltip(e, group, null));
                hubCircle.addEventListener("mouseleave", scheduleHideTooltip);
            }
        });

        svgEl.querySelectorAll(".corr-petal-node").forEach(petalEl => {
            const pid = Number(petalEl.dataset.pid);
            const coord = petalEl.dataset.coord;
            const group = coordGroups[coord] || [];

            petalEl.addEventListener("mouseenter", (e) => showTooltip(e, group, pid));
            petalEl.addEventListener("mousemove", (e) => showTooltip(e, group, pid));
            petalEl.addEventListener("mouseleave", scheduleHideTooltip);
            petalEl.addEventListener("click", (e) => {
                e.stopPropagation();
                selectPlayerAndFilter(pid);
            });
        });

        // Render breakdown table
        if (tableBodyEl) {
            const hasGlicko = window.userHasGlickoTier;
            tableBodyEl.innerHTML = data.map(st => {
                let badgeCls = "corr-badge-red";
                if (st.winRate >= 60) badgeCls = "corr-badge-green";
                else if (st.winRate >= 45) badgeCls = "corr-badge-yellow";

                const sign = st.delta > 0 ? "+" : "";
                const deltaCls = st.delta > 0 ? "delta-pos" : (st.delta < 0 ? "delta-neg" : "");
                const diffSign = st.goalDiff > 0 ? "+" : "";
                const goalsCls = st.goalDiff > 0 ? "delta-pos" : (st.goalDiff < 0 ? "delta-neg" : "");

                return `
                    <tr class="corr-table-row" onclick="window.PlayerCorrelationMap.selectPlayerAndFilter(${st.playerId})" title="Klicken, um nach ${st.name} zu filtern">
                        <td style="font-weight: 600; padding-left: 12px; color: #ffffff;">${st.name}</td>
                        <td style="text-align: center;">${st.games}</td>
                        <td style="text-align: center; color: var(--text-muted);">${st.wins}S - ${st.draws}U - ${st.losses}N</td>
                        <td style="text-align: center;"><span class="corr-badge ${badgeCls}">${st.winRate.toFixed(1)}%</span></td>
                        ${hasGlicko ? `<td style="text-align: center;" class="${deltaCls}">${sign}${st.delta.toFixed(1)}</td>` : ''}
                        <td style="text-align: center; padding-right: 12px;" class="${goalsCls}">${diffSign}${st.goalDiff} (${st.goalsFor}:${st.goalsAgainst})</td>
                    </tr>
                `;
            }).join("");
        }
    }

    // Public API
    window.PlayerCorrelationMap = {
        openModal: openModal,
        closeModal: closeModal,
        switchTab: switchTab,
        selectPlayerAndFilter: selectPlayerAndFilter
    };

    // Close on Escape key
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && modalEl && modalEl.classList.contains("open")) {
            closeModal();
        }
    });
})();
