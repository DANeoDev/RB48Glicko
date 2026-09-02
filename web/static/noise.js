/**
 * Make Some Noise — Spatial Banter Bubbles Engine
 * RB 48 Köln e.V.
 */

(function () {
    "use strict";

    let isNoiseMode = false;
    let pendingCoords = { x: 50, y: 50 };
    let currentDrag = null;
    let loadedBubbles = [];

    const PALETTE = [
        { name: "Purple", hex: "#7B52C5" },
        { name: "Teal", hex: "#00897b" },
        { name: "Crimson", hex: "#d32f2f" },
        { name: "Amber", hex: "#e65100" },
        { name: "Midnight", hex: "#211553" },
        { name: "Cyan", hex: "#00bcd4" },
    ];

    let selectedColor = PALETTE[0].hex;

    function initNoise() {
        const container = getOrCreateContainer();
        ensureNoiseElements();
        loadPageBubbles();

        // Bind global key shortcuts
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") {
                if (isNoiseMode) toggleNoiseMode(false);
                closeCreatorModal();
            }
        });

        // Click on page in Noise Mode
        document.addEventListener("click", handlePageClickInNoiseMode, true);

        // Window resize re-positions / re-checks overlap
        let resizeTimer;
        window.addEventListener("resize", () => {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(renderAllBubbles, 200);
        });
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

                <div style="margin-bottom: 14px;">
                    <textarea id="noise-text-input" placeholder="Drop your comment or banter..." maxlength="160" rows="3" style="width: 100%; box-sizing: border-box; padding: 10px; border-radius: 8px; background: #24194A; border: 1px solid #5A4A83; color: #ffffff; font-family: Inter, sans-serif; font-size: 14px; resize: vertical;"></textarea>
                    <div style="display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted); margin-top: 4px;">
                        <span>Max 160 characters</span>
                        <span id="noise-char-count">0/160</span>
                    </div>
                </div>

                <!-- Color chips -->
                <div style="margin-bottom: 14px;">
                    <label style="font-size: 12px; font-weight: 600; color: #c9c2d8; display: block; margin-bottom: 6px;">Bubble Color:</label>
                    <div id="noise-color-chips" style="display: flex; gap: 8px; align-items: center;"></div>
                </div>

                <!-- Font & Size -->
                <div style="display: flex; gap: 10px; margin-bottom: 18px;">
                    <div style="flex: 1;">
                        <label style="font-size: 12px; font-weight: 600; color: #c9c2d8; display: block; margin-bottom: 4px;">Font:</label>
                        <select id="noise-font-family" style="width: 100%; padding: 6px; border-radius: 6px; background: #24194A; border: 1px solid #5A4A83; color: #ffffff; font-size: 13px;">
                            <option value="Inter">Clean (Inter)</option>
                            <option value="'Comic Neue', cursive, sans-serif">Banter (Comic)</option>
                            <option value="Impact, Charcoal, sans-serif">Loud (Impact)</option>
                            <option value="'Courier New', monospace">Retro (Mono)</option>
                        </select>
                    </div>
                    <div style="width: 100px;">
                        <label style="font-size: 12px; font-weight: 600; color: #c9c2d8; display: block; margin-bottom: 4px;">Size:</label>
                        <select id="noise-font-size" style="width: 100%; padding: 6px; border-radius: 6px; background: #24194A; border: 1px solid #5A4A83; color: #ffffff; font-size: 13px;">
                            <option value="13">Small</option>
                            <option value="15" selected>Medium</option>
                            <option value="18">Large</option>
                            <option value="22">Huge</option>
                        </select>
                    </div>
                </div>

                <div style="display: flex; justify-content: flex-end; gap: 10px;">
                    <button type="button" class="secondary" onclick="window.RB48Noise.closeCreator()" style="padding: 8px 14px; font-size: 13px;">Cancel</button>
                    <button type="button" id="noise-save-btn" class="primary" onclick="window.RB48Noise.saveBubble()" style="padding: 8px 20px; font-size: 13px; font-weight: 700; border-radius: 20px;">
                        Post Noise 🚀
                    </button>
                </div>
            `;
            document.body.appendChild(modal);

            // Populate palette chips
            const chipContainer = document.getElementById("noise-color-chips");
            PALETTE.forEach((c, idx) => {
                const chip = document.createElement("div");
                chip.className = `noise-color-chip ${idx === 0 ? "selected" : ""}`;
                chip.style.backgroundColor = c.hex;
                chip.title = c.name;
                chip.onclick = () => {
                    selectedColor = c.hex;
                    chipContainer.querySelectorAll(".noise-color-chip").forEach(ch => ch.classList.remove("selected"));
                    chip.classList.add("selected");
                };
                chipContainer.appendChild(chip);
            });

            // Character count listener
            const textarea = document.getElementById("noise-text-input");
            textarea.addEventListener("input", () => {
                document.getElementById("noise-char-count").textContent = `${textarea.value.length}/160`;
            });
        }
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

    function handlePageClickInNoiseMode(e) {
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
            alert("Please enter some text for your noise bubble.");
            return;
        }

        const fontSelect = document.getElementById("noise-font-family");
        const sizeSelect = document.getElementById("noise-font-size");

        const payload = {
            page_path: window.location.pathname,
            pos_x_percent: pendingCoords.x,
            pos_y_percent: pendingCoords.y,
            content: content,
            bg_color: selectedColor,
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

        const userDisplayMode = (window.RB48_USER && window.RB48_USER.noise_display_mode) || "smart";
        if (userDisplayMode === "hidden") return;

        const currentUserId = window.RB48_USER ? window.RB48_USER.id : null;
        const isStaff = window.RB48_USER && ["admin", "webmaster"].includes(window.RB48_USER.role);

        loadedBubbles.forEach((b) => {
            const canManage = isStaff || (currentUserId && currentUserId === b.user_id);
            const el = createBubbleDOM(b, canManage, userDisplayMode);
            container.appendChild(el);
        });

        // Smart overlap check after layout paint
        if (userDisplayMode === "smart") {
            setTimeout(applySmartOverlapCheck, 50);
        }
    }

    function createBubbleDOM(b, canManage, userDisplayMode) {
        const wrapper = document.createElement("div");
        wrapper.className = "noise-bubble-wrapper";
        wrapper.id = `noise-bubble-wrap-${b.id}`;
        wrapper.style.left = `${b.pos_x_percent}%`;
        wrapper.style.top = `${b.pos_y_percent}%`;

        const isAlwaysPill = userDisplayMode === "always_indicators";

        if (isAlwaysPill) {
            renderAsPill(wrapper, b, canManage);
        } else {
            renderAsFullBubble(wrapper, b, canManage);
        }

        return wrapper;
    }

    function renderAsFullBubble(wrapper, b, canManage) {
        wrapper.innerHTML = `
            <div class="noise-bubble" style="background-color: ${escapeHtml(b.bg_color)}; font-family: ${escapeHtml(b.font_family)}; font-size: ${b.font_size}px;">
                <div class="noise-bubble-content">${escapeHtml(b.content)}</div>
                <div class="noise-bubble-footer">
                    <span class="noise-bubble-author">— ${escapeHtml(b.attendance_name || b.username)}</span>
                    <div class="noise-bubble-actions">
                        ${canManage ? `<span class="noise-drag-handle" title="Drag to reposition" onmousedown="window.RB48Noise.startDrag(event, ${b.id})">✥</span>` : ""}
                        ${canManage ? `<button type="button" class="noise-btn-icon" title="Delete noise" onclick="window.RB48Noise.deleteBubble(${b.id})">✕</button>` : ""}
                    </div>
                </div>
            </div>
        `;
    }

    function renderAsPill(wrapper, b, canManage) {
        wrapper.innerHTML = `
            <div class="noise-indicator-pill">
                <span>💭 ${escapeHtml(b.attendance_name || b.username)}</span>
                <div class="pill-expanded-popover">
                    <div class="noise-bubble" style="background-color: ${escapeHtml(b.bg_color)}; font-family: ${escapeHtml(b.font_family)}; font-size: ${b.font_size}px;">
                        <div class="noise-bubble-content">${escapeHtml(b.content)}</div>
                        <div class="noise-bubble-footer">
                            <span class="noise-bubble-author">— ${escapeHtml(b.attendance_name || b.username)}</span>
                            <div class="noise-bubble-actions">
                                ${canManage ? `<span class="noise-drag-handle" title="Drag to reposition" onmousedown="window.RB48Noise.startDrag(event, ${b.id})">✥</span>` : ""}
                                ${canManage ? `<button type="button" class="noise-btn-icon" title="Delete noise" onclick="window.RB48Noise.deleteBubble(${b.id})">✕</button>` : ""}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    function applySmartOverlapCheck() {
        const wrappers = document.querySelectorAll(".noise-bubble-wrapper");
        const interactiveElements = document.querySelectorAll(
            "button, a, input, select, textarea, table th, table td, form, .card h2, .nav-links"
        );

        wrappers.forEach((wrap) => {
            const bubbleId = parseInt(wrap.id.replace("noise-bubble-wrap-", ""), 10);
            const b = loadedBubbles.find(item => item.id === bubbleId);
            if (!b) return;

            const currentUserId = window.RB48_USER ? window.RB48_USER.id : null;
            const isStaff = window.RB48_USER && ["admin", "webmaster"].includes(window.RB48_USER.role);
            const canManage = isStaff || (currentUserId && currentUserId === b.user_id);

            const wrapRect = wrap.getBoundingClientRect();
            let overlaps = false;

            for (let i = 0; i < interactiveElements.length; i++) {
                const el = interactiveElements[i];
                if (wrap.contains(el)) continue;
                const elRect = el.getBoundingClientRect();

                // Check intersection
                if (
                    wrapRect.right > elRect.left &&
                    wrapRect.left < elRect.right &&
                    wrapRect.bottom > elRect.top &&
                    wrapRect.top < elRect.bottom
                ) {
                    overlaps = true;
                    break;
                }
            }

            if (overlaps) {
                renderAsPill(wrap, b, canManage);
            }
        });
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
        };

        const onMouseMove = (moveEvt) => {
            if (!currentDrag) return;
            const container = getOrCreateContainer();
            const containerWidth = container.clientWidth || window.innerWidth;
            const containerHeight = container.clientHeight || document.body.scrollHeight;

            const posXPercent = Math.max(2, Math.min(98, (moveEvt.pageX / containerWidth) * 100));
            const posYPercent = Math.max(2, Math.min(98, (moveEvt.pageY / containerHeight) * 100));

            currentDrag.element.style.left = `${posXPercent}%`;
            currentDrag.element.style.top = `${posYPercent}%`;
            currentDrag.newX = posXPercent;
            currentDrag.newY = posYPercent;
        };

        const onMouseUp = async () => {
            document.removeEventListener("mousemove", onMouseMove);
            document.removeEventListener("mouseup", onMouseUp);

            if (currentDrag && currentDrag.newX !== undefined) {
                try {
                    await fetch(`/api/noise/${currentDrag.bubbleId}/move`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            pos_x_percent: currentDrag.newX,
                            pos_y_percent: currentDrag.newY,
                        }),
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

    async function deleteBubble(bubbleId) {
        if (!confirm("Are you sure you want to delete this noise bubble?")) return;

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
            console.error("Error deleting bubble:", err);
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
        openCreator: openCreatorModal,
        closeCreator: closeCreatorModal,
        saveBubble: saveBubble,
        startDrag: startDrag,
        deleteBubble: deleteBubble,
        refresh: loadPageBubbles,
    };

    // Auto-boot on DOMContentLoaded
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initNoise);
    } else {
        initNoise();
    }
})();
