/**
 * EchoWeave — Admin UI JavaScript
 * Minimal JS for form validation and AJAX interactions.
 */

document.addEventListener('DOMContentLoaded', () => {
    // Highlight current nav link based on path
    const path = window.location.pathname;
    document.querySelectorAll('.nav-link').forEach(link => {
        if (link.getAttribute('href') === path) {
            link.classList.add('active');
        }
    });

    // Auto-dismiss action results after 10 seconds
    const observer = new MutationObserver(mutations => {
        mutations.forEach(mutation => {
            if (mutation.type === 'attributes' && mutation.attributeName === 'style') {
                const el = mutation.target;
                if (el.classList.contains('action-result') && el.style.display !== 'none') {
                    setTimeout(() => {
                        el.style.opacity = '0';
                        setTimeout(() => { el.style.display = 'none'; el.style.opacity = '1'; }, 300);
                    }, 10000);
                }
            }
        });
    });

    document.querySelectorAll('.action-result').forEach(el => {
        observer.observe(el, { attributes: true });
    });
});

/**
 * Generic POST helper for AJAX actions.
 */
async function postAction(url, body = {}) {
    const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    return resp.json();
}
