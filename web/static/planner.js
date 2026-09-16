/* Attendance Planner Interactive Behavior */

document.addEventListener("DOMContentLoaded", () => {
    // Accordion Toggle Behavior
    const eventCards = document.querySelectorAll(".planner-event-card");
    eventCards.forEach((card) => {
        const summary = card.querySelector(".planner-card-summary");
        if (!summary) return;

        summary.addEventListener("click", (e) => {
            // Prevent collapse if clicking directly on a button inside summary
            if (e.target.closest("button") || e.target.closest("a")) return;
            card.classList.toggle("expanded");
        });
    });

    // Generic Modal Open/Close System
    const openModal = (modalId) => {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.add("active");
            const firstInput = modal.querySelector("input:not([type=hidden])");
            if (firstInput) firstInput.focus();
        }
    };

    const closeModal = (modal) => {
        if (typeof modal === "string") modal = document.getElementById(modal);
        if (modal) modal.classList.remove("active");
    };

    // Close buttons and backdrop click
    document.querySelectorAll(".planner-modal-overlay").forEach((overlay) => {
        overlay.addEventListener("click", (e) => {
            if (e.target === overlay) closeModal(overlay);
        });
        const cancelBtn = overlay.querySelector(".modal-cancel-btn");
        if (cancelBtn) {
            cancelBtn.addEventListener("click", () => closeModal(overlay));
        }
    });

    // Guest Registration Buttons
    document.querySelectorAll("[data-open-guest-modal]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            if (btn.classList.contains("btn-locked")) return;

            const eventId = btn.dataset.eventId;
            const modalId = btn.dataset.openGuestModal;
            const modal = document.getElementById(modalId);
            if (modal) {
                const eventInput = modal.querySelector("input[name='event_id_target']");
                const form = modal.querySelector("form");
                if (form && eventId) {
                    form.action = `/planner/${eventId}/guest`;
                }
                openModal(modalId);
            }
        });
    });

    // Schedule Event Button & Pitch Format Dynamic Defaults
    const scheduleBtn = document.getElementById("open-schedule-modal-btn");
    const pitchSelect = document.getElementById("pitch_select");
    const eventDateInput = document.getElementById("event_date_input");
    const eventTimeInput = document.getElementById("event_time_input");
    const eventLocationInput = document.getElementById("event_location");
    const customCapacityGroup = document.getElementById("custom_capacity_group");
    const maxPlayersInput = document.getElementById("max_players_input");

    const updatePitchDefaults = () => {
        if (!pitchSelect) return;
        const format = pitchSelect.value;
        if (format === "box") {
            if (eventLocationInput) eventLocationInput.value = "Soccerbox - Unisport";
            if (eventTimeInput) eventTimeInput.value = "20:00";
            if (customCapacityGroup) customCapacityGroup.style.display = "none";
            if (maxPlayersInput) maxPlayersInput.value = "12";
        } else if (format === "hf") {
            if (eventLocationInput) eventLocationInput.value = "Halbfeld - Zülpicher Wall 5";
            if (eventTimeInput) eventTimeInput.value = "20:30";
            if (customCapacityGroup) customCapacityGroup.style.display = "none";
            if (maxPlayersInput) maxPlayersInput.value = "18";
        } else if (format === "custom") {
            if (eventLocationInput) {
                eventLocationInput.value = "";
                eventLocationInput.placeholder = "e.g. Venue / Pitch Name";
            }
            if (customCapacityGroup) customCapacityGroup.style.display = "block";
            if (maxPlayersInput && (!maxPlayersInput.value || maxPlayersInput.value === "12" || maxPlayersInput.value === "18")) {
                maxPlayersInput.value = "14";
            }
        }
    };

    if (pitchSelect) {
        pitchSelect.addEventListener("change", updatePitchDefaults);
    }

    if (scheduleBtn) {
        scheduleBtn.addEventListener("click", () => {
            if (eventDateInput && !eventDateInput.value) {
                const tomorrow = new Date();
                tomorrow.setDate(tomorrow.getDate() + 1);
                eventDateInput.value = tomorrow.toISOString().split("T")[0];
            }
            updatePitchDefaults();
            openModal("schedule-event-modal");
        });
    }

    // Attendance Name Settings Button
    document.querySelectorAll("[data-open-name-modal]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
            e.preventDefault();
            openModal("attendance-name-modal");
        });
    });

    // Webmaster Clear Dates Modal & 2-Step Validation Watcher
    const clearAllBtn = document.getElementById("open-clear-all-modal-btn");
    if (clearAllBtn) {
        clearAllBtn.addEventListener("click", () => openModal("clear-all-modal"));
    }

    const clearCheckboxes = document.querySelectorAll(".clear-date-checkbox");
    const selectAllBtn = document.getElementById("clear-select-all-btn");
    const deselectAllBtn = document.getElementById("clear-deselect-all-btn");
    const selectedCountSpan = document.getElementById("clear-selected-count");
    const clearInput = document.getElementById("clear_confirm_text");
    const clearSubmit = document.getElementById("clear-dates-submit-btn");

    const updateClearValidation = () => {
        const checkedCount = document.querySelectorAll(".clear-date-checkbox:checked").length;
        if (selectedCountSpan) {
            selectedCountSpan.textContent = checkedCount.toString();
        }
        const isTyped = clearInput ? clearInput.value.trim().toUpperCase() === "CLEAR DATES" : false;
        if (clearSubmit) {
            clearSubmit.disabled = !(checkedCount > 0 && isTyped);
        }
    };

    if (selectAllBtn) {
        selectAllBtn.addEventListener("click", () => {
            clearCheckboxes.forEach((cb) => { cb.checked = true; });
            updateClearValidation();
        });
    }

    if (deselectAllBtn) {
        deselectAllBtn.addEventListener("click", () => {
            clearCheckboxes.forEach((cb) => { cb.checked = false; });
            updateClearValidation();
        });
    }

    clearCheckboxes.forEach((cb) => {
        cb.addEventListener("change", updateClearValidation);
    });

    if (clearInput) {
        clearInput.addEventListener("input", updateClearValidation);
    }

    // Admin Edit Attendee Modal
    document.querySelectorAll(".planner-edit-btn").forEach((btn) => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const attendeeId = btn.dataset.attendeeId;
            const eventId = btn.dataset.eventId;
            const name = btn.dataset.name || "";
            const status = btn.dataset.status || "attending";

            const form = document.getElementById("edit-attendee-form");
            const nameInput = document.getElementById("edit_attendee_name");
            const statusSelect = document.getElementById("edit_attendee_status");

            if (form && attendeeId && eventId) {
                form.action = `/planner/${eventId}/attendee/${attendeeId}/edit`;
            }
            if (nameInput) nameInput.value = name;
            if (statusSelect) statusSelect.value = status;

            openModal("edit-attendee-modal");
        });
    });

    // Admin & Webmaster Matchday Attendance Log Modal
    let currentMatchdayLogs = [];
    let currentLogFilter = "all";

    const renderMatchdayLogs = () => {
        const tbody = document.getElementById("log-modal-tbody");
        const emptyBox = document.getElementById("log-modal-empty");
        if (!tbody || !emptyBox) return;

        const filtered = currentLogFilter === "all"
            ? currentMatchdayLogs
            : currentMatchdayLogs.filter((l) => l.action === currentLogFilter);

        tbody.innerHTML = "";
        if (filtered.length === 0) {
            emptyBox.style.display = "block";
            return;
        }
        emptyBox.style.display = "none";

        filtered.forEach((log) => {
            const tr = document.createElement("tr");
            tr.style.borderBottom = "1px solid rgba(255,255,255,0.06)";

            let badgeStyle = "background: rgba(255,255,255,0.06); color: var(--text-muted);";
            if (log.action === "registered") {
                badgeStyle = "background: rgba(40, 167, 69, 0.25); color: #88ff88; border: 1px solid rgba(40, 167, 69, 0.4);";
            } else if (log.action === "cancelled") {
                badgeStyle = "background: rgba(220, 53, 69, 0.25); color: #ff8888; border: 1px solid rgba(220, 53, 69, 0.4);";
            } else if (log.action === "declined") {
                badgeStyle = "background: rgba(255, 193, 7, 0.25); color: #ffe082; border: 1px solid rgba(255, 193, 7, 0.4);";
            }

            let typeBadge = "";
            if (log.attendee_type === "visitor") {
                typeBadge = `<span style="font-size: 10.5px; background: rgba(128, 222, 234, 0.15); color: #80deea; border: 1px solid rgba(128, 222, 234, 0.3); padding: 1px 6px; border-radius: 8px;">Besucher</span>`;
            } else if (log.attendee_type === "member_guest") {
                typeBadge = `<span style="font-size: 10.5px; background: rgba(255, 193, 7, 0.15); color: #ffd54f; border: 1px solid rgba(255, 193, 7, 0.3); padding: 1px 6px; border-radius: 8px;">Gast</span>`;
            } else {
                typeBadge = `<span style="font-size: 10.5px; background: rgba(123, 82, 197, 0.15); color: #c9c2d8; border: 1px solid rgba(123, 82, 197, 0.3); padding: 1px 6px; border-radius: 8px;">Mitglied</span>`;
            }

            tr.innerHTML = `
                <td style="padding: 9px 12px; color: var(--text-muted); font-size: 11.5px; white-space: nowrap;">${log.formatted_time}</td>
                <td style="padding: 9px 12px; font-weight: 600; color: #ffffff;">${log.name}</td>
                <td style="padding: 9px 12px;">${typeBadge}</td>
                <td style="padding: 9px 12px;">
                    <span style="display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 700; ${badgeStyle}">
                        ${log.action_icon || ""} ${log.action_label || log.action}
                    </span>
                </td>
                <td style="padding: 9px 12px; color: var(--text-muted); font-size: 12px;">${log.actor_name || "System"}</td>
            `;
            tbody.appendChild(tr);
        });
    };

    document.querySelectorAll(".btn-matchday-log").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
            e.stopPropagation();
            const eventId = btn.dataset.eventId;
            const eventTitle = btn.dataset.eventTitle || `Spieltag #${eventId}`;

            const titleEl = document.getElementById("log-modal-event-title");
            const dashboardLink = document.getElementById("log-modal-dashboard-link");
            const tbody = document.getElementById("log-modal-tbody");
            const emptyBox = document.getElementById("log-modal-empty");
            const loadingBox = document.getElementById("log-modal-loading");

            if (titleEl) titleEl.textContent = eventTitle;
            if (dashboardLink) dashboardLink.href = `/admin/attendance-logs?event_id=${eventId}`;
            if (tbody) tbody.innerHTML = "";
            if (emptyBox) emptyBox.style.display = "none";
            if (loadingBox) loadingBox.style.display = "block";

            // Reset filter buttons
            currentLogFilter = "all";
            document.querySelectorAll(".log-filter-btn").forEach((fb) => {
                const isAll = fb.dataset.action === "all";
                fb.style.background = isAll ? "var(--accent)" : "var(--bg-surface-alt)";
                fb.style.borderColor = isAll ? "var(--accent)" : "var(--border)";
                fb.style.color = isAll ? "#ffffff" : (fb.dataset.action === "registered" ? "#88ff88" : (fb.dataset.action === "cancelled" ? "#ff8888" : "#ffe082"));
            });

            openModal("matchday-log-modal");

            try {
                const resp = await fetch(`/planner/${eventId}/logs`);
                const data = await resp.json();
                if (loadingBox) loadingBox.style.display = "none";

                if (data.success) {
                    currentMatchdayLogs = data.logs || [];
                    const counts = data.counts || {};
                    const countAll = document.getElementById("log-count-all");
                    const countReg = document.getElementById("log-count-registered");
                    const countCan = document.getElementById("log-count-cancelled");
                    const countDec = document.getElementById("log-count-declined");

                    if (countAll) countAll.textContent = counts.total || 0;
                    if (countReg) countReg.textContent = counts.registered || 0;
                    if (countCan) countCan.textContent = counts.cancelled || 0;
                    if (countDec) countDec.textContent = counts.declined || 0;

                    renderMatchdayLogs();
                } else {
                    if (emptyBox) {
                        emptyBox.textContent = data.error || "Fehler beim Laden der Logdaten.";
                        emptyBox.style.display = "block";
                    }
                }
            } catch (err) {
                if (loadingBox) loadingBox.style.display = "none";
                if (emptyBox) {
                    emptyBox.textContent = "Netzwerkfehler beim Abrufen der Logs.";
                    emptyBox.style.display = "block";
                }
            }
        });
    });

    // In-modal filter button clicks
    document.querySelectorAll(".log-filter-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            currentLogFilter = btn.dataset.action;
            document.querySelectorAll(".log-filter-btn").forEach((fb) => {
                const isActive = fb === btn;
                fb.style.background = isActive ? "var(--accent)" : "var(--bg-surface-alt)";
                fb.style.borderColor = isActive ? "var(--accent)" : "var(--border)";
                fb.style.color = isActive ? "#ffffff" : (fb.dataset.action === "registered" ? "#88ff88" : (fb.dataset.action === "cancelled" ? "#ff8888" : (fb.dataset.action === "declined" ? "#ffe082" : "var(--text-muted)")));
            });
            renderMatchdayLogs();
        });
    });
});
