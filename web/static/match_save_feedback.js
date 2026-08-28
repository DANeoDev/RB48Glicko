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

    function showSuccess() {
        modal.style.display = 'flex';
        okButton.focus();
    }

    okButton.addEventListener('click', () => {
        // The normal POST would replace the page. Preserve the user's position
        // so acknowledging the success message does not throw them to the top.
        sessionStorage.setItem('rb48_match_center_restore_scroll', String(window.scrollY));
        window.location.reload();
    });

    const savedScroll = sessionStorage.getItem('rb48_match_center_restore_scroll');
    if (savedScroll !== null) {
        sessionStorage.removeItem('rb48_match_center_restore_scroll');
        requestAnimationFrame(() => {
            window.scrollTo(0, Number(savedScroll) || 0);
        });
    }

    form.addEventListener('submit', async event => {
        event.preventDefault();

        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }

        const submitButton = form.querySelector('button[type="submit"]');
        if (submitButton) submitButton.disabled = true;

        try {
            const response = await fetch(window.location.href, {
                method: 'POST',
                body: new FormData(form),
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });

            const html = await response.text();

            // The Match Center already renders a success notice after the
            // match has been processed. Only show our confirmation modal when
            // that successful server-side result is actually present.
            if (response.ok && /Saved\s+[^<]+and updated Glicko/.test(html)) {
                showSuccess();
                return;
            }

            // Keep the normal server-side validation/error behaviour visible.
            document.open();
            document.write(html);
            document.close();
        } catch (error) {
            console.error('Could not save match:', error);
            form.submit();
        } finally {
            if (submitButton) submitButton.disabled = false;
        }
    });
});
