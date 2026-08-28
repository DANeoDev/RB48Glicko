document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('enter-match');
    if (!form) return;

    let savedScrollY = window.scrollY;

    function showModal(title, message, onOk) {
        const existing = document.getElementById('match-save-modal');
        if (existing) existing.remove();
        const modal = document.createElement('div');
        modal.id = 'match-save-modal';
        modal.className = 'modal-bg';
        modal.innerHTML = `<div class="modal"><h3>${title}</h3><p>${message}</p><div class="modal-actions"><button type="button" class="primary" id="match-save-modal-ok">OK</button></div></div>`;
        document.body.appendChild(modal);
        modal.style.display = 'flex';
        const ok = modal.querySelector('#match-save-modal-ok');
        ok.focus();
        ok.addEventListener('click', () => { modal.remove(); if (onOk) onOk(); });
    }

    form.addEventListener('submit', async (event) => {
        const submitter = event.submitter;
        if (!submitter || submitter.name !== 'action' || submitter.value !== 'save') return;
        event.preventDefault();
        savedScrollY = window.scrollY;
        submitter.disabled = true;
        try {
            const response = await fetch(form.action || window.location.href, {
                method: 'POST', body: new FormData(form),
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || 'The match could not be saved.');
            showModal('Match added successfully', '', () => {
                sessionStorage.setItem('rb48_match_center_scroll_y', String(savedScrollY));
                window.location.reload();
            });
        } catch (error) {
            showModal('Could not add match', error.message, () => { submitter.disabled = false; });
        }
    });

    const restoreScroll = sessionStorage.getItem('rb48_match_center_scroll_y');
    if (restoreScroll !== null) {
        sessionStorage.removeItem('rb48_match_center_scroll_y');
        const y = Number(restoreScroll);
        if (Number.isFinite(y)) requestAnimationFrame(() => window.scrollTo(0, y));
    }
});
