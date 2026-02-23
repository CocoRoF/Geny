/**
 * Claude Control Dashboard - Manager Dashboard
 */

// Cache: skip redundant fetches
let _dashboardLastSessionId = null;
let _dashboardLastTimestamp = 0;
const _DASHBOARD_CACHE_TTL = 10000;  // 10 seconds

/**
 * Refresh manager dashboard
 */
async function refreshManagerDashboard() {
    if (!state.selectedSessionId) return;

    const session = state.sessions.find(s => s.session_id === state.selectedSessionId);
    if (!session || session.role !== 'manager') return;

    const now = Date.now();
    if (state.selectedSessionId === _dashboardLastSessionId
        && (now - _dashboardLastTimestamp) < _DASHBOARD_CACHE_TTL) {
        return; // fresh enough
    }
    _dashboardLastSessionId = state.selectedSessionId;
    _dashboardLastTimestamp = now;

    // Update dashboard session name
    const sessionNameEl = document.getElementById('dashboard-session-name');
    if (sessionNameEl) {
        sessionNameEl.textContent = session.session_name || session.session_id.substring(0, 8);
    }

    try {
        const dashboard = await apiCall(`/api/agents/${state.selectedSessionId}/dashboard`);
        renderManagerDashboard(dashboard);
    } catch (error) {
        console.error('Failed to load manager dashboard:', error);
    }
}

/**
 * Render manager dashboard content
 * @param {Object} dashboard - Dashboard data
 */
function renderManagerDashboard(dashboard) {
    // Update worker count
    document.getElementById('worker-count').textContent = dashboard.workers.length;

    // Render workers list
    const workersList = document.getElementById('workers-list');
    if (dashboard.workers.length === 0) {
        workersList.innerHTML = '<div class="empty-state-small">No workers assigned to this manager</div>';
    } else {
        workersList.innerHTML = dashboard.workers.map(worker => `
            <div class="worker-item ${worker.is_busy ? 'busy' : 'idle'}">
                <div class="worker-status-indicator ${worker.status}"></div>
                <div class="worker-info">
                    <div class="worker-name">${worker.worker_name || worker.worker_id.substring(0, 8)}</div>
                    <div class="worker-status-text">${worker.status}</div>
                </div>
                <div class="worker-task-info">
                    ${worker.is_busy
                        ? `<span class="worker-busy-badge">Working</span><span class="worker-task-text">${worker.current_task || ''}</span>`
                        : '<span class="worker-idle-badge">Idle</span>'}
                </div>
            </div>
        `).join('');
    }

    // Render activity timeline
    const timeline = document.getElementById('activity-timeline');
    if (dashboard.recent_events.length === 0) {
        timeline.innerHTML = '<div class="empty-state-small">No activity yet</div>';
    } else {
        timeline.innerHTML = dashboard.recent_events.map(event => {
            const time = new Date(event.timestamp).toLocaleString();
            const typeClass = getEventTypeClass(event.event_type);
            const icon = getEventIcon(event.event_type);
            return `
                <div class="timeline-item ${typeClass}">
                    <div class="timeline-icon">${icon}</div>
                    <div class="timeline-content">
                        <div class="timeline-header">
                            <span class="timeline-type">${formatEventType(event.event_type)}</span>
                            <span class="timeline-time">${time}</span>
                        </div>
                        <div class="timeline-message">${event.message}</div>
                        ${event.worker_id ? `<div class="timeline-worker">Worker: ${event.worker_id.substring(0, 8)}</div>` : ''}
                    </div>
                </div>
            `;
        }).join('');
    }
}

/**
 * Get CSS class for event type
 * @param {string} eventType - Event type
 * @returns {string} CSS class
 */
function getEventTypeClass(eventType) {
    switch (eventType) {
        case 'task_delegated':
        case 'worker_started':
            return 'event-info';
        case 'worker_completed':
            return 'event-success';
        case 'worker_error':
            return 'event-error';
        case 'worker_progress':
            return 'event-progress';
        default:
            return '';
    }
}

/**
 * Format event type for display
 * @param {string} eventType - Event type
 * @returns {string} Formatted event type
 */
function formatEventType(eventType) {
    const typeMap = {
        'task_delegated': 'Task Delegated',
        'worker_started': 'Worker Started',
        'worker_completed': 'Worker Completed',
        'worker_error': 'Worker Error',
        'worker_progress': 'Progress Update',
        'plan_created': 'Plan Created',
        'plan_updated': 'Plan Updated',
        'user_message': 'User Message',
        'manager_response': 'Manager Response'
    };
    return typeMap[eventType] || eventType;
}

/**
 * Get icon for event type
 * @param {string} eventType - Event type
 * @returns {string} Icon emoji
 */
function getEventIcon(eventType) {
    const iconMap = {
        'task_delegated': '📤',
        'worker_started': '▶️',
        'worker_completed': '✅',
        'worker_error': '❌',
        'worker_progress': '🔄',
        'plan_created': '📋',
        'plan_updated': '📝',
        'user_message': '💬',
        'manager_response': '🤖'
    };
    return iconMap[eventType] || '📌';
}
