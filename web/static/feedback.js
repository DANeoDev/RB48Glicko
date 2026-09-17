/**
 * RB48 Feedback System
 * Handles modal open/close, client telemetry collection, category switching with distinct text fields, and AJAX submission.
 */
(function() {
    window.RB48Feedback = {
        open: function() {
            const modal = document.getElementById("feedback-modal");
            const backdrop = document.getElementById("feedback-modal-backdrop");
            if (!modal || !backdrop) return;

            // Fill diagnostic preview
            const pageEl = document.getElementById("telemetry-page");
            const vpEl = document.getElementById("telemetry-vp");
            const touchEl = document.getElementById("telemetry-touch");
            if (pageEl) pageEl.textContent = window.location.pathname + window.location.search;
            if (vpEl) vpEl.textContent = `${window.innerWidth}×${window.innerHeight}`;
            const hasTouch = 'ontouchstart' in window || (navigator.maxTouchPoints > 0);
            if (touchEl) touchEl.textContent = hasTouch ? "Ja" : "Nein";

            // Default category: if mobile viewport or touch screen, select mobile_handling; otherwise general
            const defaultCat = (hasTouch || window.innerWidth <= 768) ? "mobile_handling" : "general";
            this.setCategory(defaultCat);

            backdrop.classList.add("open");
            modal.classList.add("open");
            setTimeout(() => {
                const activeTextarea = defaultCat === "mobile_handling" 
                    ? document.getElementById("feedback-message-mobile") 
                    : document.getElementById("feedback-message-general");
                if (activeTextarea) activeTextarea.focus();
            }, 100);
        },

        close: function() {
            const modal = document.getElementById("feedback-modal");
            const backdrop = document.getElementById("feedback-modal-backdrop");
            if (modal) modal.classList.remove("open");
            if (backdrop) backdrop.classList.remove("open");
        },

        setCategory: function(cat) {
            const catMobileRadio = document.getElementById("cat-mobile");
            const catGeneralRadio = document.getElementById("cat-general");
            const labelMobile = document.getElementById("label-cat-mobile");
            const labelGeneral = document.getElementById("label-cat-general");
            const groupMobile = document.getElementById("feedback-group-mobile");
            const groupGeneral = document.getElementById("feedback-group-general");

            if (cat === "mobile_handling") {
                if (catMobileRadio) catMobileRadio.checked = true;
                if (labelMobile) labelMobile.classList.add("active");
                if (labelGeneral) labelGeneral.classList.remove("active");
                if (groupMobile) groupMobile.style.display = "block";
                if (groupGeneral) groupGeneral.style.display = "none";
                const ta = document.getElementById("feedback-message-mobile");
                if (ta && document.activeElement !== ta) ta.focus();
            } else {
                if (catGeneralRadio) catGeneralRadio.checked = true;
                if (labelGeneral) labelGeneral.classList.add("active");
                if (labelMobile) labelMobile.classList.remove("active");
                if (groupGeneral) groupGeneral.style.display = "block";
                if (groupMobile) groupMobile.style.display = "none";
                const ta = document.getElementById("feedback-message-general");
                if (ta && document.activeElement !== ta) ta.focus();
            }
        },

        submit: function(e) {
            e.preventDefault();
            const submitBtn = document.getElementById("feedback-submit-btn");
            if (!submitBtn) return;

            const checkedCat = document.querySelector("input[name='feedback_category']:checked");
            const category = checkedCat ? checkedCat.value : "mobile_handling";

            const messageMobileEl = document.getElementById("feedback-message-mobile");
            const messageGeneralEl = document.getElementById("feedback-message-general");

            const message = (category === "mobile_handling" 
                ? (messageMobileEl ? messageMobileEl.value : "") 
                : (messageGeneralEl ? messageGeneralEl.value : "")).trim();

            if (!message) {
                alert("Bitte gib eine Beschreibung ein.");
                const focusEl = category === "mobile_handling" ? messageMobileEl : messageGeneralEl;
                if (focusEl) focusEl.focus();
                return;
            }

            const hasTouch = 'ontouchstart' in window || (navigator.maxTouchPoints > 0);
            const payload = {
                category: category,
                message: message,
                page_url: window.location.pathname + window.location.search,
                viewport: `${window.innerWidth}x${window.innerHeight}`,
                screen_res: `${window.screen.width}x${window.screen.height} @${window.devicePixelRatio || 1}x`,
                touch_support: hasTouch ? 1 : 0,
                user_agent: navigator.userAgent
            };

            const origText = submitBtn.innerHTML;
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span>Wird gesendet...</span>';

            fetch("/api/feedback", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                body: JSON.stringify(payload)
            })
            .then(res => res.json())
            .then(data => {
                submitBtn.disabled = false;
                submitBtn.innerHTML = origText;
                if (data.success) {
                    if (messageMobileEl) messageMobileEl.value = "";
                    if (messageGeneralEl) messageGeneralEl.value = "";
                    window.RB48Feedback.close();
                    if (window.showToast) {
                        window.showToast("Vielen Dank! Dein Feedback wurde erfasst.", 3200);
                    } else {
                        alert("Vielen Dank! Dein Feedback wurde erfasst.");
                    }
                } else {
                    alert(data.error || "Fehler beim Senden.");
                }
            })
            .catch(err => {
                submitBtn.disabled = false;
                submitBtn.innerHTML = origText;
                alert("Verbindungsfehler beim Senden des Feedbacks.");
            });
        }
    };

    // Initialize event handlers
    document.addEventListener("DOMContentLoaded", () => {
        const labelMobile = document.getElementById("label-cat-mobile");
        const labelGeneral = document.getElementById("label-cat-general");

        if (labelMobile) {
            labelMobile.addEventListener("click", () => {
                window.RB48Feedback.setCategory("mobile_handling");
            });
        }
        if (labelGeneral) {
            labelGeneral.addEventListener("click", () => {
                window.RB48Feedback.setCategory("general");
            });
        }

        // Close on ESC key
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") {
                window.RB48Feedback.close();
            }
        });
    });
})();
