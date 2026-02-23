/**
 * Claude Control Dashboard - Logs Management
 */

/** Set of log entry keys (timestamp+level) that are currently expanded. */
const _expandedLogKeys = new Set();

/** Whether loadSessionLogs was triggered by auto-refresh (not manual). */
let _isAutoRefresh = false;

/**
 * Build a stable key for a log entry so we can track expanded state across re-renders.
 */
function _logEntryKey(entry) {
    return `${entry.timestamp}|${entry.level}|${(entry.message || '').substring(0, 60)}`;
}

/**
 * Start auto-refresh for logs (5 second interval)
 */
function startLogsAutoRefresh() {
    if (state.logsAutoRefreshInterval) {
        clearInterval(state.logsAutoRefreshInterval);
    }
    state.logsAutoRefreshInterval = setInterval(() => {
        const activeTab = document.querySelector('.tab-btn.active')?.dataset.tab;
        if (activeTab === 'logs' && state.selectedSessionId && state.logsAutoRefreshEnabled) {
            _isAutoRefresh = true;
            loadSessionLogs();
        }
    }, 5000);
}

/**
 * Stop auto-refresh for logs
 */
function stopLogsAutoRefresh() {
    if (state.logsAutoRefreshInterval) {
        clearInterval(state.logsAutoRefreshInterval);
        state.logsAutoRefreshInterval = null;
    }
}

/**
 * Toggle auto-refresh for logs
 */
function toggleLogsAutoRefresh() {
    const checkbox = document.getElementById('logs-auto-refresh');
    state.logsAutoRefreshEnabled = checkbox.checked;

    if (state.logsAutoRefreshEnabled) {
        startLogsAutoRefresh();
    } else {
        stopLogsAutoRefresh();
    }
}

/**
 * Load session logs from API
 */
async function loadSessionLogs() {
    const sessionId = state.selectedSessionId;
    const levelFilter = document.getElementById('log-level-filter')?.value;
    const container = document.getElementById('logs-content');
    const isAuto = _isAutoRefresh;
    _isAutoRefresh = false; // reset flag

    if (!sessionId) {
        container.innerHTML = `
            <div class="empty-state">
                <p>Select a session to view logs</p>
            </div>
        `;
        return;
    }

    // Show loading indicator only on the first manual load (not auto-refresh)
    if (!isAuto && container.children.length === 0) {
        container.innerHTML = '<div class="loading">Loading logs...</div>';
    }

    // Capture scroll state BEFORE rebuilding DOM
    const prevScrollTop = container.scrollTop;
    const prevScrollHeight = container.scrollHeight;
    const wasNearBottom = (prevScrollHeight - container.clientHeight - prevScrollTop) < 60;

    try {
        let url = `/api/command/logs/${sessionId}?limit=200`;
        if (levelFilter) {
            url += `&level=${levelFilter}`;
        }

        const result = await apiCall(url);

        if (result.entries.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <p>No logs found</p>
                </div>
            `;
            return;
        }

        const html = result.entries.map(entry => {
            const message = entry.message || '';
            const metadata = entry.metadata || {};
            const isLongMessage = metadata.is_truncated || message.length > 200;
            const preview = metadata.preview || message.substring(0, 200) + (message.length > 200 ? '...' : '');
            const key = _logEntryKey(entry);
            const wasExpanded = _expandedLogKeys.has(key);

            if (isLongMessage) {
                return `
                    <div class="log-entry expandable${wasExpanded ? ' expanded' : ''}"
                         data-log-key="${escapeHtml(key)}"
                         onclick="toggleLogEntry(this)">
                        <div class="log-header">
                            <span class="log-timestamp">${formatTimestamp(entry.timestamp)}</span>
                            <span class="log-level ${entry.level}">${entry.level}</span>
                            <span class="log-expand-icon">${wasExpanded ? '▼' : '▶'}</span>
                        </div>
                        <div class="log-message-container">
                            <span class="log-message log-preview${wasExpanded ? ' hidden' : ''}">${escapeHtml(preview)}</span>
                            <span class="log-message log-full${wasExpanded ? '' : ' hidden'}">${escapeHtml(message)}</span>
                        </div>
                        ${metadata.prompt_length ? `<span class="log-meta">(${metadata.prompt_length} chars)</span>` : ''}
                        ${metadata.output_length ? `<span class="log-meta">(${metadata.output_length} chars)</span>` : ''}
                    </div>
                `;
            } else {
                return `
                    <div class="log-entry">
                        <span class="log-timestamp">${formatTimestamp(entry.timestamp)}</span>
                        <span class="log-level ${entry.level}">${entry.level}</span>
                        <span class="log-message">${escapeHtml(message)}</span>
                    </div>
                `;
            }
        }).join('');

        container.innerHTML = html;

        // Scroll behavior:
        //  - First load / manual refresh: scroll to bottom
        //  - Auto-refresh + user was near bottom: scroll to bottom (follow new logs)
        //  - Auto-refresh + user scrolled up: preserve position
        if (!isAuto || wasNearBottom) {
            container.scrollTop = container.scrollHeight;
        } else {
            // Keep the same visual position despite potentially new content at bottom
            const newScrollHeight = container.scrollHeight;
            container.scrollTop = prevScrollTop + (newScrollHeight - prevScrollHeight);
        }
    } catch (error) {
        // On auto-refresh failure, silently keep existing content
        if (!isAuto) {
            container.innerHTML = `
                <div class="empty-state">
                    <p>Failed to load logs: ${error.message}</p>
                </div>
            `;
        }
    }
}

/**
 * Toggle log entry expansion
 * @param {HTMLElement} element - Log entry element
 */
function toggleLogEntry(element) {
    const key = element.dataset.logKey;
    const isExpanded = element.classList.contains('expanded');

    if (isExpanded) {
        // Collapse
        element.classList.remove('expanded');
        element.querySelector('.log-expand-icon').textContent = '▶';
        element.querySelector('.log-preview').classList.remove('hidden');
        element.querySelector('.log-full').classList.add('hidden');
        if (key) _expandedLogKeys.delete(key);
    } else {
        // Expand
        element.classList.add('expanded');
        element.querySelector('.log-expand-icon').textContent = '▼';
        element.querySelector('.log-preview').classList.add('hidden');
        element.querySelector('.log-full').classList.remove('hidden');
        if (key) _expandedLogKeys.add(key);
    }
}
