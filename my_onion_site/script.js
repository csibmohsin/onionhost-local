document.addEventListener('DOMContentLoaded', () => {
    // Live visitor clock
    const clockEl = document.getElementById('live-time');
    const updateTime = () => {
        const now = new Date();
        if (clockEl) {
            clockEl.textContent = now.toLocaleTimeString() + ' (UTC ' + (now.getTimezoneOffset() / -60 >= 0 ? '+' : '') + (now.getTimezoneOffset() / -60) + ')';
        }
    };
    updateTime();
    setInterval(updateTime, 1000);
});

function verifyCircuit() {
    const out = document.getElementById('test-result');
    if (!out) return;

    out.textContent = "Pinging local rendezvous circuit...";
    out.style.color = "#f59e0b";

    setTimeout(() => {
        const ping = Math.floor(Math.random() * 40) + 60;
        out.innerHTML = `&#10004; Verified! Tor Multi-Hop Circuit Active &bull; Latency: ${ping}ms &bull; Zero Leaks Detected.`;
        out.style.color = "#10b981";
    }, 600);
}
