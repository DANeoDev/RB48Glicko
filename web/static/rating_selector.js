document.addEventListener('DOMContentLoaded', () => {
    const path = window.location.pathname;
    const isHistory = path === '/matches';
    const isMatchCenter = path === '/match-center';
    if (!isHistory && !isMatchCenter) return;

    const labels = { total: 'Total', box: 'BOX', hf: 'HF' };
    const params = new URLSearchParams(window.location.search);
    const current = labels[params.get('rating_type')?.toLowerCase()] ? params.get('rating_type').toLowerCase() : 'total';

    if (isHistory) {
        const history = document.querySelector('.match-history');
        if (!history) return;

        const wrapper = document.createElement('div');
        wrapper.style.cssText = 'display:flex;align-items:center;gap:10px;margin:22px 0 10px;';
        wrapper.title = 'Choose which Glicko rating type is shown for the recorded matches. The selected type is used for player ratings, team ratings, expected result and rating change.';
        wrapper.innerHTML = '<label style="font-weight:600;cursor:help;">Rating: <select id="history-rating-type" title="The selected rating type is used throughout the match history details."><option value="total">Total</option><option value="box">BOX</option><option value="hf">HF</option></select></label>';
        const select = wrapper.querySelector('select'); select.value = current;
        history.parentNode.insertBefore(wrapper, history.nextSibling);
        select.addEventListener('change', () => {
            const next = new URL(window.location.href);
            next.searchParams.set('rating_type', select.value);
            window.location.href = next.toString();
        });

        const descriptor = `Showing ${labels[current]} rating. Hover for an explanation.`;
        document.querySelectorAll('.match-player .player-rating').forEach(el => {
            el.title = descriptor;
            el.style.cursor = 'help';
        });
    }
});