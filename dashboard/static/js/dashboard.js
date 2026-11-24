/**
 * OnionHost Command & Control Center Front-End Controller.
 * SaaS Pro Light Theme Controller matching reference UI.
 * Handles live REST polling, multi-site hosting, in-browser file/code editing,
 * folder creation (mkdir), direct path registration, telemetry, and Tor Browser launching.
 */

let activeTab = 'sites';
let currentFileSiteId = null;
let currentSubpath = "";
let currentEditingPath = "";
let pendingDeletePath = "";
let logFilter = 'all';
let allLogsCache = { tor: [], app: [] };

document.addEventListener('DOMContentLoaded', () => {
    initUserProfile();
    initSidebarState();
    initDashboard();
    initLiveDatePill();
    // 3-second status polling
    setInterval(pollSystemStatus, 3000);
    // 4-second log polling if logs tab is active
    setInterval(pollLogsIfActive, 4000);
    // 30-second live date updater
    setInterval(initLiveDatePill, 30000);
});

// -------------------------------------------------------------------
// Sidebar Toggle & Persistent State
// -------------------------------------------------------------------
function toggleSidebar() {
    const layout = document.querySelector('.app-layout');
    if (!layout) return;
    layout.classList.toggle('sidebar-collapsed');
    const isCollapsed = layout.classList.contains('sidebar-collapsed');
    localStorage.setItem('onionhost_sidebar_collapsed', isCollapsed ? 'true' : 'false');
    
    const toggleBtn = document.getElementById('sidebar-toggle-btn');
    if (toggleBtn) toggleBtn.title = isCollapsed ? "Expand Sidebar" : "Collapse Sidebar";
}

function initSidebarState() {
    const saved = localStorage.getItem('onionhost_sidebar_collapsed');
    if (saved === 'true') {
        document.querySelector('.app-layout')?.classList.add('sidebar-collapsed');
    }
}

function initDashboard() {
    pollSystemStatus();
    loadSites();
    loadStats();
    pollLogs();
}

// -------------------------------------------------------------------
// Live Header Date & Time (Matching Reference Image)
// -------------------------------------------------------------------
function initLiveDatePill() {
    const pill = document.getElementById('date-pill-text');
    if (!pill) return;
    
    const now = new Date();
    const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    
    const dayName = days[now.getDay()];
    const dateNum = now.getDate();
    const monthName = months[now.getMonth()];
    const year = now.getFullYear();
    
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    
    // Timezone string
    let tz = 'IST';
    try {
        const parts = Intl.DateTimeFormat('en', { timeZoneName: 'short' }).formatToParts(now);
        const tzPart = parts.find(p => p.type === 'timeZoneName');
        if (tzPart) tz = tzPart.value;
    } catch (e) {}

    pill.innerHTML = `${dayName}, ${dateNum} ${monthName} ${year}<br><span style="color: var(--text-hint); font-size: 11px;">${hours}:${minutes} ${tz}</span>`;
}

// -------------------------------------------------------------------
// User Profile Management (Bottom-Left Clickable & Persistent)
// -------------------------------------------------------------------
function initUserProfile() {
    const username = localStorage.getItem('onionhost_username') || "Mohsin Khawaja";
    const userRole = localStorage.getItem('onionhost_userrole') || "Administrator";
    
    // Compute Initials (e.g. "Mohsin Khawaja" -> "MK", "Mohsin" -> "MM")
    const words = username.trim().split(/\s+/).filter(w => w.length > 0);
    let initials = "MK";
    if (words.length >= 2) {
        initials = (words[0][0] + words[1][0]).toUpperCase();
    } else if (words.length === 1 && words[0].length >= 2) {
        initials = words[0].slice(0, 2).toUpperCase();
    }

    const avatarEl = document.getElementById('profile-avatar');
    const nameEl = document.getElementById('profile-name-display');
    const roleEl = document.getElementById('profile-role-display');
    const welcomeEl = document.getElementById('welcome-title-text');

    if (avatarEl) avatarEl.textContent = initials;
    if (nameEl) nameEl.textContent = username;
    if (roleEl) roleEl.textContent = userRole;
    if (welcomeEl) welcomeEl.textContent = `Welcome back, ${username}`;

    // Modal sync
    const modalAvatar = document.getElementById('modal-profile-avatar');
    const modalName = document.getElementById('modal-profile-name-text');
    const modalRole = document.getElementById('modal-profile-role-text');
    if (modalAvatar) modalAvatar.textContent = initials;
    if (modalName) modalName.textContent = username;
    if (modalRole) modalRole.textContent = userRole;
}

function openProfileModal() {
    const currentName = localStorage.getItem('onionhost_username') || "Mohsin Khawaja";
    const currentRole = localStorage.getItem('onionhost_userrole') || "Administrator";
    const inputName = document.getElementById('input-profile-name');
    const inputRole = document.getElementById('input-profile-role');
    if (inputName) inputName.value = currentName;
    if (inputRole) inputRole.value = currentRole;
    document.getElementById('profile-modal').style.display = 'flex';
}

function closeProfileModal() {
    document.getElementById('profile-modal').style.display = 'none';
}

function saveUserProfile() {
    const inputName = document.getElementById('input-profile-name');
    const inputRole = document.getElementById('input-profile-role');
    const newName = inputName ? inputName.value.trim() : "Mohsin Khawaja";
    const newRole = inputRole ? inputRole.value.trim() : "Administrator";

    if (!newName) {
        showToast("Please enter a valid user name.", "error");
        return;
    }

    localStorage.setItem('onionhost_username', newName);
    localStorage.setItem('onionhost_userrole', newRole);
    initUserProfile();
    closeProfileModal();
    showToast(`User profile updated: ${newName}`, "success");
}

// -------------------------------------------------------------------
// About Modal (Developer: Mohsin Khawaja)
// -------------------------------------------------------------------
function openAboutModal() {
    document.getElementById('about-modal').style.display = 'flex';
}

function closeAboutModal() {
    document.getElementById('about-modal').style.display = 'none';
}

// -------------------------------------------------------------------
// System Status & KPIs
// -------------------------------------------------------------------
async function pollSystemStatus() {
    try {
        const resp = await fetch('/api/status');
        const json = await resp.json();
        if (json.success && json.data) {
            updateHeaderStatus(json.data);
            updateKPIs(json.data);
        }
    } catch (e) {
        console.warn("Status poll error:", e);
    }
}

function updateHeaderStatus(data) {
    const dot = document.getElementById('tor-dot');
    const text = document.getElementById('tor-status-text');
    const pct = document.getElementById('tor-pct');

    const percent = data.bootstrap_percent || 0;
    if (pct) pct.textContent = `${percent}%`;

    if (data.tor_running && percent >= 100) {
        if (dot) dot.className = 'status-dot dot-green';
        if (text) text.textContent = 'Tor: Connected & Routing';
    } else if (data.tor_running) {
        if (dot) dot.className = 'status-dot dot-amber';
        if (text) text.textContent = `Tor: Bootstrapping (${percent}%)`;
    } else {
        if (dot) dot.className = 'status-dot dot-gray';
        if (text) text.textContent = 'Tor: Stopped';
    }

    const uptimeEl = document.getElementById('kpi-uptime');
    if (uptimeEl) uptimeEl.textContent = formatSeconds(data.uptime_seconds || 0);
}

function updateKPIs(data) {
    const activeCount = data.active_sites_count || 0;
    const sites = data.sites || [];
    const totalCount = sites.length;

    const activeEl = document.getElementById('kpi-active-sites');
    const totalEl = document.getElementById('kpi-total-sites');
    if (activeEl) activeEl.textContent = activeCount;
    if (totalEl) totalEl.textContent = totalCount;

    updateMultiSiteButton(sites, activeCount);
}

function updateMultiSiteButton(sites, activeCount) {
    const btnText = document.getElementById('quick-action-multi-text');
    if (!btnText) return;

    if (activeCount > 1) {
        btnText.textContent = `${activeCount} Sites Active Simultaneously`;
    } else if (sites.length >= 2) {
        btnText.textContent = `Launch ${sites.length} Sites Simultaneously`;
    } else {
        btnText.textContent = `Launch Multiple Sites Simultaneously`;
    }
}

// -------------------------------------------------------------------
// Dynamic Multi-Site Hosting (Handles 2, 3, 4, 5+ Sites Dynamically)
// -------------------------------------------------------------------
async function launchMultipleSites() {
    try {
        const resp = await fetch('/api/sites');
        const json = await resp.json();
        const sites = json.sites || [];
        const activeCount = sites.filter(s => s.is_active).length;
        updateMultiSiteButton(sites, activeCount);

        let sitesToLaunch = [];
        if (sites.length >= 2) {
            // Use all registered sites dynamically (e.g. 2, 3, 4, 5 sites)
            sitesToLaunch = sites.map((s, idx) => ({
                folder_path: s.path,
                port: s.local_port || (8080 + idx)
            }));
        } else {
            // Fallback default sample multi-sites
            sitesToLaunch = [
                { folder_path: "my_onion_site", port: 8080 },
                { folder_path: "sample_website", port: 8088 }
            ];
        }

        const count = sitesToLaunch.length;
        showToast(`Launching ${count} Sites Simultaneously over Tor...`, "info");

        const startResp = await fetch('/api/sites/start_multiple', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sites: sitesToLaunch })
        });
        const res = await startResp.json();
        if (res.success) {
            showToast(`Success! All ${count} sites are now active simultaneously!`, "success");
            loadSites();
            pollSystemStatus();
        } else {
            showToast("Failed: " + (res.error || "Unknown error"), "error");
        }
    } catch (e) {
        showToast("Error launching multiple sites.", "error");
    }
}

// Keep backward compatibility alias
const launchDualSitesDemo = launchMultipleSites;

// -------------------------------------------------------------------
// Sites Management (Modern SaaS Table View)
// -------------------------------------------------------------------
async function loadSites() {
    const grid = document.getElementById('sites-grid');
    const select = document.getElementById('fm-site-select');

    try {
        const resp = await fetch('/api/sites');
        const json = await resp.json();
        const sites = json.sites || [];
        const activeCount = sites.filter(s => s.is_active).length;
        updateMultiSiteButton(sites, activeCount);

        // Update File Manager Site Select
        if (select) {
            const prevSelected = select.value;
            select.innerHTML = '';
            if (sites.length === 0) {
                select.innerHTML = '<option value="">-- No sites registered --</option>';
            } else {
                sites.forEach(s => {
                    const opt = document.createElement('option');
                    opt.value = s.id;
                    opt.textContent = `${s.name} (${s.id})`;
                    select.appendChild(opt);
                });
                if (prevSelected && sites.some(s => s.id === prevSelected)) {
                    select.value = prevSelected;
                } else if (!currentFileSiteId && sites.length > 0) {
                    currentFileSiteId = sites[0].id;
                    select.value = currentFileSiteId;
                    loadFilesForCurrentSite();
                }
            }
        }

        // Render Table Matching Reference Image
        if (sites.length === 0) {
            grid.innerHTML = `
                <div class="table-card-container" style="padding: 48px; text-align: center;">
                    <p style="font-size: 15px; font-weight: 700; color: #475569; margin-bottom: 6px;">No Active Onion Websites Hosted</p>
                    <p class="text-muted" style="font-size: 13px; margin-bottom: 20px;">
                        Create a new app or host any Windows folder path to publish your first .onion site.
                    </p>
                    <button class="btn btn-primary" onclick="openCreateAppModal()">+ Create Website App</button>
                </div>
            `;
            return;
        }

        let tableHtml = `
            <div class="table-card-container">
                <table class="saas-table">
                    <thead>
                        <tr>
                            <th style="width: 36px; text-align: center;">#</th>
                            <th>Name</th>
                            <th>Onion URL</th>
                            <th style="text-align: center; width: 60px;">Local</th>
                            <th style="text-align: center; width: 65px;">Requests</th>
                            <th style="text-align: center; width: 85px;">Transfer</th>
                            <th style="width: 130px;">Status</th>
                            <th style="text-align: right; width: 120px;">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
        `;

        sites.forEach((s, index) => {
            const isRunning = s.is_active;
            const isProxy = s.is_proxy || (s.path && (s.path.startsWith('http://') || s.path.startsWith('https://')));
            const sub = s.subpath || '';
            const displayOnionText = s.onion_address ? `${s.onion_address}${sub}` : 'Generating address...';
            const fullOnionLink = s.onion_address ? `http://${s.onion_address}${sub}` : '';
            const localUrl = (s.path && s.path.startsWith('http')) ? s.path : `http://127.0.0.1:${s.local_port}${sub}`;
            const rowNumber = String(index + 1).padStart(2, '0');

            tableHtml += `
                <tr>
                    <td style="font-family: var(--font-mono); font-size: 12px; color: var(--text-hint); font-weight: 600; text-align: center;">${rowNumber}</td>
                    <td>
                        <div class="site-name-cell">
                            <div class="folder-icon-box" style="${isProxy ? 'background: #eff6ff; color: #2563eb;' : ''}">
                                ${isProxy 
                                    ? `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>`
                                    : `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`
                                }
                            </div>
                            <div class="site-title-column">
                                <div style="display: flex; align-items: center;">
                                    <span class="site-main-title">${escapeHtml(s.name)}</span>
                                    ${isProxy ? '<span style="font-size: 9.5px; background: #eff6ff; color: #2563eb; border: 1px solid #bfdbfe; padding: 1px 5px; border-radius: 4px; font-weight: 700; margin-left: 6px;">TOR MIRROR</span>' : ''}
                                </div>
                                <span class="site-path-sub" title="${escapeHtml(s.path)}">${isProxy ? 'Mirroring: ' + escapeHtml(s.path) : escapeHtml(s.path)}</span>
                            </div>
                        </div>
                    </td>
                    <td>
                        <div class="onion-address-cell">
                            ${s.onion_address ? `
                                <a href="${fullOnionLink}" target="_blank" class="onion-address-link" title="Open in Tor Browser: ${fullOnionLink}">${fullOnionLink}</a>
                                <button class="copy-mini-btn" onclick="copyToClipboard('${fullOnionLink}')" title="Copy Onion URL">
                                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                                </button>
                            ` : `<span class="text-muted" style="font-size: 12px;">${displayOnionText}</span>`}
                        </div>
                    </td>
                    <td style="text-align: center;">
                        <a href="${localUrl}" target="_blank" class="local-icon-pill" title="Click to visit local binding: ${localUrl}">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                        </a>
                    </td>
                    <td style="font-weight: 600; text-align: center;">${s.stats ? s.stats.total_requests : 0}</td>
                    <td style="font-weight: 500; text-align: center;">${s.stats ? s.stats.total_bytes_formatted : '0 B'}</td>
                    <td>
                        <div class="status-cell-wrapper">
                            ${isRunning 
                                ? `<span class="kpi-badge-green"><span class="status-dot dot-green"></span> Running</span>
                                   <button class="btn-table-state stop" onclick="stopSite('${s.id}')" title="Stop ${escapeHtml(s.name)}">
                                       <svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="2"/></svg>
                                       <span>Stop</span>
                                   </button>`
                                : `<span style="background: #f1f5f9; color: #64748b; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 9999px; display: inline-flex; align-items: center; gap: 4px;"><span class="status-dot dot-gray"></span> Stopped</span>
                                   <button class="btn-table-state start" onclick="startExistingSite('${s.id}')" title="Start ${escapeHtml(s.name)}">
                                       <svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20 6 4"/></svg>
                                       <span>Start</span>
                                   </button>`
                            }
                        </div>
                    </td>
                    <td>
                        <div class="table-actions-cell">
                            ${isRunning
                                ? `<button class="action-icon-btn stop-btn" onclick="stopSite('${s.id}')" title="Stop Hosting ${escapeHtml(s.name)}">
                                       <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="2"/></svg>
                                   </button>
                                   <button class="action-icon-btn" onclick="restartSite('${s.id}')" title="Restart Service">
                                       <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
                                   </button>`
                                : `<button class="action-icon-btn start-btn" onclick="startExistingSite('${s.id}')" title="Start Hosting ${escapeHtml(s.name)}">
                                       <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20 6 4"/></svg>
                                   </button>`
                            }
                            ${s.onion_address ? `
                                <button class="action-icon-btn" onclick="openInTorBrowser('${s.id}')" title="Open in Tor Browser">
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                                </button>
                            ` : ''}
                            <button class="action-icon-btn" onclick="openFileManagerForSite('${s.id}')" title="Browse Files">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                            </button>
                            <button class="action-icon-btn" onclick="openCodeEditorForSiteRoot('${s.id}')" title="Code Editor">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                            </button>
                            <button class="action-icon-btn delete" onclick="deleteSiteRegistration('${s.id}')" title="Delete / Unregister">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        });

        tableHtml += `
                    </tbody>
                </table>
            </div>
        `;

        grid.innerHTML = tableHtml;
    } catch (e) {
        console.error("Error loading sites:", e);
    }
}

async function submitQuickHost() {
    const folderInput = document.getElementById('quick-folder-input');
    const portInput = document.getElementById('quick-port-input');
    const inputVal = folderInput.value.trim();
    const port = portInput.value.trim();

    if (!inputVal) {
        showToast("Please enter a direct website folder path or URL.", "error");
        return;
    }

    // Check if input is a live website URL (e.g. www.csib.co.in or https://...)
    const isUrl = inputVal.startsWith("http://") || inputVal.startsWith("https://") || inputVal.startsWith("www.") || [".com", ".in", ".org", ".net", ".io", ".co"].some(tld => inputVal.includes(tld));

    if (isUrl) {
        showToast("Creating live Tor Onion Mirror for " + inputVal + "...", "info");
        try {
            const resp = await fetch('/api/sites/host_url', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: inputVal, port: port || 8090 })
            });
            const res = await resp.json();
            if (res.success) {
                showToast("Tor Onion Mirror online: " + res.site.onion_address, "success");
                folderInput.value = "";
                loadSites();
                pollSystemStatus();
            } else {
                showToast("Failed: " + res.error, "error");
            }
        } catch (e) {
            showToast("Error connecting to backend.", "error");
        }
        return;
    }

    showToast("Initializing OnionHost for " + inputVal + "...", "info");

    try {
        const resp = await fetch('/api/sites/host', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder_path: inputVal, port: port || 8080 })
        });
        const res = await resp.json();
        if (res.success) {
            showToast("Website online at: " + res.site.onion_address, "success");
            folderInput.value = "";
            loadSites();
            pollSystemStatus();
        } else {
            showToast("Failed: " + res.error, "error");
        }
    } catch (e) {
        showToast("Error connecting to C2 backend.", "error");
    }
}

// -------------------------------------------------------------------
// Live Website URL Tor Mirror Modal
// -------------------------------------------------------------------
function openHostUrlModal() {
    document.getElementById('host-url-modal').style.display = 'flex';
}

function closeHostUrlModal() {
    document.getElementById('host-url-modal').style.display = 'none';
}

async function submitHostUrl() {
    const urlInput = document.getElementById('url-mirror-target');
    const nameInput = document.getElementById('url-mirror-name');
    const portInput = document.getElementById('url-mirror-port');

    const url = urlInput.value.trim();
    const name = nameInput.value.trim();
    const port = portInput.value.trim();

    if (!url) {
        showToast("Please enter a target website URL.", "error");
        return;
    }

    closeHostUrlModal();
    showToast(`Launching Tor Onion Mirror for ${url}...`, "info");

    try {
        const resp = await fetch('/api/sites/host_url', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: url,
                name: name,
                port: port || 8090
            })
        });
        const res = await resp.json();
        if (res.success) {
            showToast(`Tor Mirror Live: ${res.site.onion_address}`, "success");
            loadSites();
            pollSystemStatus();
        } else {
            showToast("Failed: " + res.error, "error");
        }
    } catch (e) {
        showToast("Error connecting to backend.", "error");
    }
}

async function openInTorBrowser(siteId) {
    showToast("Launching Tor Browser...", "info");
    try {
        const resp = await fetch(`/api/sites/${siteId}/open_tor`, { method: 'POST' });
        const res = await resp.json();
        if (res.success) {
            showToast(res.message, "success");
        } else {
            showToast(res.error, "error");
        }
    } catch (e) {
        showToast("Failed to launch Tor Browser", "error");
    }
}

async function startExistingSite(siteId) {
    showToast("Starting site " + siteId + "...", "info");
    try {
        const resp = await fetch(`/api/sites/${siteId}/restart`, { method: 'POST' });
        const res = await resp.json();
        if (res.success) {
            showToast("Site online: " + res.site.onion_address, "success");
            loadSites();
            pollSystemStatus();
        } else {
            showToast("Failed: " + res.error, "error");
        }
    } catch (e) {
        showToast("Request failed", "error");
    }
}

async function stopSite(siteId) {
    try {
        const resp = await fetch(`/api/sites/${siteId}/stop`, { method: 'POST' });
        const res = await resp.json();
        if (res.success) {
            showToast(res.message, "success");
            loadSites();
            pollSystemStatus();
        }
    } catch (e) {
        showToast("Failed to stop site", "error");
    }
}

async function restartSite(siteId) {
    showToast("Restarting site...", "info");
    startExistingSite(siteId);
}

async function stopAllHosting() {
    if (!confirm("Are you sure you want to stop all active OnionHost services?")) return;
    try {
        const resp = await fetch('/api/stop_all', { method: 'POST' });
        const res = await resp.json();
        showToast(res.message, "success");
        loadSites();
        pollSystemStatus();
    } catch (e) {
        showToast("Error stopping services", "error");
    }
}

async function deleteSiteRegistration(siteId) {
    if (!confirm(`Unregister site '${siteId}'? (Your files and onion keys will NOT be deleted).`)) return;
    try {
        const resp = await fetch(`/api/sites/${siteId}`, { method: 'DELETE' });
        const res = await resp.json();
        if (res.success) {
            showToast(res.message, "success");
            loadSites();
            pollSystemStatus();
        }
    } catch (e) {
        showToast("Error unregistering site", "error");
    }
}

// -------------------------------------------------------------------
// File Management & In-Browser Code Editor
// -------------------------------------------------------------------
function openFileManagerForSite(siteId) {
    currentFileSiteId = siteId;
    currentSubpath = "";
    const select = document.getElementById('fm-site-select');
    if (select) select.value = siteId;
    switchTab('files');
    loadFilesForCurrentSite();
}

async function openCodeEditorForSiteRoot(siteId) {
    currentFileSiteId = siteId;
    currentSubpath = "";
    const select = document.getElementById('fm-site-select');
    if (select) select.value = siteId;
    
    try {
        const resp = await fetch(`/api/sites/${siteId}/files?path=`);
        const json = await resp.json();
        if (json.success && json.files && json.files.length > 0) {
            const htmlFile = json.files.find(f => !f.is_dir && f.name.toLowerCase().endsWith('.html')) || json.files.find(f => !f.is_dir);
            if (htmlFile) {
                openCodeEditor(htmlFile.path, htmlFile.name);
                return;
            }
        }
    } catch (e) {}

    // Fallback: switch to file manager
    openFileManagerForSite(siteId);
}

function onFileSiteChanged() {
    currentFileSiteId = document.getElementById('fm-site-select').value;
    currentSubpath = "";
    loadFilesForCurrentSite();
}

async function loadFilesForCurrentSite() {
    if (!currentFileSiteId) return;

    const tbody = document.getElementById('fm-files-tbody');
    updateBreadcrumbs();

    try {
        const resp = await fetch(`/api/sites/${currentFileSiteId}/files?path=${encodeURIComponent(currentSubpath)}`);
        const json = await resp.json();
        if (!json.success) {
            tbody.innerHTML = `<tr><td colspan="4" class="text-center text-danger">${escapeHtml(json.error)}</td></tr>`;
            return;
        }

        const files = json.files || [];
        if (files.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" class="text-center text-muted">Folder is empty. Click "+ Upload Files" or "+ New Folder" above.</td></tr>`;
            return;
        }

        let html = '';
        if (currentSubpath) {
            html += `
                <tr>
                    <td colspan="4">
                        <div class="file-row-name is-folder" onclick="navigateParentFolder()">
                            &#128193; <strong>.. (Parent Directory)</strong>
                        </div>
                    </td>
                </tr>
            `;
        }

        files.forEach(f => {
            const icon = f.is_dir ? '&#128193;' : '&#128196;';
            const action = f.is_dir 
                ? `onclick="navigateSubfolder('${escapeHtml(f.name)}')"` 
                : `onclick="openCodeEditor('${escapeHtml(f.path)}', '${escapeHtml(f.name)}')"` ;
            
            const isEditable = !f.is_dir && isEditableFile(f.name);

            html += `
                <tr>
                    <td>
                        <div class="file-row-name ${f.is_dir ? 'is-folder' : ''}" ${action} style="cursor: pointer;">
                            <span>${icon}</span>
                            <span>${escapeHtml(f.name)}</span>
                            ${isEditable ? '<span class="file-badge-code">Edit</span>' : ''}
                        </div>
                    </td>
                    <td>${f.size_formatted}</td>
                    <td>${formatDate(f.modified)}</td>
                    <td style="text-align: right; display: flex; justify-content: flex-end; gap: 6px;">
                        ${isEditable ? `<button class="btn btn-sm btn-secondary" onclick="openCodeEditor('${escapeHtml(f.path)}', '${escapeHtml(f.name)}')">&#9998; Edit</button>` : ''}
                        <button class="btn btn-sm btn-danger" onclick="promptDeleteFile('${escapeHtml(f.path)}', '${escapeHtml(f.name)}')">Delete</button>
                    </td>
                </tr>
            `;
        });

        tbody.innerHTML = html;
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="4" class="text-center text-danger">Failed to load files.</td></tr>`;
    }
}

function isEditableFile(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    return ['html', 'htm', 'css', 'js', 'json', 'txt', 'md', 'xml', 'svg'].includes(ext);
}

function updateBreadcrumbs() {
    const bc = document.getElementById('fm-breadcrumbs');
    const parts = currentSubpath.split('/').filter(p => p.length > 0);
    let html = `<span class="crumb ${parts.length === 0 ? 'active' : ''}" onclick="navigateToCrumb(-1)">/ (root)</span>`;

    let accumulated = '';
    parts.forEach((p, idx) => {
        accumulated += (accumulated ? '/' : '') + p;
        const isLast = idx === parts.length - 1;
        html += ` / <span class="crumb ${isLast ? 'active' : ''}" onclick="navigateToCrumb(${idx})">${escapeHtml(p)}</span>`;
    });

    bc.innerHTML = html;
}

function navigateSubfolder(folderName) {
    currentSubpath = currentSubpath ? `${currentSubpath}/${folderName}` : folderName;
    loadFilesForCurrentSite();
}

function navigateParentFolder() {
    const parts = currentSubpath.split('/').filter(p => p.length > 0);
    parts.pop();
    currentSubpath = parts.join('/');
    loadFilesForCurrentSite();
}

function navigateToCrumb(index) {
    if (index === -1) {
        currentSubpath = "";
    } else {
        const parts = currentSubpath.split('/').filter(p => p.length > 0);
        currentSubpath = parts.slice(0, index + 1).join('/');
    }
    loadFilesForCurrentSite();
}

// -------------------------------------------------------------------
// In-Browser Code / HTML Editor
// -------------------------------------------------------------------
async function openCodeEditor(relPath, fileName) {
    if (!currentFileSiteId) return;

    currentEditingPath = relPath;
    document.getElementById('editor-file-title').textContent = `Editing: ${fileName}`;
    document.getElementById('editor-file-path').textContent = `Path: ${relPath}`;
    document.getElementById('editor-status').textContent = "Loading file...";
    document.getElementById('code-editor-modal').style.display = 'flex';

    try {
        const resp = await fetch(`/api/sites/${currentFileSiteId}/file_content?path=${encodeURIComponent(relPath)}`);
        const json = await resp.json();
        if (json.success) {
            document.getElementById('code-editor-textarea').value = json.content;
            document.getElementById('editor-status').textContent = "Ready";
        } else {
            document.getElementById('editor-status').textContent = "Error: " + json.error;
        }
    } catch (e) {
        document.getElementById('editor-status').textContent = "Failed to load content";
    }
}

function closeCodeEditorModal() {
    document.getElementById('code-editor-modal').style.display = 'none';
    currentEditingPath = "";
}

async function saveCodeEditorContent() {
    if (!currentFileSiteId || !currentEditingPath) return;

    const content = document.getElementById('code-editor-textarea').value;
    document.getElementById('editor-status').textContent = "Saving...";

    try {
        const resp = await fetch(`/api/sites/${currentFileSiteId}/save_file`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: currentEditingPath, content: content })
        });
        const json = await resp.json();
        if (json.success) {
            document.getElementById('editor-status').textContent = "Saved successfully!";
            showToast("File saved! Live updates applied to Tor site.", "success");
            setTimeout(closeCodeEditorModal, 500);
            loadFilesForCurrentSite();
        } else {
            document.getElementById('editor-status').textContent = "Error: " + json.error;
            showToast("Save failed: " + json.error, "error");
        }
    } catch (e) {
        document.getElementById('editor-status').textContent = "Save request failed";
    }
}

// -------------------------------------------------------------------
// Folder & File Creation Modals
// -------------------------------------------------------------------
function openNewFolderModal() {
    const select = document.getElementById('fm-site-select');
    currentFileSiteId = currentFileSiteId || (select ? select.value : null);
    if (!currentFileSiteId) {
        showToast("Please select or create a website first.", "error");
        return;
    }
    document.getElementById('new-folder-name').value = '';
    document.getElementById('new-folder-modal').style.display = 'flex';
}

function closeNewFolderModal() {
    document.getElementById('new-folder-modal').style.display = 'none';
}

async function submitNewFolder() {
    const folderName = document.getElementById('new-folder-name').value.trim();
    const select = document.getElementById('fm-site-select');
    currentFileSiteId = currentFileSiteId || (select ? select.value : null);

    if (!currentFileSiteId) {
        showToast("Please select a website first.", "error");
        return;
    }
    if (!folderName) {
        showToast("Folder name cannot be empty.", "error");
        return;
    }

    closeNewFolderModal();
    showToast(`Creating folder '${folderName}'...`, "info");

    try {
        const resp = await fetch(`/api/sites/${currentFileSiteId}/mkdir`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: currentSubpath, folder_name: folderName })
        });
        const json = await resp.json();
        if (json.success) {
            showToast(json.message, "success");
            loadFilesForCurrentSite();
        } else {
            showToast("Failed: " + json.error, "error");
        }
    } catch (e) {
        showToast("Error creating folder.", "error");
    }
}

function openNewFileModal() {
    document.getElementById('new-file-name').value = 'page.html';
    document.getElementById('new-file-modal').style.display = 'flex';
}

function closeNewFileModal() {
    document.getElementById('new-file-modal').style.display = 'none';
}

async function submitNewFile() {
    const fileName = document.getElementById('new-file-name').value.trim();
    if (!fileName || !currentFileSiteId) return;

    closeNewFileModal();
    const starterHtml = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>${escapeHtml(fileName)}</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <h1>${escapeHtml(fileName)}</h1>
    <p>Welcome to your new page hosted over Tor!</p>
</body>
</html>`;

    const filePath = currentSubpath ? `${currentSubpath}/${fileName}` : fileName;

    try {
        const resp = await fetch(`/api/sites/${currentFileSiteId}/save_file`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: filePath, content: starterHtml })
        });
        const json = await resp.json();
        if (json.success) {
            showToast(`Created ${fileName}!`, "success");
            loadFilesForCurrentSite();
            openCodeEditor(filePath, fileName);
        } else {
            showToast("Failed: " + json.error, "error");
        }
    } catch (e) {
        showToast("Error creating file.", "error");
    }
}

// -------------------------------------------------------------------
// Host Localhost Port Modal (XAMPP / Apache / Node / etc.)
// -------------------------------------------------------------------
function openHostPortModal() {
    document.getElementById('host-port-modal').style.display = 'flex';
}

function closeHostPortModal() {
    document.getElementById('host-port-modal').style.display = 'none';
}

async function submitHostPort() {
    const name = document.getElementById('port-service-name').value.trim() || 'AnonChat';
    const port = document.getElementById('port-number-input').value.trim() || '80';
    const subpath = document.getElementById('port-subpath-input').value.trim();

    closeHostPortModal();
    showToast(`Binding localhost:${port} to new Tor Onion Service...`, "info");

    try {
        const resp = await fetch('/api/sites/host_port', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                port: port,
                subpath: subpath
            })
        });
        const json = await resp.json();
        if (json.success) {
            showToast("Localhost is now LIVE on Tor!", "success");
            loadSites();
            pollSystemStatus();
        } else {
            showToast("Failed: " + json.error, "error");
        }
    } catch (e) {
        showToast("Error connecting to C2 backend.", "error");
    }
}

// -------------------------------------------------------------------
// Create App Modal
// -------------------------------------------------------------------
function openCreateAppModal() {
    document.getElementById('create-app-modal').style.display = 'flex';
}

function closeCreateAppModal() {
    document.getElementById('create-app-modal').style.display = 'none';
}

async function submitCreateApp() {
    const name = document.getElementById('app-name-input').value.trim();
    const customPath = document.getElementById('app-path-input').value.trim();
    const port = document.getElementById('app-port-input').value.trim();
    const autoStart = document.getElementById('app-autostart-input').checked;

    if (!name) {
        showToast("Please enter an application / website name.", "error");
        return;
    }

    closeCreateAppModal();
    showToast(`Creating website '${name}'...`, "info");

    try {
        const resp = await fetch('/api/sites/create_new', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                custom_path: customPath || null,
                port: port || null,
                auto_start: autoStart
            })
        });
        const json = await resp.json();
        if (json.success) {
            showToast(json.message, "success");
            loadSites();
            pollSystemStatus();
        } else {
            showToast("Error: " + json.error, "error");
        }
    } catch (e) {
        showToast("Error creating website application.", "error");
    }
}

// -------------------------------------------------------------------
// Upload & Delete
// -------------------------------------------------------------------
async function handleFileUpload(event) {
    const files = event.target.files;
    if (!files || files.length === 0 || !currentFileSiteId) return;

    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const formData = new FormData();
        formData.append('file', file);
        formData.append('path', currentSubpath);

        showToast(`Uploading ${file.name}...`, "info");

        try {
            const resp = await fetch(`/api/sites/${currentFileSiteId}/upload`, {
                method: 'POST',
                body: formData
            });
            const json = await resp.json();
            if (json.success) {
                showToast(json.message, "success");
            } else {
                showToast("Upload failed: " + json.error, "error");
            }
        } catch (e) {
            showToast("Error uploading " + file.name, "error");
        }
    }

    loadFilesForCurrentSite();
    event.target.value = "";
}

function promptDeleteFile(relPath, fileName) {
    pendingDeletePath = relPath;
    document.getElementById('delete-file-name').textContent = fileName;
    document.getElementById('delete-file-modal').style.display = 'flex';
}

function closeDeleteModal() {
    document.getElementById('delete-file-modal').style.display = 'none';
    pendingDeletePath = "";
}

async function confirmDeleteFile() {
    if (!pendingDeletePath || !currentFileSiteId) return;

    try {
        const resp = await fetch(`/api/sites/${currentFileSiteId}/delete_file`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: pendingDeletePath })
        });
        const json = await resp.json();
        if (json.success) {
            showToast(json.message, "success");
            closeDeleteModal();
            loadFilesForCurrentSite();
        } else {
            showToast("Deletion failed: " + json.error, "error");
        }
    } catch (e) {
        showToast("Error deleting item.", "error");
    }
}

// -------------------------------------------------------------------
// Traffic & Statistics
// -------------------------------------------------------------------
async function loadStats() {
    try {
        const resp = await fetch('/api/stats');
        const json = await resp.json();
        if (json.success) {
            const reqEl = document.getElementById('kpi-requests');
            const bytesEl = document.getElementById('kpi-bytes');
            if (reqEl) reqEl.textContent = json.total_requests;
            if (bytesEl) bytesEl.textContent = json.total_bytes_formatted;

            const tbody = document.getElementById('stats-requests-tbody');
            if (!tbody) return;
            const reqs = json.recent_requests || [];
            if (reqs.length === 0) {
                tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted" style="padding: 24px;">No requests recorded yet. Forwarded requests will appear here live.</td></tr>`;
                return;
            }

            let html = '';
            reqs.forEach(r => {
                const statusColor = r.status >= 200 && r.status < 300 ? 'dot-green' : (r.status >= 400 ? 'dot-amber' : 'dot-gray');
                html += `
                    <tr>
                        <td>${escapeHtml(r.timestamp)}</td>
                        <td><strong>${escapeHtml(r.site_name || 'Site')}</strong></td>
                        <td><span class="file-badge-code">${escapeHtml(r.method)}</span></td>
                        <td><code style="font-family: var(--font-mono); font-size: 12px;">${escapeHtml(r.path)}</code></td>
                        <td><span class="status-dot ${statusColor}"></span> ${r.status}</td>
                        <td>${formatBytes(r.size)}</td>
                        <td>${escapeHtml(r.client)}</td>
                    </tr>
                `;
            });
            tbody.innerHTML = html;
        }
    } catch (e) {
        console.error("Error loading stats:", e);
    }
}

// -------------------------------------------------------------------
// Live Logs
// -------------------------------------------------------------------
async function pollLogs() {
    try {
        const resp = await fetch('/api/logs');
        const json = await resp.json();
        if (json.success) {
            allLogsCache.tor = json.tor_logs || [];
            allLogsCache.app = json.app_logs || [];
            renderLogs();
        }
    } catch (e) {
        console.warn("Log polling error:", e);
    }
}

function pollLogsIfActive() {
    if (activeTab === 'logs') {
        pollLogs();
    }
}

function setLogView(filter) {
    logFilter = filter;
    document.querySelectorAll('.filter-tab').forEach(b => b.classList.remove('active'));
    if (event && event.target) {
        event.target.classList.add('active');
    }
    renderLogs();
}

function renderLogs() {
    const out = document.getElementById('log-output');
    if (!out) return;
    let lines = [];

    if (logFilter === 'all') {
        lines = [...allLogsCache.tor.map(l => `[TOR] ${l}`), ...allLogsCache.app.map(l => `[APP] ${l}`)];
    } else if (logFilter === 'tor') {
        lines = allLogsCache.tor;
    } else {
        lines = allLogsCache.app;
    }

    if (lines.length === 0) {
        out.textContent = "No log output recorded yet.";
        return;
    }

    out.textContent = lines.join('\n');

    const autoScrollCheck = document.getElementById('log-autoscroll');
    if (autoScrollCheck && autoScrollCheck.checked) {
        const win = document.getElementById('terminal-window');
        if (win) win.scrollTop = win.scrollHeight;
    }
}

async function clearLogs() {
    try {
        await fetch('/api/logs/clear', { method: 'POST' });
        allLogsCache = { tor: [], app: [] };
        renderLogs();
        showToast("Logs cleared.", "info");
    } catch (e) {
        showToast("Error clearing logs", "error");
    }
}

function copyLogsToClipboard() {
    const text = document.getElementById('log-output').textContent;
    copyToClipboard(text);
}

// -------------------------------------------------------------------
// Modals & Previews
// -------------------------------------------------------------------
function previewSite(siteId, localUrl, siteName) {
    document.getElementById('preview-title').textContent = `Preview: ${siteName} (${localUrl})`;
    document.getElementById('preview-iframe').src = localUrl;
    document.getElementById('preview-external-link').href = localUrl;
    document.getElementById('preview-modal').style.display = 'flex';
}

function closePreviewModal() {
    document.getElementById('preview-iframe').src = 'about:blank';
    document.getElementById('preview-modal').style.display = 'none';
}

function openNewSiteModal() {
    document.getElementById('new-site-modal').style.display = 'flex';
}

function closeNewSiteModal() {
    document.getElementById('new-site-modal').style.display = 'none';
}

async function submitModalNewSite() {
    const folder = document.getElementById('modal-folder-path').value.trim();
    const port = document.getElementById('modal-port').value.trim();

    if (!folder) {
        showToast("Website folder path cannot be empty.", "error");
        return;
    }

    closeNewSiteModal();
    showToast("Launching onion hosting for " + folder + "...", "info");

    try {
        const resp = await fetch('/api/sites/host', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder_path: folder, port: port || 8080 })
        });
        const res = await resp.json();
        if (res.success) {
            showToast("New Onion Service Online!", "success");
            loadSites();
            pollSystemStatus();
        } else {
            showToast("Error: " + res.error, "error");
        }
    } catch (e) {
        showToast("Failed to create site", "error");
    }
}

// -------------------------------------------------------------------
// Tabs & Sidebar Navigation
// -------------------------------------------------------------------
function switchTab(tabName) {
    activeTab = tabName;
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

    const tabBtn = document.getElementById(`tab-btn-${tabName}`);
    if (tabBtn) tabBtn.classList.add('active');

    const target = document.getElementById(`tab-${tabName}`);
    if (target) target.classList.add('active');

    if (tabName === 'stats') loadStats();
    if (tabName === 'logs') pollLogs();
    if (tabName === 'files' && currentFileSiteId) loadFilesForCurrentSite();
}

function switchSidebar(itemName) {
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    const clickedItem = document.getElementById(`nav-${itemName}`);
    if (clickedItem) clickedItem.classList.add('active');

    if (itemName === 'overview' || itemName === 'websites' || itemName === 'nodes' || itemName === 'service-control') {
        switchTab('sites');
    } else if (itemName === 'files') {
        switchTab('files');
    } else if (itemName === 'code') {
        switchTab('files');
    } else if (itemName === 'traffic') {
        switchTab('stats');
    } else if (itemName === 'telemetry' || itemName === 'logs') {
        switchTab('logs');
    }
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showToast("Copied to clipboard!", "success");
    }).catch(() => {
        // Fallback
        const textarea = document.createElement("textarea");
        textarea.value = text;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        document.body.removeChild(textarea);
        showToast("Copied to clipboard!", "success");
    });
}

function showToast(message, type = "info") {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

function formatSeconds(secs) {
    const d = Math.floor(secs / 86400);
    const h = Math.floor((secs % 86400) / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

function formatDate(ts) {
    if (!ts) return '--';
    const d = new Date(ts * 1000);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>"']/g, m => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    })[m]);
}
