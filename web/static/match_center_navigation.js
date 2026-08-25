document.addEventListener('DOMContentLoaded', () => {
    const suggested = document.getElementById('suggested-teams');
    const generated = document.getElementById('generated-teams');
    const matchmaker = document.getElementById('matchmaker-details');
    if (!suggested || !generated) return;

    if (matchmaker) matchmaker.open = true;
    requestAnimationFrame(() => {
        setTimeout(() => suggested.scrollIntoView({ behavior: 'smooth', block: 'center' }), 60);
    });
});
