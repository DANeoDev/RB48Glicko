/**
 * RB48 Interactive Multi-Page Feature Tour
 * Guides new and existing users through all key club platform features.
 */
(function() {
    'use strict';

    const TOUR_STEPS = [
        {
            id: 'stats_table',
            url: '/stats',
            selector: '#stats-table-container, #leaderboard',
            title_de: '📊 Die Vereinsrangliste',
            title_en: '📊 Club Leaderboard',
            desc_de: 'Hier findest du die Übersicht aller aktiven Spieler. Auf einen Blick erkennst du absolvierte Spiele, Siege, Niederlagen und die prozentuale Siegquote (W%).',
            desc_en: 'Here you can view the leaderboard with all active players, showing matches played, wins, losses, and win percentages.'
        },
        {
            id: 'stats_filters',
            url: '/stats',
            selector: '.stats-table-header',
            title_de: '🏟️ Formate, Zeiträume & Deltas',
            title_en: '🏟️ Pitches, Timeframes & Deltas',
            desc_de: 'Schalte flexibel zwischen Gesamtbilanz (TOTAL), Soccerbox (BOX) und Halbfeld (HF) um. Über die Delta-Auswahl rechts kannst du kurzfristige Formänderungen (letztes Spiel, Monat) analysieren.',
            desc_en: 'Switch between TOTAL, Soccerbox (BOX), and Half-field (HF). Use the delta controls on the right to analyze recent form changes.'
        },
        {
            id: 'stats_synergies',
            url: '/stats',
            selector: '.stats-header-spacer',
            title_de: '🤝 Duos, Serien & Profile',
            title_en: '🤝 Duos, Streaks & Profiles',
            desc_de: 'Über die Buttons oben erreichst du Traum-Duos & Angstgegner sowie aktive Siegesserien. Ein Klick auf einen Spielernamen in der Tabelle bringt dich direkt zu dessen detailliertem Spielerprofil!',
            desc_en: 'Explore dream duos, rivalries, and winning streaks with the buttons above. Click any player name to open their personal profile!'
        },
        {
            id: 'mvp_voting',
            url: '/matches',
            selector: '.match:first-child, .matches-list',
            title_de: '🗳️ MVP-Abstimmung an Spieltagen',
            title_en: '🗳️ Matchday MVP Voting',
            desc_de: 'Nach jedem Spieltag können alle anwesenden Spieler bis zum Folgetag um 20:00 Uhr die besten Spieler wählen (Gold, Silber, Bronze). Keine Selbstwahl erlaubt! Klicke auf eine Spielkarte, um abzustimmen.',
            desc_en: 'After each matchday, players can vote for the top performers (Gold, Silver, Bronze) until 20:00 the next day. Self-voting is disallowed. Click any match card to vote!'
        },
        {
            id: 'mvp_medals',
            url: '/stats/mvp-medals',
            selector: '.medals-table-container, .medals-filter-container',
            title_de: '🏅 Ewiger Medaillenspiegel',
            title_en: '🏅 All-Time Medal Table',
            desc_de: 'Alle errungenen Gold-, Silber- und Bronzemedaillen fließen in diesen Medaillenspiegel ein. Filtere nach Saisons oder Spielformaten, um zu sehen, wer die meisten Auszeichnungen hält.',
            desc_en: 'All earned medals are tracked in the all-time table. Filter by season or pitch format to see who leads the MVP rankings.'
        },
        {
            id: 'positions',
            url: '/settings',
            selector: '#position-preferences-box, #player_id, #settings-profile-card',
            title_de: '⚽ Positionspräferenzen (Reine Orientierung!)',
            title_en: '⚽ Position Preferences (Orientation Only!)',
            desc_de: 'Hier kannst du deine bevorzugten Positionen (Torwart, Abwehr, Mittelfeld, Sturm) angeben.<br><br><strong style="color: #ffd700;">Wichtiger Hinweis:</strong> Diese Angaben dienen dem automatischen Matchmaker als Orientierungshilfe für ausgeglichene Teams – sie sind reine Information und bedeuten <em>niemals</em>, dass du auf dem Platz nur dort spielen musst oder darfst!',
            desc_en: 'Set your preferred positions (GK, DEF, MID, ATT) and primary role.<br><br><strong style="color: #ffd700;">Important:</strong> These preferences serve solely as an orientation guide for the matchmaker. They <em>never</em> restrict where you can or must play on the pitch!'
        },
        {
            id: 'glicko_assessment',
            url: '/settings',
            selector: '#glicko-assessment-card',
            title_de: '🧠 Glicko-Aktivierung & Psychologietest',
            title_en: '🧠 Glicko Clearance & Assessment',
            desc_de: 'Um Spielspaß zu bewahren und Rating-Toxizität zu verhindern, werden detaillierte Glicko-2-Zahlen erst nach Absolvieren unseres humorvollen I.M.P.-Persönlichkeitstests sichtbar. Der Test kann jederzeit im Menü oder hier wiederholt werden!',
            desc_en: 'To maintain friendly competition and prevent toxicity, detailed Glicko-2 numbers are unlocked after taking our humorous personality assessment. You can retake it at any time!'
        },
        {
            id: 'glicko_opt_out',
            url: '/settings',
            selector: '#glicko-opt-out-box',
            title_de: '🙈 Glicko-2 Opt-Out',
            title_en: '🙈 Glicko-2 Opt-Out',
            desc_de: 'Blende dein Glicko-2-Rating und deine RD für alle anderen Mitspieler aus. Dein Account wird auf die Standard-Ansicht ohne Ratings zurückgestuft, während deine Spiele normal weitergezählt werden.',
            desc_en: 'Hide your Glicko-2 rating and RD from all other players. Your account switches to standard view without numerical ratings.'
        },
        {
            id: 'stats_opt_out',
            url: '/settings',
            selector: '#stats-opt-out-box',
            title_de: '🚫 Vollständiges Statistik Opt-Out',
            title_en: '🚫 Full Statistics Opt-Out',
            desc_de: 'Verstecke deine Siege, Niederlagen, Siegquoten und Heatmaps komplett. Nur die Anzahl deiner gespielten Partien bleibt öffentlich sichtbar. Du kannst die Statistik-Seite danach selbst nicht mehr aufrufen.',
            desc_en: 'Completely hide your wins, losses, win rates, and synergies across the platform. Only total matches played remain visible, and the statistics page becomes inaccessible to you.'
        },
        {
            id: 'achievements',
            url: '/achievements',
            selector: '.achievements-hero-card, .achievements-page-wrap',
            title_de: '🏆 Auszeichnungen & Century Club',
            title_en: '🏆 Achievements & Milestones',
            desc_de: 'Erreiche Meilensteine und verdiene Trophäen! Von Teilnahmerekorden wie dem <em>Century Club</em> (100 Spiele) über Siegesserien bis hin zu MVP-Wahlen. Neue Auszeichnungen lassen dein Profil-Icon leuchten!',
            desc_en: 'Unlock trophies for milestones such as the <em>Century Club</em> (100 matches), streaks, or MVP awards. New achievements make your profile icon glow!'
        },
        {
            id: 'faq',
            url: '/glickofaq',
            selector: '#faq-content, .page-header',
            title_de: '📐 Modellanalyse & Glicko-FAQ',
            title_en: '📐 Model Guide & Glicko FAQ',
            desc_de: 'Hier findest du das mathematische Regelwerk unseres Glicko-2-Systems, Erklärungen zu RD und Kalibrierung sowie Antworten auf alle offenen Fragen zum Verein und Matchmaking.',
            desc_en: 'Here you can explore the mathematical framework of our Glicko-2 system, explanations of RD and calibration, and answers to common club questions.'
        }
    ];

    class FeatureTourEngine {
        constructor() {
            this.currentStep = 0;
            this.backdrop = null;
            this.card = null;
            this.currentHighlighted = null;
            this.lang = document.documentElement.lang === 'en' ? 'en' : 'de';
        }

        isLoggedIn() {
            if (window.RB48_USER && window.RB48_USER.id) {
                return true;
            }
            if (document.body && document.body.dataset && document.body.dataset.userLoggedIn === 'true') {
                return true;
            }
            return false;
        }

        restart() {
            localStorage.removeItem('rb48_tour_completed');
            localStorage.removeItem('rb48_tour_dismissed');
            this.start(0);
        }

        init() {
            const isAuthPage = window.location.pathname.startsWith('/login') || window.location.pathname.startsWith('/register');
            if (!this.isLoggedIn() || isAuthPage) {
                // Clear any leftover tour session state to prevent redirect loops for unauthenticated visitors
                sessionStorage.removeItem('rb48_tour_active');
                sessionStorage.removeItem('rb48_tour_step');
                return;
            }

            // Check for tour continuation from sessionStorage or URL query params
            const urlParams = new URLSearchParams(window.location.search);
            const paramStep = urlParams.get('tour_step');
            const sessionActive = sessionStorage.getItem('rb48_tour_active') === 'true';
            const sessionStep = sessionStorage.getItem('rb48_tour_step');

            let targetStep = null;
            if (paramStep !== null) {
                targetStep = parseInt(paramStep, 10);
            } else if (sessionActive && sessionStep !== null) {
                targetStep = parseInt(sessionStep, 10);
            }

            if (targetStep !== null && !isNaN(targetStep) && targetStep >= 0 && targetStep < TOUR_STEPS.length) {
                // Clean URL query param without full reload
                if (paramStep !== null) {
                    urlParams.delete('tour_step');
                    const newQuery = urlParams.toString();
                    const newUrl = window.location.pathname + (newQuery ? '?' + newQuery : '') + window.location.hash;
                    window.history.replaceState({}, document.title, newUrl);
                }

                setTimeout(() => {
                    this.start(targetStep);
                }, 300);
            } else {
                this.checkWelcomeToast();
            }
        }

        checkWelcomeToast() {
            if (!this.isLoggedIn()) return;

            const dismissed = localStorage.getItem('rb48_tour_dismissed') === 'true';
            const completed = localStorage.getItem('rb48_tour_completed') === 'true';

            if (!dismissed && !completed) {
                // Add pulse indicator to profile button
                const profileBtn = document.querySelector('.profile-button');
                if (profileBtn) {
                    profileBtn.classList.add('rb48-tour-pulse-btn');
                }

                // Show friendly welcome toast after 1.5s
                setTimeout(() => {
                    this.showWelcomeToast();
                }, 1500);
            }
        }

        showWelcomeToast() {
            if (!this.isLoggedIn() || document.getElementById('rb48-tour-welcome-toast')) return;

            const toast = document.createElement('div');
            toast.id = 'rb48-tour-welcome-toast';
            toast.className = 'rb48-tour-toast';

            const title = this.lang === 'en' ? 'New to RB48?' : 'Neu bei RB48?';
            const text = this.lang === 'en'
                ? 'Discover all interactive features in a quick 2-minute tour!'
                : 'Entdecke alle interaktiven Funktionen in einer kurzen 2-Minuten-Tour!';
            const startBtnText = this.lang === 'en' ? 'Start Tour 🚀' : 'Tour starten 🚀';

            toast.innerHTML = `
                <div class="rb48-tour-toast-content">
                    <span class="rb48-tour-toast-icon">🚀</span>
                    <div class="rb48-tour-toast-text">
                        <strong>${title}</strong>
                        <p>${text}</p>
                    </div>
                </div>
                <div class="rb48-tour-toast-actions">
                    <button type="button" class="rb48-tour-btn rb48-tour-btn-next" id="rb48-toast-start">${startBtnText}</button>
                    <button type="button" class="rb48-tour-btn rb48-tour-btn-dismiss" id="rb48-toast-dismiss">✕</button>
                </div>
            `;

            document.body.appendChild(toast);

            document.getElementById('rb48-toast-start').addEventListener('click', () => {
                this.dismissWelcome();
                this.start(0);
            });

            document.getElementById('rb48-toast-dismiss').addEventListener('click', () => {
                this.dismissWelcome();
            });
        }

        dismissWelcome() {
            localStorage.setItem('rb48_tour_dismissed', 'true');
            const toast = document.getElementById('rb48-tour-welcome-toast');
            if (toast) {
                toast.style.opacity = '0';
                toast.style.transform = 'translateY(20px)';
                setTimeout(() => toast.remove(), 250);
            }
            const profileBtn = document.querySelector('.profile-button');
            if (profileBtn) {
                profileBtn.classList.remove('rb48-tour-pulse-btn');
            }
        }

        start(stepIndex = 0) {
            const isAuthPage = window.location.pathname.startsWith('/login') || window.location.pathname.startsWith('/register');
            if (!this.isLoggedIn() || isAuthPage) {
                sessionStorage.removeItem('rb48_tour_active');
                sessionStorage.removeItem('rb48_tour_step');
                return;
            }

            this.dismissWelcome();
            sessionStorage.setItem('rb48_tour_active', 'true');
            sessionStorage.setItem('rb48_tour_step', stepIndex.toString());
            this.currentStep = stepIndex;

            const step = TOUR_STEPS[this.currentStep];
            if (!step) return;

            // Normalize current path
            const currentPath = window.location.pathname.replace(/\/+$/, '');
            const targetPath = step.url.replace(/\/+$/, '');

            if (currentPath !== targetPath) {
                // Navigate to step URL
                window.location.href = step.url + '?tour_step=' + this.currentStep;
                return;
            }

            this.createOverlay();
            this.renderStep();
        }

        createOverlay() {
            if (!this.backdrop) {
                this.backdrop = document.createElement('div');
                this.backdrop.className = 'rb48-tour-backdrop';
                this.backdrop.addEventListener('click', () => {
                    // Clicking backdrop advances tour
                    this.next();
                });
                document.body.appendChild(this.backdrop);
            }
            requestAnimationFrame(() => {
                this.backdrop.classList.add('active');
            });

            if (!this.card) {
                this.card = document.createElement('div');
                this.card.className = 'rb48-tour-card';
                this.card.setAttribute('role', 'dialog');
                this.card.setAttribute('aria-modal', 'true');
                document.body.appendChild(this.card);
            }
        }

        renderStep() {
            const step = TOUR_STEPS[this.currentStep];
            if (!step) return;

            // Clear previous highlight
            if (this.currentHighlighted) {
                this.currentHighlighted.classList.remove('rb48-tour-spotlight-active');
                this.currentHighlighted = null;
            }

            // Find target element with selector fallback
            let targetEl = null;
            const selectors = step.selector.split(',').map(s => s.trim());
            for (const sel of selectors) {
                targetEl = document.querySelector(sel);
                if (targetEl && targetEl.offsetParent !== null) break;
            }

            // Fallback to first matched or document body
            if (!targetEl && selectors.length > 0) {
                targetEl = document.querySelector(selectors[0]);
            }

            if (targetEl) {
                this.currentHighlighted = targetEl;
                targetEl.classList.add('rb48-tour-spotlight-active');

                // Smooth scroll into center view
                targetEl.scrollIntoView({
                    behavior: 'smooth',
                    block: 'center',
                    inline: 'center'
                });
            }

            const stepNumber = this.currentStep + 1;
            const totalSteps = TOUR_STEPS.length;
            const progressPercent = Math.round((stepNumber / totalSteps) * 100);

            const title = this.lang === 'en' ? step.title_en : step.title_de;
            const desc = this.lang === 'en' ? step.desc_en : step.desc_de;
            const stepBadge = this.lang === 'en' 
                ? `Step ${stepNumber} of ${totalSteps}` 
                : `Schritt ${stepNumber} von ${totalSteps}`;
            const btnPrevText = this.lang === 'en' ? '← Back' : '← Zurück';
            const btnNextText = this.currentStep === totalSteps - 1 
                ? (this.lang === 'en' ? 'Finish 🎉' : 'Abschließen 🎉') 
                : (this.lang === 'en' ? 'Next →' : 'Weiter →');
            const btnEndText = this.lang === 'en' ? 'Close' : 'Beenden';

            this.card.innerHTML = `
                <div class="rb48-tour-header">
                    <span class="rb48-tour-step-badge">${stepBadge}</span>
                    <button type="button" class="rb48-tour-close-btn" id="rb48-tour-btn-close" aria-label="Tour beenden" title="${btnEndText}">✕</button>
                </div>
                <div class="rb48-tour-progress-bar">
                    <div class="rb48-tour-progress-fill" style="width: ${progressPercent}%;"></div>
                </div>
                <div class="rb48-tour-title">${title}</div>
                <div class="rb48-tour-body">${desc}</div>
                <div class="rb48-tour-footer">
                    <button type="button" class="rb48-tour-btn rb48-tour-btn-dismiss" id="rb48-tour-btn-stop">${btnEndText}</button>
                    <div class="rb48-tour-btn-group">
                        ${this.currentStep > 0 ? `<button type="button" class="rb48-tour-btn rb48-tour-btn-prev" id="rb48-tour-btn-prev">${btnPrevText}</button>` : ''}
                        <button type="button" class="rb48-tour-btn rb48-tour-btn-next" id="rb48-tour-btn-next">${btnNextText}</button>
                    </div>
                </div>
            `;

            // Position card near target on desktop
            this.positionCard(targetEl);

            // Bind listeners
            document.getElementById('rb48-tour-btn-close').addEventListener('click', () => this.stop());
            document.getElementById('rb48-tour-btn-stop').addEventListener('click', () => this.stop());
            if (this.currentStep > 0) {
                document.getElementById('rb48-tour-btn-prev').addEventListener('click', () => this.prev());
            }
            document.getElementById('rb48-tour-btn-next').addEventListener('click', () => this.next());

            // Focus next button
            const nextBtn = document.getElementById('rb48-tour-btn-next');
            if (nextBtn) nextBtn.focus();
        }

        positionCard(targetEl) {
            if (!this.card) return;

            // On mobile screens <= 768px, CSS handles bottom-docking
            if (window.innerWidth <= 768) {
                return;
            }

            if (!targetEl) {
                // Center on screen
                this.card.style.top = '50%';
                this.card.style.left = '50%';
                this.card.style.transform = 'translate(-50%, -50%)';
                return;
            }

            this.card.style.transform = 'none';
            const rect = targetEl.getBoundingClientRect();
            const cardWidth = 380;
            const cardHeight = this.card.offsetHeight || 240;
            const margin = 16;

            let top = 0;
            let left = 0;

            // Preference 1: Below target
            if (rect.bottom + margin + cardHeight <= window.innerHeight) {
                top = rect.bottom + margin;
                left = Math.max(margin, Math.min(rect.left, window.innerWidth - cardWidth - margin));
            }
            // Preference 2: Above target
            else if (rect.top - margin - cardHeight >= 60) {
                top = rect.top - margin - cardHeight;
                left = Math.max(margin, Math.min(rect.left, window.innerWidth - cardWidth - margin));
            }
            // Preference 3: To the right
            else if (rect.right + margin + cardWidth <= window.innerWidth) {
                top = Math.max(margin + 60, Math.min(rect.top, window.innerHeight - cardHeight - margin));
                left = rect.right + margin;
            }
            // Preference 4: To the left
            else if (rect.left - margin - cardWidth >= margin) {
                top = Math.max(margin + 60, Math.min(rect.top, window.innerHeight - cardHeight - margin));
                left = rect.left - margin - cardWidth;
            }
            // Fallback: Safe bottom right
            else {
                top = window.innerHeight - cardHeight - margin;
                left = window.innerWidth - cardWidth - margin;
            }

            this.card.style.top = Math.max(60, top) + 'px';
            this.card.style.left = Math.max(margin, left) + 'px';
        }

        next() {
            if (this.currentStep < TOUR_STEPS.length - 1) {
                this.start(this.currentStep + 1);
            } else {
                this.finish();
            }
        }

        prev() {
            if (this.currentStep > 0) {
                this.start(this.currentStep - 1);
            }
        }

        stop() {
            sessionStorage.removeItem('rb48_tour_active');
            sessionStorage.removeItem('rb48_tour_step');
            localStorage.setItem('rb48_tour_completed', 'true');
            this.cleanup();
        }

        finish() {
            this.stop();
        }

        cleanup() {
            if (this.currentHighlighted) {
                this.currentHighlighted.classList.remove('rb48-tour-spotlight-active');
                this.currentHighlighted = null;
            }
            if (this.backdrop) {
                this.backdrop.classList.remove('active');
                setTimeout(() => {
                    if (this.backdrop) {
                        this.backdrop.remove();
                        this.backdrop = null;
                    }
                }, 250);
            }
            if (this.card) {
                this.card.remove();
                this.card = null;
            }
        }
    }

    // Expose global instance
    window.RB48Tour = new FeatureTourEngine();

    // Auto-init on DOMContentLoaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => window.RB48Tour.init());
    } else {
        window.RB48Tour.init();
    }
})();
