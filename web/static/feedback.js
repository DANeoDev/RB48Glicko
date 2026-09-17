/**
 * RB48 Feedback System
 * Handles modal open/close, client telemetry collection, category syncing, and AJAX submission.
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
            const catMobileRadio = document.getElementById("cat-mobile");
            const catGeneralRadio = document.getElementById("cat-general");
            if (hasTouch || window.innerWidth <= 768) {
                if (catMobileRadio) catMobileRadio.checked = true;
            } else {
                if (catGeneralRadio) catGeneralRadio.checked = true;
            }
            this.syncCatLabels();

            backdrop.classList.add("open");
            modal.classList.add("open");
            setTimeout(() => {
                const textarea = document.getElementById("feedback-message");
                if (textarea) textarea.focus();
            }, 100);
        },

        close: function() {
            const modal = document.getElementById("feedback-modal");
            const backdrop = document.getElementById("feedback-modal-backdrop");
            if (modal) modal.classList.remove("open");
            if (backdrop) backdrop.classList.remove("open");
        },

        syncCatLabels: function() {
            document.querySelectorAll(".feedback-cat-label").forEach(label => {
                const radio = label.querySelector("input[type='radio']");
                if (radio && radio.checked) {
                    label.classList.add("active");
                } else {
                    label.classList.remove("active");
                }
            });
        },

        submit: function(e) {
            e.preventDefault();
            const messageEl = document.getElementById("feedback-message");
            const submitBtn = document.getElementById("feedback-submit-btn");
            if (!messageEl || !submitBtn) return;

            const message = messageEl.value.trim();
            if (!message) {
                alert("Bitte gib eine Beschreibung ein.");
                return;
            }

            const checkedCat = document.querySelector("input[name='feedback_category']:checked");
            const category = checkedCat ? checkedCat.value : "general";

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
                    messageEl.value = "";
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
        document.querySelectorAll(".feedback-cat-label").forEach(label => {
            label.addEventListener("click", () => {
                setTimeout(() => {
                    window.RB48Feedback.syncCatLabels();
                }, 10);
            });
        });

        // Close on ESC key
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") {
                window.RB48Feedback.close();
            }
        });
    });
})();
