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
});
