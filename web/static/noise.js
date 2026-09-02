/**
 * Make Some Noise — Spatial Banter Bubbles Engine
 * RB 48 Köln e.V.
 */

(function () {
    "use strict";

    let isNoiseMode = false;
    let pendingCoords = { x: 50, y: 50 };
    let currentDrag = null;
    let isDraggingJustEnded = false;
    let loadedBubbles = [];

    const BG_PALETTE = [
        { name: "Royal Purple", hex: "#7B52C5" },
        { name: "Deep Emerald", hex: "#00897b" },
        { name: "Crimson Fire", hex: "#dc2626" },
        { name: "Electric Amber", hex: "#ea580c" },
        { name: "Midnight Velvet", hex: "#24194A" },
        { name: "Neon Cyan", hex: "#06b6d4" },
        { name: "Hot Magenta", hex: "#db2777" },
        { name: "Electric Lime", hex: "#65a30d" },
        { name: "Sky Blue", hex: "#2563eb" },
        { name: "Slate Charcoal", hex: "#334155" },
    ];

    const TEXT_PALETTE = [
        { name: "Pure White", hex: "#ffffff" },
        { name: "Deep Charcoal", hex: "#111827" },
        { name: "Lemon Yellow", hex: "#fef08a" },
        { name: "Neon Cyan", hex: "#22d3ee" },
        { name: "Electric Lime", hex: "#a3e635" },
        { name: "Hot Pink", hex: "#f472b6" },
        { name: "Bright Lavender", hex: "#e9d5ff" },
        { name: "Vivid Orange", hex: "#fb923c" },
        { name: "Gold Sparkle", hex: "#fbbf24" },
        { name: "Crimson Red", hex: "#ef4444" },
    ];

    const FONTS = [
        { label: "Modern (Inter)", value: "Inter, sans-serif" },
        { label: "Comic Punch (Bangers)", value: "'Bangers', Impact, cursive, sans-serif" },
        { label: "Street Graffiti (Marker)", value: "'Permanent Marker', cursive, sans-serif" },
        { label: "Handwritten (Caveat)", value: "'Caveat', cursive, sans-serif" },
        { label: "8-Bit Arcade (Press Start)", value: "'Press Start 2P', monospace" },
        { label: "Sci-Fi Cyber (Orbitron)", value: "'Orbitron', sans-serif" },
        { label: "Spooky / Grunge (Creepster)", value: "'Creepster', cursive, sans-serif" },
        { label: "Wild West (Rye)", value: "'Rye', serif" },
        { label: "Fancy Script (Great Vibes)", value: "'Great Vibes', cursive, serif" },
        { label: "Retro Typewriter (Courier)", value: "'Courier Prime', monospace" },
        { label: "Luxury Editorial (Playfair)", value: "'Playfair Display', Georgia, serif" },
    ];

    let selectedBgColor = BG_PALETTE[0].hex;
    let selectedTextColor = TEXT_PALETTE[0].hex;

    function initNoise() {
        // Only load if user is logged in
        if (!window.RB48_USER) return;

        normalizeUserMode();
        updateNavModeButton();
        getOrCreateContainer();
        ensureNoiseElements();
        loadPageBubbles();

        // Bind global key shortcuts
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") {
                if (isNoiseMode) toggleNoiseMode(false);
                closeCreatorModal();
            }
        });

        // Click on page: handle noise mode creation clicks
        document.addEventListener("click", handleDocumentClick, true);

        // Window resize
        let resizeTimer;
        window.addEventListener("resize", () => {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(renderAllBubbles, 200);
        });
    }

    function normalizeUserMode() {
        if (!window.RB48_USER) return;
        let mode = window.RB48_USER.noise_display_mode;
        if (mode === "transparent" || mode === "smart" || mode === "always_indicators" || mode === "collapsed" || !mode) {
            window.RB48_USER.noise_display_mode = "collapsed";
        } else if (mode === "always_expanded" || mode === "always_show" || mode === "expanded") {
            window.RB48_USER.noise_display_mode = "expanded";
        } else if (mode === "hidden" || mode === "muted") {
            window.RB48_USER.noise_display_mode = "muted";
        } else {
            window.RB48_USER.noise_display_mode = "collapsed";
        }
    }

    function updateNavModeButton() {
        const iconEl = document.getElementById("nav-noise-mode-icon");
        const labelEl = document.getElementById("nav-noise-mode-label");
        if (!iconEl || !labelEl || !window.RB48_USER) return;

        const mode = window.RB48_USER.noise_display_mode;
        if (mode === "expanded") {
            iconEl.textContent = "💬";
            labelEl.textContent = "Expanded";
        } else if (mode === "muted") {
            iconEl.textContent = "🔇";
            labelEl.textContent = "Muted";
        } else {
            iconEl.textContent = "💭";
            labelEl.textContent = "Collapsed";
        }
    }

    function cycleMode() {
        if (!window.RB48_USER) return;
        const current = window.RB48_USER.noise_display_mode || "collapsed";
        let nextMode = "collapsed";

        if (current === "collapsed") {
            nextMode = "expanded";
        } else if (current === "expanded") {
            nextMode = "muted";
        } else {
            nextMode = "collapsed";
        }

        setMode(nextMode);
    }

    async function setMode(mode) {
        if (!window.RB48_USER) return;
        window.RB48_USER.noise_display_mode = mode;
        normalizeUserMode();
        updateNavModeButton();
        renderAllBubbles();

        try {
            await fetch("/settings/noise-mode", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                body: JSON.stringify({ noise_display_mode: mode }),
            });
        } catch (err) {
            console.error("Failed to save noise mode setting:", err);
        }
    }

    function getOrCreateContainer() {
        let container = document.getElementById("noise-overlay-container");
        if (!container) {
            container = document.createElement("div");
            container.id = "noise-overlay-container";
            document.body.appendChild(container);
        }
        updateContainerHeight();
        return container;
    }

    function updateContainerHeight() {
        const container = document.getElementById("noise-overlay-container");
        if (container) {
            const bodyHeight = Math.max(
                document.body.scrollHeight,
                document.documentElement.scrollHeight,
                window.innerHeight
            );
            container.style.height = `${bodyHeight}px`;
        }
    }

    function ensureNoiseElements() {
        // 1. Noise Mode Banner
        if (!document.getElementById("noise-mode-banner")) {
            const banner = document.createElement("div");
            banner.id = "noise-mode-banner";
            banner.innerHTML = `
                <span>📢 <strong>Noise Mode Active:</strong> Click anywhere on the page to drop banter!</span>
                <button type="button" class="secondary" onclick="window.RB48Noise.toggle(false)" style="padding: 2px 8px; font-size: 11px; background: rgba(0,0,0,0.3); border-color: rgba(255,255,255,0.4); color: #ffffff; cursor: pointer; border-radius: 10px;">Esc</button>
            `;
            document.body.appendChild(banner);
        }

        // 2. Creator Modal
        if (!document.getElementById("noise-creator-modal")) {
            const modal = document.createElement("div");
            modal.id = "noise-creator-modal";
            modal.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 8px;">
                    <strong style="color: #80deea; font-size: 16px;">📢 Make Some Noise</strong>
                    <button type="button" onclick="window.RB48Noise.closeCreator()" style="background: none; border: none; color: #fff; font-size: 18px; cursor: pointer;">✕</button>
                </div>

                <!-- WYSIWYG Live Preview Textarea -->
                <div style="margin-bottom: 14px;">
                    <label style="font-size: 12px; font-weight: 600; color: #c9c2d8; display: block; margin-bottom: 6px;">Banter Message (Live Preview):</label>
                    <textarea id="noise-text-input" placeholder="Type your banter or comment..." maxlength="160" rows="3" style="width: 100%; box-sizing: border-box; padding: 12px 14px; border-radius: 12px; background: #7B52C5; color: #ffffff; border: 2px solid rgba(255,255,255,0.3); font-family: Inter, sans-serif; font-size: 15px; resize: vertical; box-shadow: 0 4px 14px rgba(0,0,0,0.4); transition: background-color 0.15s ease, color 0.15s ease;"></textarea>
                    <div style="display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted); margin-top: 4px;">
                        <span>Author: ${escapeHtml(window.RB48_USER?.attendance_name || window.RB48_USER?.username || 'You')}</span>
                        <span id="noise-char-count">0/160</span>
                    </div>
                </div>

                <!-- Bubble Background Color Chips -->
                <div style="margin-bottom: 12px;">
                    <label style="font-size: 12px; font-weight: 600; color: #c9c2d8; display: block; margin-bottom: 6px;">Bubble Background Color:</label>
                    <div id="noise-bg-color-chips" style="display: flex; gap: 7px; flex-wrap: wrap; align-items: center;"></div>
                </div>

                <!-- Font / Text Color Chips -->
                <div style="margin-bottom: 14px;">
                    <label style="font-size: 12px; font-weight: 600; color: #c9c2d8; display: block; margin-bottom: 6px;">Font / Text Color:</label>
                    <div id="noise-text-color-chips" style="display: flex; gap: 7px; flex-wrap: wrap; align-items: center;"></div>
                </div>

                <!-- Font Style & Size Selection -->
                <div style="display: flex; gap: 10px; margin-bottom: 18px;">
                    <div style="flex: 1;">
                        <label style="font-size: 12px; font-weight: 600; color: #c9c2d8; display: block; margin-bottom: 4px;">Font Style:</label>
                        <select id="noise-font-family" style="width: 100%; padding: 7px; border-radius: 6px; background: #24194A; border: 1px solid #5A4A83; color: #ffffff; font-size: 13px;">
                            ${FONTS.map(f => `<option value="${escapeHtml(f.value)}">${escapeHtml(f.label)}</option>`).join("")}
                        </select>
                    </div>
                    <div style="width: 110px;">
                        <label style="font-size: 12px; font-weight: 600; color: #c9c2d8; display: block; margin-bottom: 4px;">Size:</label>
                        <select id="noise-font-size" style="width: 100%; padding: 7px; border-radius: 6px; background: #24194A; border: 1px solid #5A4A83; color: #ffffff; font-size: 13px;">
                            <option value="13">Small</option>
                            <option value="15" selected>Medium</option>
                            <option value="18">Large</option>
                            <option value="22">Huge</option>
                        </select>
                    </div>
                </div>

                <div style="display: flex; justify-content: flex-end; gap: 10px;">
                    <button type="button" class="secondary" onclick="window.RB48Noise.closeCreator()" style="padding: 8px 14px; font-size: 13px;">Cancel</button>
                    <button type="button" id="noise-save-btn" class="primary" onclick="window.RB48Noise.saveBubble()" style="padding: 9px 22px; font-size: 13.5px; font-weight: 700; border-radius: 20px;">
                        Post Banter 🚀
                    </button>
                </div>
            `;
            document.body.appendChild(modal);

            // Populate background palette chips
            const bgContainer = document.getElementById("noise-bg-color-chips");
            BG_PALETTE.forEach((c, idx) => {
                const chip = document.createElement("div");
                chip.className = `noise-color-chip ${idx === 0 ? "selected" : ""}`;
                chip.style.backgroundColor = c.hex;
                chip.title = c.name;
                chip.onclick = () => {
                    selectedBgColor = c.hex;
                    bgContainer.querySelectorAll(".noise-color-chip").forEach(ch => ch.classList.remove("selected"));
                    chip.classList.add("selected");
                    syncWysiwygPreview();
                };
                bgContainer.appendChild(chip);
            });

            // Populate text color chips
            const textContainer = document.getElementById("noise-text-color-chips");
            TEXT_PALETTE.forEach((c, idx) => {
                const chip = document.createElement("div");
                chip.className = `noise-text-color-chip ${idx === 0 ? "selected" : ""}`;
                chip.style.backgroundColor = c.hex;
                chip.title = c.name;
                chip.onclick = () => {
                    selectedTextColor = c.hex;
                    textContainer.querySelectorAll(".noise-text-color-chip").forEach(ch => ch.classList.remove("selected"));
                    chip.classList.add("selected");
                    syncWysiwygPreview();
                };
                textContainer.appendChild(chip);
            });

            // Character count & input listener
            const textarea = document.getElementById("noise-text-input");
            const fontSelect = document.getElementById("noise-font-family");
            const sizeSelect = document.getElementById("noise-font-size");

            textarea.addEventListener("input", () => {
                document.getElementById("noise-char-count").textContent = `${textarea.value.length}/160`;
            });
            fontSelect.addEventListener("change", syncWysiwygPreview);
            sizeSelect.addEventListener("change", syncWysiwygPreview);
        }
    }

    function syncWysiwygPreview() {
        const textarea = document.getElementById("noise-text-input");
        const fontSelect = document.getElementById("noise-font-family");
        const sizeSelect = document.getElementById("noise-font-size");
        if (!textarea) return;

        textarea.style.backgroundColor = selectedBgColor;
        textarea.style.color = selectedTextColor;
        textarea.style.fontFamily = fontSelect ? fontSelect.value : "Inter, sans-serif";
        textarea.style.fontSize = (sizeSelect ? sizeSelect.value : "15") + "px";
    }

    function toggleNoiseMode(forceState) {
        isNoiseMode = typeof forceState === "boolean" ? forceState : !isNoiseMode;

        const navBtn = document.getElementById("nav-noise-toggle-btn");
        const banner = document.getElementById("noise-mode-banner");

        if (isNoiseMode) {
            document.body.classList.add("noise-mode-active");
            if (navBtn) navBtn.classList.add("active");
            if (banner) banner.style.display = "flex";
        } else {
            document.body.classList.remove("noise-mode-active");
            if (navBtn) navBtn.classList.remove("active");
            if (banner) banner.style.display = "none";
        }
    }

    function handleDocumentClick(e) {
        if (!isNoiseMode) return;

        // Ignore clicks inside nav, modals, or dropdowns
        if (e.target.closest("header, .site-header, #noise-creator-modal, #noise-mode-banner, .profile-dropdown")) {
            return;
        }

        e.preventDefault();
        e.stopPropagation();

        updateContainerHeight();
        const container = getOrCreateContainer();
        const containerWidth = container.clientWidth || window.innerWidth;
        const containerHeight = container.clientHeight || document.body.scrollHeight;

        const posXPercent = (e.pageX / containerWidth) * 100;
        const posYPercent = (e.pageY / containerHeight) * 100;

        pendingCoords = {
            x: Math.max(2, Math.min(98, posXPercent)),
            y: Math.max(2, Math.min(98, posYPercent)),
        };

        toggleNoiseMode(false);
        openCreatorModal();
    }

    function openCreatorModal() {
        const modal = document.getElementById("noise-creator-modal");
        const textarea = document.getElementById("noise-text-input");
        if (modal && textarea) {
            textarea.value = "";
            document.getElementById("noise-char-count").textContent = "0/160";
            syncWysiwygPreview();
            modal.style.display = "block";
            textarea.focus();
        }
    }

    function closeCreatorModal() {
        const modal = document.getElementById("noise-creator-modal");
        if (modal) modal.style.display = "none";
    }

    async function saveBubble() {
        const textarea = document.getElementById("noise-text-input");
        const content = textarea.value.trim();
        if (!content) {
            alert("Please enter some banter for your speech bubble.");
            return;
        }

        const fontSelect = document.getElementById("noise-font-family");
        const sizeSelect = document.getElementById("noise-font-size");

        const payload = {
            page_path: window.location.pathname,
            pos_x_percent: pendingCoords.x,
            pos_y_percent: pendingCoords.y,
            content: content,
            bg_color: selectedBgColor,
            text_color: selectedTextColor,
            font_family: fontSelect.value,
            font_size: parseInt(sizeSelect.value, 10) || 15,
        };

        try {
            const saveBtn = document.getElementById("noise-save-btn");
            if (saveBtn) saveBtn.disabled = true;

            const resp = await fetch("/api/noise", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });

            const data = await resp.json();
            if (data.success && data.bubble) {
                closeCreatorModal();
                loadPageBubbles();
            } else {
                alert(data.error || "Failed to post noise.");
            }
        } catch (err) {
            console.error("Error saving noise bubble:", err);
            alert("Could not post noise. Check connection.");
        } finally {
            const saveBtn = document.getElementById("noise-save-btn");
            if (saveBtn) saveBtn.disabled = false;
        }
    }

    async function loadPageBubbles() {
        try {
            const path = encodeURIComponent(window.location.pathname);
            const resp = await fetch(`/api/noise?path=${path}`);
            const data = await resp.json();
            if (data.success && Array.isArray(data.bubbles)) {
                loadedBubbles = data.bubbles;
                renderAllBubbles();
            }
        } catch (err) {
            console.error("Failed to load noise bubbles:", err);
        }
    }

    function renderAllBubbles() {
        updateContainerHeight();
        const container = getOrCreateContainer();
        container.innerHTML = "";

        const userDisplayMode = (window.RB48_USER && window.RB48_USER.noise_display_mode) || "collapsed";
        if (userDisplayMode === "muted") return;

        const currentUserId = window.RB48_USER ? window.RB48_USER.id : null;
        const isStaff = window.RB48_USER && ["admin", "webmaster"].includes(window.RB48_USER.role);

        loadedBubbles.forEach((b) => {
            const isAuthorOrStaff = isStaff || (currentUserId && currentUserId === b.user_id);
            const el = createBubbleDOM(b, isAuthorOrStaff, userDisplayMode);
            container.appendChild(el);
        });
    }

    function createBubbleDOM(b, isAuthorOrStaff, userDisplayMode) {
        const wrapper = document.createElement("div");
        wrapper.className = "noise-bubble-wrapper";
        wrapper.id = `noise-bubble-wrap-${b.id}`;
        wrapper.style.left = `${b.pos_x_percent}%`;
        wrapper.style.top = `${b.pos_y_percent}%`;

        if (userDisplayMode === "expanded") {
            renderExpandedBubble(wrapper, b, isAuthorOrStaff);
        } else {
            renderCollapsedPill(wrapper, b, isAuthorOrStaff);
        }

        return wrapper;
    }

    function renderExpandedBubble(wrapper, b, isAuthorOrStaff, canMinimize = true) {
        const textColor = escapeHtml(b.text_color || "#ffffff");
        wrapper.innerHTML = `
            <div class="noise-bubble" style="background-color: ${escapeHtml(b.bg_color)}; color: ${textColor}; font-family: ${escapeHtml(b.font_family)}; font-size: ${b.font_size}px;">
                <div class="noise-bubble-content">${escapeHtml(b.content)}</div>
                <div class="noise-bubble-footer" style="border-top-color: rgba(255, 255, 255, 0.25);">
                    <span class="noise-bubble-author" style="color: ${textColor};" title="${escapeHtml(b.attendance_name || b.username)}">${escapeHtml(b.attendance_name || b.username)}</span>
                    <div class="noise-bubble-actions">
                        <span class="noise-drag-handle" style="color: ${textColor};" title="Drag to move anywhere" onmousedown="window.RB48Noise.startDrag(event, ${b.id})">✥</span>
                        ${canMinimize ? `<button type="button" class="noise-btn-icon" style="color: ${textColor};" title="Collapse to indicator pill" onclick="window.RB48Noise.minimizeBubble(${b.id})">🔽</button>` : ""}
                        ${isAuthorOrStaff 
                            ? `<button type="button" class="noise-btn-icon" title="Delete banter globally for everyone" style="color: #ff9999;" onclick="window.RB48Noise.deleteGlobal(${b.id})">🗑️</button>`
                            : `<button type="button" class="noise-btn-icon" style="color: ${textColor};" title="Hide from my view" onclick="window.RB48Noise.dismissLocal(${b.id})">✕</button>`
                        }
                    </div>
                </div>
            </div>
        `;
    }

    function renderCollapsedPill(wrapper, b, isAuthorOrStaff) {
        wrapper.innerHTML = `
            <div class="noise-indicator-pill" id="pill-${b.id}">
                <span class="noise-drag-handle" title="Drag to move" onmousedown="window.RB48Noise.startDrag(event, ${b.id})">✥</span>
                <span class="pill-label" title="Click or hover to expand banter">💭 ${escapeHtml(b.attendance_name || b.username)}</span>
                <button type="button" class="noise-btn-icon" title="Mute all noise across site" onclick="window.RB48Noise.setMode('muted')">🔇</button>
                ${isAuthorOrStaff 
                    ? `<button type="button" class="noise-btn-icon" title="Delete banter globally for everyone" style="color: #ff9999;" onclick="window.RB48Noise.deleteGlobal(${b.id})">✕</button>`
                    : `<button type="button" class="noise-btn-icon" title="Hide from my view" onclick="window.RB48Noise.dismissLocal(${b.id})">✕</button>`
                }
            </div>
        `;

        const pill = wrapper.querySelector(".noise-indicator-pill");
        if (pill) {
            pill.addEventListener("mouseenter", (e) => {
                if (isDraggingJustEnded) return;
                if (e && (e.target.closest(".noise-drag-handle") || e.target.closest("button"))) return;

                const immunity = parseInt(wrapper.dataset.hoverImmunity || "0", 10);
                if (immunity > 0) {
                    wrapper.dataset.hoverImmunity = (immunity - 1).toString();
                    return;
                }

                renderExpandedBubble(wrapper, b, isAuthorOrStaff, true);
            });

            pill.addEventListener("click", (e) => {
                if (isDraggingJustEnded) return;
                if (e && (e.target.closest(".noise-drag-handle") || e.target.closest("button"))) return;
                wrapper.dataset.hoverImmunity = "0";
                renderExpandedBubble(wrapper, b, isAuthorOrStaff, true);
            });
        }
    }

    function minimizeBubble(bubbleId) {
        const wrap = document.getElementById(`noise-bubble-wrap-${bubbleId}`);
        const b = loadedBubbles.find(item => item.id === bubbleId);
        if (wrap && b) {
            wrap.dataset.hoverImmunity = "2";
            const currentUserId = window.RB48_USER ? window.RB48_USER.id : null;
            const isStaff = window.RB48_USER && ["admin", "webmaster"].includes(window.RB48_USER.role);
            const isAuthorOrStaff = isStaff || (currentUserId && currentUserId === b.user_id);
            renderCollapsedPill(wrap, b, isAuthorOrStaff);
        }
    }

    function startDrag(e, bubbleId) {
        e.preventDefault();
        e.stopPropagation();

        const wrap = document.getElementById(`noise-bubble-wrap-${bubbleId}`);
        if (!wrap) return;

        currentDrag = {
            bubbleId: bubbleId,
            element: wrap,
            startX: e.clientX,
            startY: e.clientY,
            didMove: false,
        };

        const onMouseMove = (moveEvt) => {
            if (!currentDrag) return;
            currentDrag.didMove = true;
            const container = getOrCreateContainer();
            const containerWidth = container.clientWidth || window.innerWidth;
            const containerHeight = container.clientHeight || document.body.scrollHeight;

            const posXPercent = Math.max(1, Math.min(99, (moveEvt.pageX / containerWidth) * 100));
            const posYPercent = Math.max(1, Math.min(99, (moveEvt.pageY / containerHeight) * 100));

            currentDrag.element.style.left = `${posXPercent}%`;
            currentDrag.element.style.top = `${posYPercent}%`;
            currentDrag.newX = posXPercent;
            currentDrag.newY = posYPercent;
        };

        const onMouseUp = async () => {
            document.removeEventListener("mousemove", onMouseMove);
            document.removeEventListener("mouseup", onMouseUp);

            if (currentDrag && currentDrag.didMove && currentDrag.newX !== undefined) {
                isDraggingJustEnded = true;
                setTimeout(() => { isDraggingJustEnded = false; }, 150);

                const bId = currentDrag.bubbleId;
                const newX = currentDrag.newX;
                const newY = currentDrag.newY;

                // Update loadedBubble local cache
                const b = loadedBubbles.find(item => item.id === bId);
                if (b) {
                    b.pos_x_percent = newX;
                    b.pos_y_percent = newY;
                }

                // Persist move to server (per-user override and base update)
                try {
                    await fetch(`/api/noise/${bId}/move`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ pos_x_percent: newX, pos_y_percent: newY }),
                    });
                } catch (err) {
                    console.error("Failed to persist bubble move:", err);
                }
            }
            currentDrag = null;
        };

        document.addEventListener("mousemove", onMouseMove);
        document.addEventListener("mouseup", onMouseUp);
    }

    async function dismissLocal(bubbleId) {
        const wrap = document.getElementById(`noise-bubble-wrap-${bubbleId}`);
        if (wrap) {
            wrap.style.transition = "opacity 0.2s ease, transform 0.2s ease";
            wrap.style.opacity = "0";
            wrap.style.transform = "translate(-50%, -50%) scale(0.6)";
            setTimeout(() => wrap.remove(), 200);
        }

        try {
            await fetch(`/api/noise/${bubbleId}/dismiss`, { method: "POST" });
            loadedBubbles = loadedBubbles.filter(b => b.id !== bubbleId);
        } catch (err) {
            console.error("Error dismissing noise:", err);
        }
    }

    async function deleteGlobal(bubbleId) {
        if (!confirm("Are you sure you want to delete this noise bubble globally for everyone?")) return;

        try {
            const resp = await fetch(`/api/noise/${bubbleId}`, { method: "DELETE" });
            const data = await resp.json();
            if (data.success) {
                loadedBubbles = loadedBubbles.filter(b => b.id !== bubbleId);
                const wrap = document.getElementById(`noise-bubble-wrap-${bubbleId}`);
                if (wrap) wrap.remove();
            } else {
                alert(data.error || "Failed to delete bubble.");
            }
        } catch (err) {
            console.error("Error deleting bubble globally:", err);
        }
    }

    function escapeHtml(str) {
        if (!str) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // Export global controller
    window.RB48Noise = {
        toggle: toggleNoiseMode,
        cycleMode: cycleMode,
        setMode: setMode,
        minimizeBubble: minimizeBubble,
        openCreator: openCreatorModal,
        closeCreator: closeCreatorModal,
        saveBubble: saveBubble,
        startDrag: startDrag,
        dismissLocal: dismissLocal,
        deleteGlobal: deleteGlobal,
        refresh: loadPageBubbles,
    };

    // Auto-boot on DOMContentLoaded
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initNoise);
    } else {
        initNoise();
    }
})();
