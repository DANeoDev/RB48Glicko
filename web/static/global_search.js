// Global Universal Site & Player Search with Ctrl+K shortcut
(function() {
    let players = [];
    const searchModal = document.getElementById("global-search-modal");
    const searchBackdrop = document.getElementById("global-search-backdrop");
    const searchInput = document.getElementById("global-search-input");
    const searchResults = document.getElementById("global-search-results");
    let selectedIndex = -1;

    // Static site pages catalogue with minimum tier requirements
    const sitePages = [
        { name: "Dashboard", desc: "Startseite & RB48 Übersicht", url: "/dashboard", icon: "🏠", minTier: "visitor" },
        { name: "Statistiken / Leaderboard", desc: "Spieler-Rangliste, Formkurven & Details", url: "/stats", icon: "📊", minTier: "user" },
        { name: "Auszeichnungen & Meilensteine", desc: "Erfolge, Century Club & Rekorde", url: "/achievements", icon: "🏆", minTier: "visitor" },
        { name: "Spieltagsplaner (Planner)", desc: "Teilnahme eintragen & Spieltage planen", url: "/planner", icon: "📅", minTier: "visitor" },
        { name: "Kalender-Export (.ics)", desc: "Spielplan in privaten Kalender importieren", url: "/planner/export.ics", icon: "🗓️", minTier: "visitor" },
        { name: "Spielhistorie (Matches)", desc: "Alle absolvierten Spiele & Ergebnisse", url: "/matches", icon: "📋", minTier: "visitor" },
        { name: "Match Center", desc: "Spieleingabe & KI-Matchmaking", url: "/match-center", icon: "⚙️", minTier: "admin" },
        { name: "Modell-Analyse", desc: "Glicko-2 Kalibrierung & Brier Score", url: "/model-analysis", icon: "🔬", minTier: "glicko_user" },
        { name: "Profil & Einstellungen", desc: "Account, Spielerprofil & Passwörter", url: "/settings", icon: "⚙️", minTier: "user" },
        { name: "Glicko FAQ & Erklärungen", desc: "Wie funktioniert die Rating-Berechnung?", url: "/glicko-explainer", icon: "❓", minTier: "visitor" },
        { name: "Über RB48", desc: "Informationen zum Projekt", url: "/about", icon: "ℹ️", minTier: "visitor" },
    ];

    function getUserTier() {
        if (!window.RB48_USER) return "visitor";
        const role = window.RB48_USER.role || "user";
        if (role === "webmaster" || role === "admin") return "admin";
        if (window.RB48_USER.psychology_test_passed) return "glicko_user";
        return "user";
    }

    const tierHierarchy = {
        "visitor": 0,
        "user": 1,
        "glicko_user": 2,
        "admin": 3,
        "webmaster": 4
    };

    function canAccess(minTier) {
        const userTier = getUserTier();
        return (tierHierarchy[userTier] || 0) >= (tierHierarchy[minTier] || 0);
    }

    async function loadPlayers() {
        if (players.length > 0) return;
        try {
            const resp = await fetch("/api/players-list");
            if (resp.ok) {
                players = await resp.json();
            }
        } catch (e) {
            console.error("Failed to load players list", e);
        }
    }

    function openSearch() {
        if (!searchModal) return;
        loadPlayers();
        searchModal.classList.add("open");
        if (searchBackdrop) searchBackdrop.classList.add("open");
        document.body.style.overflow = "hidden";
        if (searchInput) {
            searchInput.value = "";
            renderResults("");
            setTimeout(() => searchInput.focus(), 50);
        }
    }

    function closeSearch() {
        if (!searchModal) return;
        searchModal.classList.remove("open");
        if (searchBackdrop) searchBackdrop.classList.remove("open");
        document.body.style.overflow = "";
        selectedIndex = -1;
    }

    function renderResults(query) {
        if (!searchResults) return;
        searchResults.innerHTML = "";
        const lower = query.toLowerCase().trim();

        // 1. Filter accessible pages
        const matchingPages = sitePages.filter(page => {
            if (!canAccess(page.minTier)) return false;
            if (!lower) return true;
            return page.name.toLowerCase().includes(lower) || page.desc.toLowerCase().includes(lower);
        }).slice(0, 5);

        // 2. Filter players
        const matchingPlayers = players.filter(p => {
            if (!lower) return true;
            return p.name.toLowerCase().includes(lower);
        }).slice(0, 8);

        if (matchingPages.length === 0 && matchingPlayers.length === 0) {
            const empty = document.createElement("div");
            empty.className = "search-empty";
            empty.textContent = "Keine passenden Seiten oder Spieler gefunden.";
            searchResults.appendChild(empty);
            selectedIndex = -1;
            return;
        }

        let itemIndex = 0;

        if (matchingPages.length > 0) {
            const groupHeader = document.createElement("div");
            groupHeader.className = "search-group-header";
            groupHeader.textContent = "Seiten & Funktionen";
            searchResults.appendChild(groupHeader);

            matchingPages.forEach(p => {
                const item = document.createElement("a");
                item.className = "search-result-item" + (itemIndex === 0 ? " selected" : "");
                item.href = p.url;
                item.innerHTML = `
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span>${p.icon}</span>
                        <div>
                            <div class="search-item-name">${p.name}</div>
                            <div style="font-size: 11px; color: var(--text-muted);">${p.desc}</div>
                        </div>
                    </div>
                    <span style="font-size: 11px; color: #80deea; opacity: 0.8;">↵</span>
                `;
                searchResults.appendChild(item);
                itemIndex++;
            });
        }

        if (matchingPlayers.length > 0) {
            const groupHeader = document.createElement("div");
            groupHeader.className = "search-group-header";
            groupHeader.textContent = "Spieler";
            searchResults.appendChild(groupHeader);

            matchingPlayers.forEach(p => {
                const item = document.createElement("a");
                item.className = "search-result-item" + (itemIndex === 0 ? " selected" : "");
                item.href = `/player/${p.id}`;
                item.innerHTML = `
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span>⚽</span>
                        <div class="search-item-name">${p.name}</div>
                    </div>
                    ${p.rating ? `<span class="search-item-rating">${Math.round(p.rating)} Rating</span>` : ''}
                `;
                searchResults.appendChild(item);
                itemIndex++;
            });
        }

        selectedIndex = 0;
    }

    if (searchInput) {
        searchInput.addEventListener("input", (e) => renderResults(e.target.value));
        searchInput.addEventListener("keydown", (e) => {
            const items = searchResults.querySelectorAll(".search-result-item");
            if (e.key === "ArrowDown") {
                e.preventDefault();
                if (items.length === 0) return;
                items[selectedIndex]?.classList.remove("selected");
                selectedIndex = (selectedIndex + 1) % items.length;
                items[selectedIndex]?.classList.add("selected");
                items[selectedIndex]?.scrollIntoView({ block: "nearest" });
            } else if (e.key === "ArrowUp") {
                e.preventDefault();
                if (items.length === 0) return;
                items[selectedIndex]?.classList.remove("selected");
                selectedIndex = (selectedIndex - 1 + items.length) % items.length;
                items[selectedIndex]?.classList.add("selected");
                items[selectedIndex]?.scrollIntoView({ block: "nearest" });
            } else if (e.key === "Enter") {
                e.preventDefault();
                if (items.length > 0 && items[selectedIndex]) {
                    items[selectedIndex].click();
                }
            } else if (e.key === "Escape") {
                closeSearch();
            }
        });
    }

    // Ctrl+K / Cmd+K listener
    document.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
            e.preventDefault();
            if (searchModal && searchModal.classList.contains("open")) {
                closeSearch();
            } else {
                openSearch();
            }
        }
    });

    window.GlobalPlayerSearch = {
        open: openSearch,
        close: closeSearch
    };
    window.GlobalSiteSearch = window.GlobalPlayerSearch;
    window.GlobalSearch = window.GlobalPlayerSearch;
})();

// Toast notification helper
window.showToast = function(message, duration = 2800) {
    let container = document.getElementById("toast-container");
    if (!container) {
        container = document.createElement("div");
        container.id = "toast-container";
        container.style.cssText = "position: fixed; bottom: 24px; right: 24px; z-index: 9999; display: flex; flex-direction: column; gap: 8px;";
        document.body.appendChild(container);
    }
    const toast = document.createElement("div");
    toast.style.cssText = "background: #1e1338; border: 1px solid #7B52C5; color: #80deea; padding: 10px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; box-shadow: 0 8px 24px rgba(0,0,0,0.6); transform: translateY(20px); opacity: 0; transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);";
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.transform = "translateY(0)";
        toast.style.opacity = "1";
    }, 10);
    setTimeout(() => {
        toast.style.transform = "translateY(20px)";
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 200);
    }, duration);
};
