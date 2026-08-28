document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('match-form');
    if (!form) return;

    const modal = document.createElement('div');
    modal.className = 'modal-bg';
    modal.id = 'match-save-success-modal';
    modal.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="match-save-success-title">
            <h3 id="match-save-success-title">Match added successfully</h3>
            <div class="modal-actions">
                <button type="button" class="primary" id="match-save-success-ok">OK</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);

    const okButton = modal.querySelector('#match-save-success-ok');

    okButton.addEventListener('click', () => {
        sessionStorage.setItem('rb48_match_center_restore_scroll', String(window.scrollY));
        window.location.reload();
    });

    const savedScroll = sessionStorage.getItem('rb48_match_center_restore_scroll');
    if (savedScroll !== null) {
        sessionStorage.removeItem('rb48_match_center_restore_scroll');
        requestAnimationFrame(() => window.scrollTo(0, Number(savedScroll) || 0));
    }

    form.addEventListener('submit', async event => {
        const submitter = event.submitter;
        if (!submitter || submitter.name !== 'action' || submitter.value !== 'save') return;

        event.preventDefault();
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }

        const scrollY = window.scrollY;
        submitter.disabled = true;

        try {
            const response = await fetch(form.action || window.location.href, {
                method: 'POST',
                body: new FormData(form),
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(data.error || 'The match could not be saved.');
            }

            modal.style.display = 'flex';
            okButton.focus();
            sessionStorage.setItem('rb48_match_center_restore_scroll', String(scrollY));
        } catch (error) {
            console.error('Could not save match:', error);
            alert(error.message);
            submitter.disabled = false;
        }
    });
});
