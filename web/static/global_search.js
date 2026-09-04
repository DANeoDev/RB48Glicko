// Global Player Search with Ctrl+K shortcut
(function() {
    let players = [];
    const searchModal = document.getElementById("global-search-modal");
    const searchBackdrop = document.getElementById("global-search-backdrop");
    const searchInput = document.getElementById("global-search-input");
    const searchResults = document.getElementById("global-search-results");
    let selectedIndex = -1;

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

        const filtered = players
            .filter(p => !lower || p.name.toLowerCase().includes(lower))
            .slice(0, 10);

        if (filtered.length === 0) {
            const empty = document.createElement("div");
            empty.className = "search-empty";
            empty.textContent = "Keine passenden Spieler gefunden";
            searchResults.appendChild(empty);
            selectedIndex = -1;
            return;
        }

        filtered.forEach((p, idx) => {
            const item = document.createElement("a");
            item.className = "search-result-item" + (idx === 0 ? " selected" : "");
            item.href = `/player/${p.id}`;
            item.innerHTML = `
                <span class="search-item-name">⚽ ${p.name}</span>
                ${p.rating ? `<span class="search-item-rating">${Math.round(p.rating)} Rating</span>` : ''}
            `;
            searchResults.appendChild(item);
        });

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

    window.GlobalSearch = {
        open: openSearch,
        close: closeSearch
    };
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
