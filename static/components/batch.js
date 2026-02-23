/**
 * Claude Control Dashboard - Batch Execution
 */

/**
 * Update batch session list
 */
function updateBatchSessionList() {
    const container = document.getElementById('batch-session-list');

    if (state.sessions.length === 0) {
        container.innerHTML = '<p class="text-muted">No sessions available</p>';
        return;
    }

    container.innerHTML = state.sessions
        .filter(s => s.status === 'running')
        .map(s => `
            <label class="batch-session-item">
                <input type="checkbox" value="${s.session_id}" checked>
                <span>${s.session_name || s.session_id.substring(0, 8)}</span>
            </label>
        `).join('');
}

/**
 * Select all sessions in batch list
 */
function selectAllSessions() {
    document.querySelectorAll('#batch-session-list input[type="checkbox"]').forEach(cb => {
        cb.checked = true;
    });
}

/**
 * Deselect all sessions in batch list
 */
function deselectAllSessions() {
    document.querySelectorAll('#batch-session-list input[type="checkbox"]').forEach(cb => {
        cb.checked = false;
    });
}

/**
 * Execute batch command on selected sessions
 */
async function executeBatchCommand() {
    const selectedSessions = Array.from(
        document.querySelectorAll('#batch-session-list input[type="checkbox"]:checked')
    ).map(cb => cb.value);

    if (selectedSessions.length === 0) {
        showError('Please select at least one session');
        return;
    }

    const prompt = document.getElementById('batch-command-input').value.trim();
    if (!prompt) {
        showError('Please enter a command');
        return;
    }

    const timeout = parseInt(document.getElementById('batch-timeout').value) || 600;
    const parallel = document.getElementById('batch-parallel').checked;

    const resultsContainer = document.getElementById('batch-results');
    resultsContainer.innerHTML = '<div class="loading">Executing batch command...</div>';

    try {
        const result = await apiCall('/api/command/batch', {
            method: 'POST',
            body: JSON.stringify({
                session_ids: selectedSessions,
                prompt: prompt,
                timeout: timeout,
                parallel: parallel,
                skip_permissions: true
            })
        });

        renderBatchResults(result);
    } catch (error) {
        resultsContainer.innerHTML = `
            <div class="empty-state">
                <p>Batch execution failed: ${error.message}</p>
            </div>
        `;
    }
}

/**
 * Render batch execution results
 * @param {Object} result - Batch execution result
 */
function renderBatchResults(result) {
    const container = document.getElementById('batch-results');

    const summary = `
        <div class="batch-summary">
            <strong>Summary:</strong> ${result.successful}/${result.total_sessions} successful
            | Total time: ${result.total_duration_ms}ms
        </div>
    `;

    const results = result.results.map(r => `
        <div class="batch-result-item ${r.success ? 'success' : 'failed'}">
            <div class="batch-result-header">
                <strong>${getSessionName(r.session_id)}</strong>
                <span class="result-badge ${r.success ? 'success' : 'failed'}">${r.success ? 'Success' : 'Failed'}</span>
            </div>
            <div class="batch-result-output">
                ${escapeHtml(r.success ? (r.output || 'No output') : (r.error || 'Unknown error'))}
            </div>
            ${r.duration_ms ? `<small class="text-muted">Duration: ${r.duration_ms}ms</small>` : ''}
        </div>
    `).join('');

    container.innerHTML = summary + results;
}
