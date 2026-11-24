document.addEventListener('DOMContentLoaded', () => {
    // Live Clock
    const clockEl = document.getElementById('clock-display');
    const updateClock = () => {
        const now = new Date();
        if (clockEl) {
            clockEl.textContent = now.toLocaleTimeString() + ' (' + Intl.DateTimeFormat().resolvedOptions().timeZone + ')';
        }
    };
    updateClock();
    setInterval(updateClock, 1000);

    // Dynamic Host Text
    const hostEl = document.getElementById('local-server-text');
    if (hostEl && window.location.host) {
        hostEl.textContent = window.location.protocol + '//' + window.location.host;
    }
});

function testInteractive() {
    const out = document.getElementById('test-output');
    if (out) {
        out.textContent = "JavaScript execution and DOM rendering verified! Assets loaded cleanly.";
        out.style.opacity = '1';
        setTimeout(() => {
            out.style.transition = 'opacity 1s';
            out.style.opacity = '0.7';
        }, 3000);
    }
}

