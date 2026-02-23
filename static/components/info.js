/**
 * Claude Control Dashboard - Info Tab (Session Detail View)
 *
 * Shows detailed session metadata for the selected session.
 * Deleted sessions logic lives in sessions.js (sidebar).
 */

// Cache: skip redundant fetches
let _infoLastSessionId = null;
let _infoLastTimestamp = 0;
const _INFO_CACHE_TTL = 10000;  // 10 seconds

/**
 * Refresh the Info tab — load session detail for the selected session.
 */
async function refreshInfoTab() {
    const now = Date.now();
    if (state.selectedSessionId === _infoLastSessionId
        && (now - _infoLastTimestamp) < _INFO_CACHE_TTL) {
        return; // fresh enough
    }
    _infoLastSessionId = state.selectedSessionId;
    _infoLastTimestamp = now;
    await loadSessionDetail();
}

// ========================================================================
// Session Detail Panel
// ========================================================================

/**
 * Load and render detailed session info for the selected session.
 */
async function loadSessionDetail() {
    const container = document.getElementById('info-session-detail');
    if (!container) return;

    const sessionId = state.selectedSessionId;
    if (!sessionId) {
        container.innerHTML = `
            <div class="empty-state">
                <p>Select a session to view its details</p>
            </div>
        `;
        return;
    }

    try {
        // Try live agent first, fall back to store
        let data;
        try {
            data = await apiCall(`/api/agents/${sessionId}`);
            data._source = 'live';
        } catch {
            data = await apiCall(`/api/agents/store/${sessionId}`);
            data._source = 'store';
        }
        renderSessionDetail(container, data);
    } catch (error) {
        container.innerHTML = `
            <div class="empty-state">
                <p>Failed to load session details</p>
                <small>${escapeHtml(error.message)}</small>
            </div>
        `;
    }
}

/**
 * Render session detail HTML.
 */
function renderSessionDetail(container, data) {
    const isDeleted = data.is_deleted === true;
    const statusClass = isDeleted ? 'stopped' : (data.status || 'unknown');

    const fields = [
        { label: 'Session ID', value: data.session_id },
        { label: 'Name', value: data.session_name || '(unnamed)' },
        { label: 'Status', value: isDeleted ? '🗑️ Deleted' : (data.status || 'unknown'), class: statusClass },
        { label: 'Model', value: data.model || 'default' },
        { label: 'Role', value: data.role || 'worker' },
        { label: 'Autonomous', value: data.autonomous ? 'Yes' : 'No' },
        { label: 'Max Turns', value: data.max_turns ?? '—' },
        { label: 'Timeout', value: data.timeout ? `${data.timeout}s` : '—' },
        { label: 'Max Iterations', value: data.autonomous_max_iterations ?? '—' },
        { label: 'Storage Path', value: data.storage_path || '—' },
        { label: 'Created', value: data.created_at ? formatTimestamp(data.created_at) : '—' },
        { label: 'PID', value: data.pid || '—' },
        { label: 'Pod', value: data.pod_name || '—' },
        { label: 'Manager ID', value: data.manager_id ? data.manager_id.substring(0, 8) + '...' : '—' },
    ];

    if (isDeleted) {
        fields.push({ label: 'Deleted At', value: data.deleted_at ? formatTimestamp(data.deleted_at) : '—' });
    }

    let html = `
        <div class="info-detail-header">
            <h4>${escapeHtml(data.session_name || 'Session Details')}</h4>
            <span class="info-status-badge info-status-badge--${statusClass}">${isDeleted ? 'Deleted' : (data.status || 'unknown')}</span>
        </div>
        <div class="info-detail-grid">
    `;

    for (const f of fields) {
        html += `
            <div class="info-field">
                <span class="info-field-label">${f.label}</span>
                <span class="info-field-value ${f.class || ''}">${escapeHtml(String(f.value))}</span>
            </div>
        `;
    }

    html += `</div>`;

    // Actions for deleted sessions
    if (isDeleted) {
        html += `
            <div class="info-detail-actions">
                <button class="btn btn-primary btn-sm" onclick="restoreSession('${data.session_id}')">
                    ↻ Restore Session
                </button>
                <button class="btn btn-danger btn-sm" onclick="permanentDeleteSession('${data.session_id}')">
                    🗑️ Permanently Delete
                </button>
            </div>
        `;
    }

    container.innerHTML = html;
}
