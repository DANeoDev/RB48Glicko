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

    // Schedule Event Button
    const scheduleBtn = document.getElementById("open-schedule-modal-btn");
    if (scheduleBtn) {
        scheduleBtn.addEventListener("click", () => openModal("schedule-event-modal"));
    }

    // Attendance Name Settings Button
    document.querySelectorAll("[data-open-name-modal]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
            e.preventDefault();
            openModal("attendance-name-modal");
        });
    });

    // Webmaster Clear All Dates Modal & 2-Step Validation Watcher
    const clearAllBtn = document.getElementById("open-clear-all-modal-btn");
    if (clearAllBtn) {
        clearAllBtn.addEventListener("click", () => openModal("clear-all-modal"));
    }

    const clearCheck = document.getElementById("clear_confirm_1");
    const clearInput = document.getElementById("clear_confirm_2");
    const clearSubmit = document.getElementById("clear-all-submit-btn");

    if (clearCheck && clearInput && clearSubmit) {
        const validateClear = () => {
            const isChecked = clearCheck.checked;
            const isTyped = clearInput.value.trim().toUpperCase() === "CLEAR ALL DATES";
            clearSubmit.disabled = !(isChecked && isTyped);
        };
        clearCheck.addEventListener("change", validateClear);
        clearInput.addEventListener("input", validateClear);
    }
});
