/**
 * RB48 Time-Scrollbar & Floating Mini-Card Component
 * Supports:
 * - Match History: Scrolling sync, tick jump, hover mini-card
 * - Stats Page: Leaderboard Time-Machine with real-time ranking and rating updates
 */

(function() {
    'use strict';

    class TimeScrollbar {
        constructor(options = {}) {
            this.pageType = options.pageType || 'matches'; // 'matches' or 'stats'
            this.data = options.data || { matchdays: [], months: [] };
            this.mode = 'matchdays'; // 'matchdays' or 'months'
            this.activeId = null;
            this.scrollTimer = null;
            this.hoverHideTimer = null;
            this.originalLeaderboardData = null;

            // Focus & Scrubber state
            this.isFocused = false;
            this.isDragging = false;
            this.lastWheelTime = 0;
            this.wheelThrottleMs = 85;
            this.statsInitialTop = null;

            this.initElements();
            this.bindEvents();
            this.render();

            // Stabilize layout and align
            setTimeout(() => this.alignWithContent(), 50);
            setTimeout(() => this.alignWithContent(), 200);
        }

        initElements() {
            this.container = document.getElementById('time-rail-container');
            if (!this.container) return;

            if (this.pageType === 'matches') {
                this.container.classList.add('time-rail-history');
            }

            this.track = document.getElementById('time-rail-track');
            this.modeBtn = document.getElementById('time-mode-toggle-btn');
            this.modeLabel = document.getElementById('time-mode-label');
            this.resetBtn = document.getElementById('time-rail-reset-btn');
            this.titleBadge = document.getElementById('time-rail-title-badge');

            // Draggable Thumb handle
            this.thumb = document.getElementById('time-rail-thumb');
            if (!this.thumb && this.track) {
                this.thumb = document.createElement('div');
                this.thumb.id = 'time-rail-thumb';
                this.thumb.className = 'time-rail-thumb';
                this.thumb.title = 'Zeitleiste ziehen / Scrollrad nutzen';
                this.thumb.innerHTML = `
                    <div class="time-rail-thumb-line"></div>
                    <div class="time-rail-thumb-line"></div>
                `;
                this.track.appendChild(this.thumb);
            }

            // Floating Mini-Card
            this.hoverCard = document.getElementById('time-hover-card');
            if (!this.hoverCard) {
                this.hoverCard = document.createElement('div');
                this.hoverCard.id = 'time-hover-card';
                this.hoverCard.className = 'time-hover-card';
                document.body.appendChild(this.hoverCard);
            }

            // Stats page specific elements
            if (this.pageType === 'stats') {
                this.banner = document.getElementById('historical-leaderboard-banner');
                this.bannerText = document.getElementById('historical-banner-text');
                this.bannerResetBtn = document.getElementById('historical-banner-reset-btn');
                this.tableBody = document.querySelector('#leaderboard tbody');
                
                if (this.tableBody) {
                    this.cacheOriginalLeaderboard();
                }
            }
        }

        cacheOriginalLeaderboard() {
            this.originalLeaderboardData = [];
            const rows = this.tableBody.querySelectorAll('tr');
            rows.forEach((row, index) => {
                const pid = parseInt(row.getAttribute('data-player-id') || row.querySelector('td:nth-child(2) a')?.href?.split('/').pop() || '0');
                this.originalLeaderboardData.push({
                    rowElement: row.cloneNode(true),
                    playerId: pid,
                    originalIndex: index
                });
            });
        }

        bindEvents() {
            if (this.modeBtn) {
                this.modeBtn.addEventListener('click', () => {
                    this.toggleMode();
                    this.setFocused(true);
                });
            }

            if (this.resetBtn) {
                this.resetBtn.addEventListener('click', () => {
                    if (this.pageType === 'stats') {
                        this.resetStatsToCurrent();
                    } else {
                        window.scrollTo({ top: 0, behavior: 'smooth' });
                    }
                    this.setFocused(true);
                });
            }

            if (this.titleBadge) {
                this.titleBadge.addEventListener('click', () => {
                    if (this.pageType === 'stats') {
                        this.resetStatsToCurrent();
                    }
                    this.setFocused(true);
                });
            }

            if (this.pageType === 'stats' && this.bannerResetBtn) {
                this.bannerResetBtn.addEventListener('click', () => this.resetStatsToCurrent());
            }

            // Container click gives focus
            if (this.container) {
                this.container.addEventListener('pointerdown', () => this.setFocused(true));
            }

            // Track click jumps directly
            if (this.track) {
                this.track.addEventListener('click', (e) => {
                    if (e.target.closest('.time-rail-thumb')) return;
                    const trackRect = this.track.getBoundingClientRect();
                    const ticks = this.track.querySelectorAll('.time-rail-tick');
                    const firstTick = ticks[0];
                    const lastTick = ticks[ticks.length - 1];
                    const minCenter = firstTick ? (firstTick.offsetTop + firstTick.offsetHeight / 2) : 12;
                    const maxCenter = lastTick ? (lastTick.offsetTop + lastTick.offsetHeight / 2) : (trackRect.height - 12);

                    const rawY = e.clientY - trackRect.top;
                    const clampedY = Math.max(minCenter, Math.min(maxCenter, rawY));
                    const span = maxCenter - minCenter;
                    const ratio = span > 0 ? (clampedY - minCenter) / span : 0;

                    const items = this.getItems();
                    if (!items || items.length === 0) return;
                    const maxIndex = items.length - 1;
                    const targetIndex = Math.max(0, Math.min(maxIndex, Math.round(ratio * maxIndex)));
                    this.selectItemByIndex(targetIndex);
                    this.setFocused(true);
                });
            }

            // Draggable Thumb interaction
            if (this.thumb) {
                this.thumb.addEventListener('mousedown', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    this.startDragging(e.clientY);
                });
                this.thumb.addEventListener('touchstart', (e) => {
                    if (e.touches && e.touches[0]) {
                        e.preventDefault();
                        e.stopPropagation();
                        this.startDragging(e.touches[0].clientY);
                    }
                }, { passive: false });
            }

            // Mouse wheel interception
            window.addEventListener('wheel', (e) => this.onWheel(e), { passive: false });

            // Click outside or Escape removes focus
            document.addEventListener('pointerdown', (e) => {
                if (!this.container) return;
                if (!this.container.contains(e.target) && !this.hoverCard.contains(e.target)) {
                    this.setFocused(false);
                }
            });

            window.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    this.setFocused(false);
                }
            });

            // Window resize & scroll sync
            window.addEventListener('resize', () => this.alignWithContent());
            window.addEventListener('scroll', () => this.onScroll(), { passive: true });
        }

        setFocused(focused) {
            this.isFocused = !!focused;
            if (!this.container) return;
            if (this.isFocused) {
                this.container.classList.add('rail-focused');
            } else {
                this.container.classList.remove('rail-focused');
                this.hideHoverCard();
            }
        }

        onWheel(e) {
            const isHoveringRail = this.container && this.container.matches(':hover');
            if (!this.isFocused && !isHoveringRail) {
                return;
            }

            // Rail handles the wheel event
            e.preventDefault();
            this.setFocused(true);

            const now = Date.now();
            if (now - this.lastWheelTime < this.wheelThrottleMs) {
                return;
            }
            this.lastWheelTime = now;

            const items = this.getItems();
            if (!items || items.length === 0) return;

            let currentIndex = items.findIndex(it => it.id === this.activeId);
            if (currentIndex === -1) currentIndex = 0;

            let nextIndex = currentIndex;
            if (e.deltaY > 0) {
                // Wheel down -> step down track to older entry
                nextIndex = Math.min(items.length - 1, currentIndex + 1);
            } else if (e.deltaY < 0) {
                // Wheel up -> step up track to newer entry
                nextIndex = Math.max(0, currentIndex - 1);
            }

            if (nextIndex !== currentIndex) {
                this.selectItemByIndex(nextIndex);
                clearTimeout(this.hoverHideTimer);
                this.hoverHideTimer = setTimeout(() => this.hideHoverCard(), 1400);
            }
        }

        startDragging(clientY) {
            this.isDragging = true;
            this.setFocused(true);
            if (this.thumb) {
                this.thumb.classList.add('dragging');
                this.thumb.style.transition = 'none';
            }

            const items = this.getItems();
            const activeItem = items.find(it => it.id === this.activeId) || items[0];
            if (activeItem && this.thumb) {
                this.showHoverCard(activeItem, this.thumb);
            }

            this.onDragMoveHandler = (e) => {
                if (!this.isDragging) return;
                const y = e.touches && e.touches[0] ? e.touches[0].clientY : e.clientY;
                this.handleDragMove(y);
            };

            this.onDragEndHandler = () => {
                if (!this.isDragging) return;
                this.isDragging = false;
                if (this.thumb) {
                    this.thumb.classList.remove('dragging');
                    this.thumb.style.transition = '';
                }
                window.removeEventListener('mousemove', this.onDragMoveHandler);
                window.removeEventListener('mouseup', this.onDragEndHandler);
                window.removeEventListener('touchmove', this.onDragMoveHandler);
                window.removeEventListener('touchend', this.onDragEndHandler);
                this.updateThumbPosition();
                clearTimeout(this.hoverHideTimer);
                this.hoverHideTimer = setTimeout(() => this.hideHoverCard(), 1200);
            };

            window.addEventListener('mousemove', this.onDragMoveHandler);
            window.addEventListener('mouseup', this.onDragEndHandler);
            window.addEventListener('touchmove', this.onDragMoveHandler, { passive: false });
            window.addEventListener('touchend', this.onDragEndHandler);
        }

        handleDragMove(clientY) {
            if (!this.track || !this.thumb) return;
            const trackRect = this.track.getBoundingClientRect();
            const ticks = this.track.querySelectorAll('.time-rail-tick');
            if (!ticks || ticks.length === 0) return;

            const firstTick = ticks[0];
            const lastTick = ticks[ticks.length - 1];
            const minCenter = firstTick ? (firstTick.offsetTop + firstTick.offsetHeight / 2) : 12;
            const maxCenter = lastTick ? (lastTick.offsetTop + lastTick.offsetHeight / 2) : (trackRect.height - 12);

            const rawY = clientY - trackRect.top;
            const clampedY = Math.max(minCenter, Math.min(maxCenter, rawY));
            this.thumb.style.top = `${clampedY}px`;

            const items = this.getItems();
            if (!items || items.length === 0) return;

            const span = maxCenter - minCenter;
            const ratio = span > 0 ? (clampedY - minCenter) / span : 0;
            const maxIndex = items.length - 1;
            const targetIndex = Math.max(0, Math.min(maxIndex, Math.round(ratio * maxIndex)));
            const item = items[targetIndex];

            if (item && item.id !== this.activeId) {
                this.activeId = item.id;
                this.updateActiveTick();
                this.showHoverCard(item, this.thumb);

                if (this.pageType === 'stats') {
                    this.applyHistoricalLeaderboard(item);
                } else if (this.pageType === 'matches') {
                    this.scrollToItem(item, false);
                }
            } else if (item) {
                this.positionHoverCard(this.thumb);
            }
        }

        selectItemByIndex(index, smooth = true) {
            const items = this.getItems();
            if (!items || index < 0 || index >= items.length) return;
            const item = items[index];
            this.activeId = item.id;
            this.updateActiveTick();
            this.updateThumbPosition();

            if (this.thumb) {
                this.showHoverCard(item, this.thumb);
            }

            if (this.pageType === 'matches') {
                this.scrollToItem(item, smooth);
            } else if (this.pageType === 'stats') {
                this.applyHistoricalLeaderboard(item);
            }
        }

        scrollToItem(item, smooth = true) {
            const targetElement = document.getElementById(item.id) || 
                                  document.querySelector(`[data-match-date="${item.date}"]`) ||
                                  document.querySelector(`[data-month-key="${item.month_key}"]`);
            if (targetElement) {
                const offset = 85;
                const bodyRect = document.body.getBoundingClientRect().top;
                const elementRect = targetElement.getBoundingClientRect().top;
                const elementPosition = elementRect - bodyRect;
                const offsetPosition = elementPosition - offset;
                window.scrollTo({
                    top: Math.max(0, offsetPosition),
                    behavior: smooth ? 'smooth' : 'auto'
                });
            }
        }

        alignWithContent() {
            if (!this.container) return;

            if (this.pageType === 'matches') {
                // History pages: align with the logo from the navigation bar
                const logo = document.querySelector('.logo img') || document.querySelector('.logo') || document.querySelector('.navbar');
                const railWidth = this.container.offsetWidth || 56;
                if (logo) {
                    const logoRect = logo.getBoundingClientRect();
                    const logoCenter = logoRect.left + (logoRect.width / 2);
                    const computedLeft = Math.max(8, Math.round(logoCenter - (railWidth / 2)));
                    this.container.style.left = `${computedLeft}px`;
                } else {
                    const historyContainer = document.querySelector('.match-history') || document.querySelector('main');
                    if (historyContainer) {
                        const rect = historyContainer.getBoundingClientRect();
                        const computedLeft = Math.max(8, Math.round(rect.left - railWidth - 16));
                        this.container.style.left = `${computedLeft}px`;
                    }
                }

                // Centered vertically in viewport
                this.container.style.top = '50%';
                this.container.style.transform = 'translateY(-50%)';

            } else if (this.pageType === 'stats') {
                this.container.style.transform = 'none';

                // 1. Horizontal: 12px to the left of leaderboard table
                const tableTarget = document.getElementById('leaderboard') || document.querySelector('.stats-table-header') || document.getElementById('stats-table-container');
                if (tableTarget) {
                    const rect = tableTarget.getBoundingClientRect();
                    const railWidth = this.container.offsetWidth || 64;
                    const computedLeft = Math.max(8, Math.round(rect.left - railWidth - 12));
                    this.container.style.left = `${computedLeft}px`;
                }

                // 2. Vertical: align 'Rating Geschichte' button top with '#open-synergies-modal-btn'
                const refBtn = document.getElementById('open-synergies-modal-btn') || document.querySelector('.stats-table-header');
                if (refBtn) {
                    // Match height of 'Rating Geschichte' button to the adjacent button
                    if (this.titleBadge) {
                        this.titleBadge.style.height = `${refBtn.offsetHeight}px`;
                    }

                    if (this.statsInitialTop === null || window.scrollY === 0) {
                        this.statsInitialTop = refBtn.getBoundingClientRect().top + window.scrollY;
                    }
                    const targetTop = Math.max(75, this.statsInitialTop - window.scrollY);
                    this.container.style.top = `${Math.round(targetTop)}px`;

                    // 3. Align the element from 'Spieltage / Monate' selector further down so it aligns with '#leaderboard thead'
                    const thead = document.querySelector('#leaderboard thead');
                    if (thead && this.modeBtn && this.titleBadge) {
                        const theadRect = thead.getBoundingClientRect();
                        const titleRect = this.titleBadge.getBoundingClientRect();
                        const targetGap = Math.max(10, Math.round(theadRect.top - titleRect.bottom));
                        this.modeBtn.style.marginTop = `${targetGap}px`;
                    }
                }
            }
        }

        onScroll() {
            // Keep stats rail top smoothly positioned
            if (this.pageType === 'stats') {
                this.alignWithContent();
            } else if (this.pageType === 'matches') {
                this.onMatchesScroll();
            }
        }

        toggleMode() {
            this.mode = this.mode === 'matchdays' ? 'months' : 'matchdays';
            this.render();
        }

        getItems() {
            return this.mode === 'matchdays' ? this.data.matchdays : this.data.months;
        }

        render() {
            if (!this.track) return;
            this.track.innerHTML = '';

            const items = this.getItems();
            if (!items || items.length === 0) return;

            // Update mode button label
            if (this.modeLabel) {
                this.modeLabel.textContent = this.mode === 'matchdays' ? 'Spieltage' : 'Monate';
            }

            items.forEach((item, index) => {
                const tick = document.createElement('div');
                tick.className = 'time-rail-tick';
                tick.dataset.id = item.id;
                tick.dataset.index = index;

                if (this.activeId === item.id) {
                    tick.classList.add('active');
                }

                // Hover events
                tick.addEventListener('mouseenter', (e) => {
                    this.showHoverCard(item, e.target);
                });
                tick.addEventListener('mousemove', (e) => {
                    this.positionHoverCard(e.target);
                });
                tick.addEventListener('mouseleave', () => {
                    if (!this.isDragging) this.hideHoverCard();
                });

                // Click event
                tick.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.selectItemByIndex(index);
                    this.setFocused(true);
                });

                this.track.appendChild(tick);
            });

            // Re-append thumb
            if (this.thumb) {
                this.track.appendChild(this.thumb);
            }

            this.updateActiveTick();
            this.updateThumbPosition();
            this.alignWithContent();
        }

        updateActiveTick() {
            if (!this.track) return;
            this.track.querySelectorAll('.time-rail-tick').forEach(tick => {
                if (tick.dataset.id === this.activeId) {
                    tick.classList.add('active');
                } else {
                    tick.classList.remove('active');
                }
            });
        }

        updateThumbPosition() {
            if (!this.thumb || !this.track) return;
            if (this.isDragging) return;

            const items = this.getItems();
            if (!items || items.length === 0) return;

            let index = items.findIndex(it => it.id === this.activeId);
            if (index === -1) index = 0;

            const ticks = this.track.querySelectorAll('.time-rail-tick');
            if (ticks && ticks[index]) {
                const tick = ticks[index];
                const tickCenter = tick.offsetTop + (tick.offsetHeight / 2);
                this.thumb.style.top = `${tickCenter}px`;
            } else {
                const trackHeight = this.track.clientHeight || 320;
                const minCenter = 12;
                const maxCenter = trackHeight - 12;
                const ratio = items.length > 1 ? (index / (items.length - 1)) : 0;
                this.thumb.style.top = `${minCenter + ratio * (maxCenter - minCenter)}px`;
            }
        }

        showHoverCard(item, targetElement) {
            if (!this.hoverCard) return;

            const dateStr = item.date_formatted || item.date || '';
            const badgeStr = item.short_label || item.label || '';
            const matchesCount = item.matches_count || 1;
            const matchesText = matchesCount === 1 ? '1 Spiel' : `${matchesCount} Spiele`;
            const pitchesText = item.pitch_types && item.pitch_types.length ? item.pitch_types.join(' & ') : '';

            this.hoverCard.innerHTML = `
                <div class="time-hover-card-header">
                    <span class="time-hover-card-date">📅 ${dateStr}</span>
                    <span class="time-hover-card-badge">${badgeStr}</span>
                </div>
                <div class="time-hover-card-sub">
                    <span>⚽ ${matchesText}</span>
                    ${pitchesText ? `<span class="pitches">· ${pitchesText}</span>` : ''}
                </div>
            `;

            this.positionHoverCard(targetElement);
            this.hoverCard.classList.add('visible');
        }

        positionHoverCard(targetElement) {
            if (!this.hoverCard || !targetElement) return;
            const rect = targetElement.getBoundingClientRect();
            const cardLeft = rect.right + 12;
            const cardTop = rect.top + (rect.height / 2) - 24;

            this.hoverCard.style.left = `${cardLeft}px`;
            this.hoverCard.style.top = `${cardTop}px`;
        }

        hideHoverCard() {
            if (this.hoverCard) {
                this.hoverCard.classList.remove('visible');
            }
        }

        // --- Matches Page Scroll Sync ---
        onMatchesScroll() {
            if (this.isDragging) return;

            const items = this.getItems();
            if (!items || items.length === 0) return;

            let closestItem = null;
            let minDistance = Infinity;

            items.forEach(item => {
                const el = document.getElementById(item.id) || 
                           document.querySelector(`[data-match-date="${item.date}"]`) ||
                           document.querySelector(`[data-month-key="${item.month_key}"]`);
                if (el) {
                    const rect = el.getBoundingClientRect();
                    const dist = Math.abs(rect.top - 120);
                    if (dist < minDistance) {
                        minDistance = dist;
                        closestItem = item;
                    }
                }
            });

            if (closestItem && this.activeId !== closestItem.id) {
                this.activeId = closestItem.id;
                this.updateActiveTick();
                this.updateThumbPosition();

                if (this.thumb) {
                    this.showHoverCard(closestItem, this.thumb);
                    clearTimeout(this.scrollTimer);
                    this.scrollTimer = setTimeout(() => this.hideHoverCard(), 1400);
                }
            }
        }

        // --- Stats Page Leaderboard Time Machine ---
        applyHistoricalLeaderboard(item) {
            if (!this.tableBody || !item.leaderboard) return;

            // Show banner
            if (this.banner && this.bannerText) {
                const isWhr = window.activeModel === 'whr' || document.querySelector('.whr-mode-banner') !== null;
                const icon = isWhr ? '🔮' : '🕒';
                const labelPrefix = isWhr ? 'Historische WHR-Ansicht' : 'Historische Ansicht';
                this.bannerText.innerHTML = `${icon} ${labelPrefix}: <span class="accent">${item.label} (${item.date_formatted})</span>`;
                this.banner.classList.add('visible');
                this.alignWithContent();
            }

            const currentPitch = (window.getCurrentPitch && window.getCurrentPitch()) || 'total';
            const sortedLeaderboard = [...item.leaderboard];
            const optedOutIds = window.optedOutPlayerIds || [];
            const isWebmaster = window.isWebmaster || false;
            const hasGlickoCols = document.querySelector('th[data-base-column="rating"]') !== null;

            sortedLeaderboard.sort((a, b) => {
                const isOptA = optedOutIds.includes(a.player_id) && !isWebmaster;
                const isOptB = optedOutIds.includes(b.player_id) && !isWebmaster;
                if (isOptA !== isOptB) return isOptA ? 1 : -1;

                const aVal = (a[currentPitch] && a[currentPitch].conservative) !== undefined ? a[currentPitch].conservative : -9999;
                const bVal = (b[currentPitch] && b[currentPitch].conservative) !== undefined ? b[currentPitch].conservative : -9999;
                return bVal - aVal;
            });

            this.tableBody.innerHTML = '';
            sortedLeaderboard.forEach((player, rank) => {
                const isOptedOut = optedOutIds.includes(player.player_id) && !isWebmaster;
                const tr = document.createElement('tr');
                tr.setAttribute('data-player-id', player.player_id);
                tr.setAttribute('data-opted-out', isOptedOut ? 'true' : 'false');

                for (const p of ['total', 'box', 'hf']) {
                    const pData = player[p] || {};
                    tr.setAttribute(`data-${p}-conservative`, isOptedOut ? 0 : (pData.conservative || 0));
                    tr.setAttribute(`data-${p}-rating`, isOptedOut ? 0 : (pData.rating || 0));
                    tr.setAttribute(`data-${p}-rd`, isOptedOut ? 999 : (pData.rd || 0));
                    tr.setAttribute(`data-${p}-games`, pData.games || 0);
                    tr.setAttribute(`data-${p}-wins`, pData.wins || 0);
                    tr.setAttribute(`data-${p}-losses`, pData.losses || 0);
                    tr.setAttribute(`data-${p}-win-percent`, pData.win_percent || 0);

                    const deltas = pData.deltas || {};
                    for (const interval of ['game', 'month', 'quarter', 'year']) {
                        const dInt = deltas[interval] || {};
                        tr.setAttribute(`data-${p}-delta-${interval}-conservative`, isOptedOut ? 0 : (dInt.conservative || 0));
                        tr.setAttribute(`data-${p}-delta-${interval}-rating`, isOptedOut ? 0 : (dInt.rating || 0));
                        tr.setAttribute(`data-${p}-delta-${interval}-rd`, isOptedOut ? 0 : (dInt.rd || 0));
                        tr.setAttribute(`data-${p}-delta-${interval}-games`, dInt.games || 0);
                        tr.setAttribute(`data-${p}-delta-${interval}-wins`, dInt.wins || 0);
                        tr.setAttribute(`data-${p}-delta-${interval}-losses`, dInt.losses || 0);
                        tr.setAttribute(`data-${p}-delta-${interval}-win-percent`, dInt.win_percent || 0);
                    }
                }

                let pitchCells = '';
                for (const p of ['total', 'box', 'hf']) {
                    const pData = player[p] || {};
                    if (hasGlickoCols) {
                        if (isOptedOut) {
                            pitchCells += `
                                <td data-pitch-cell="${p}" style="color: var(--text-muted);">—</td>
                                <td data-pitch-cell="${p}" class="delta-col delta-conservative-col" data-delta-type="conservative" style="color: var(--text-muted);">—</td>
                                <td data-pitch-cell="${p}" style="color: var(--text-muted);">—</td>
                                <td data-pitch-cell="${p}" class="delta-col delta-rating-col" data-delta-type="rating" style="color: var(--text-muted);">—</td>
                                <td data-pitch-cell="${p}" style="color: var(--text-muted);">—</td>
                                <td data-pitch-cell="${p}" class="delta-col delta-rd-col" data-delta-type="rd" style="color: var(--text-muted);">—</td>
                            `;
                        } else {
                            pitchCells += `
                                <td data-pitch-cell="${p}">${pData.conservative !== undefined ? Math.round(pData.conservative) : '—'}</td>
                                <td data-pitch-cell="${p}" class="delta-col delta-conservative-col" data-delta-type="conservative"></td>
                                <td data-pitch-cell="${p}">${pData.rating !== undefined ? Math.round(pData.rating) : '—'}</td>
                                <td data-pitch-cell="${p}" class="delta-col delta-rating-col" data-delta-type="rating"></td>
                                <td data-pitch-cell="${p}">${pData.rd !== undefined ? pData.rd.toFixed(1) : '—'}</td>
                                <td data-pitch-cell="${p}" class="delta-col delta-rd-col" data-delta-type="rd"></td>
                            `;
                        }
                    }
                    pitchCells += `
                        <td data-pitch-cell="${p}">${pData.games || 0}</td>
                        <td data-pitch-cell="${p}" class="delta-col delta-games-col" data-delta-type="games" style="display: none;"></td>
                        <td data-pitch-cell="${p}">${pData.wins || 0}</td>
                        <td data-pitch-cell="${p}" class="delta-col delta-wins-col" data-delta-type="wins" style="display: none;"></td>
                        <td data-pitch-cell="${p}">${pData.losses || 0}</td>
                        <td data-pitch-cell="${p}" class="delta-col delta-losses-col" data-delta-type="losses" style="display: none;"></td>
                        <td data-pitch-cell="${p}">${pData.win_percent !== undefined ? pData.win_percent.toFixed(1) + '%' : '0.0%'}</td>
                        <td data-pitch-cell="${p}" class="delta-col delta-win-percent-col" data-delta-type="win-percent" style="display: none;"></td>
                    `;
                }

                const optOutBadge = (isWebmaster && optedOutIds.includes(player.player_id))
                    ? '<span style="font-size: 10px; opacity: 0.7; color: #ffc107;" title="Glicko-2 Opt-out aktiv">🔒 Opt-out</span>'
                    : '';

                tr.innerHTML = `
                    <td>${isOptedOut ? '—' : rank + 1}</td>
                    <td>
                        <a href="/player/${player.player_id}">${player.alias}</a>
                        ${optOutBadge}
                    </td>
                    ${pitchCells}
                `;

                this.tableBody.appendChild(tr);
            });

            if (window.syncDeltaRowAttributesAndCells) {
                window.syncDeltaRowAttributesAndCells();
            }
            if (window.applyTableFilters) {
                window.applyTableFilters();
            }
            if (window.updateColumnVisibility) {
                window.updateColumnVisibility();
            }
        }

        resetStatsToCurrent() {
            if (!this.tableBody || !this.originalLeaderboardData) return;

            if (this.banner) {
                this.banner.classList.remove('visible');
                this.alignWithContent();
            }

            this.activeId = null;
            this.updateActiveTick();
            this.updateThumbPosition();

            this.tableBody.innerHTML = '';
            this.originalLeaderboardData.forEach(item => {
                this.tableBody.appendChild(item.rowElement.cloneNode(true));
            });

            if (window.syncDeltaRowAttributesAndCells) {
                window.syncDeltaRowAttributesAndCells();
            }
            if (window.applyTableFilters) {
                window.applyTableFilters();
            }
            if (window.updateColumnVisibility) {
                window.updateColumnVisibility();
            }
        }
    }

    // Expose class globally
    window.RB48TimeScrollbar = TimeScrollbar;
})();
