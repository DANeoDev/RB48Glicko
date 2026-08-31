document.addEventListener('DOMContentLoaded', () => {
    const suggested = document.getElementById('suggested-teams');
    const generated = document.getElementById('generated-teams');
    const matchmaker = document.getElementById('matchmaker-details');
    const matchmakerForm = [...document.querySelectorAll('form')].find(form =>
        form.querySelector('button[name="action"][value="generate"]')
    );

    // Match Center actions are normal POST requests. Preserve the user's
    // position instead of making Generate Teams / Reroll jump the page.
    const scrollKey = 'rb48_match_center_matchmaker_scroll';

    if (matchmakerForm) {
        matchmakerForm.addEventListener('submit', event => {
            const submitter = event.submitter;
            if (!submitter || submitter.name !== 'action') return;
            if (!['generate', 'reroll'].includes(submitter.value)) return;

            sessionStorage.setItem(scrollKey, String(window.scrollY));
        });
    }

    const savedScroll = sessionStorage.getItem(scrollKey);
    if (savedScroll !== null) {
        sessionStorage.removeItem(scrollKey);
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                window.scrollTo(0, Number(savedScroll) || 0);
            });
        });
    }

    if (!suggested || !generated) return;

    if (matchmaker) matchmaker.open = true;

    // Do not scroll to the generated result automatically. The user stays
    // where they were; they can scroll to the result themselves.
});
