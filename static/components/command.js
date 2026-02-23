/**
 * Claude Control Dashboard - Command Execution
 */

/**
 * Execute command on selected session
 */
async function executeCommand() {
    if (!state.selectedSessionId) {
        showError('Please select a session first');
        return;
    }

    const prompt = document.getElementById('command-input').value.trim();
    if (!prompt) {
        showError('Please enter a prompt');
        return;
    }

    // Get current session to check if autonomous mode
    const session = state.sessions.find(s => s.session_id === state.selectedSessionId);
    if (!session) {
        showError('Session not found');
        return;
    }

    const skipPermissions = document.getElementById('skip-permissions').checked;

    // Check if session is in autonomous mode
    if (session.autonomous) {
        await executeAutonomousInternal(prompt, skipPermissions);
    } else {
        await executeSingleInternal(prompt, skipPermissions);
    }
}

/**
 * Execute single command
 * @param {string} prompt - Command prompt
 * @param {boolean} skipPermissions - Skip permissions flag
 */
async function executeSingleInternal(prompt, skipPermissions) {
    setExecutionStatus('running', 'Executing...');
    updateExecutionUI(true);
    notifyCharacterRequestStart(state.selectedSessionId);

    try {
        const result = await apiCall(`/api/agents/${state.selectedSessionId}/execute`, {
            method: 'POST',
            body: JSON.stringify({
                prompt: prompt,
                skip_permissions: skipPermissions
            })
        });

        const sessionData = getSessionData(state.selectedSessionId);
        sessionData.input = prompt;

        if (result.success) {
            const statusText = `Completed in ${result.duration_ms}ms`;
            setExecutionStatus('success', statusText);
            const output = result.output || 'No output';
            document.getElementById('command-output').textContent = output;

            sessionData.output = output;
            sessionData.status = 'success';
            sessionData.statusText = statusText;

            notifyCharacterRequestEnd(state.selectedSessionId, true);
        } else {
            setExecutionStatus('error', 'Failed');
            const output = result.error || 'Unknown error';
            document.getElementById('command-output').textContent = output;

            sessionData.output = output;
            sessionData.status = 'error';
            sessionData.statusText = 'Failed';

            notifyCharacterRequestEnd(state.selectedSessionId, false);
        }
    } catch (error) {
        setExecutionStatus('error', 'Error');
        document.getElementById('command-output').textContent = error.message;

        const sessionData = getSessionData(state.selectedSessionId);
        sessionData.output = error.message;
        sessionData.status = 'error';
        sessionData.statusText = 'Error';

        notifyCharacterRequestEnd(state.selectedSessionId, false);
    } finally {
        updateExecutionUI(false);
    }
}

/**
 * Execute autonomous command
 * @param {string} prompt - Command prompt
 * @param {boolean} skipPermissions - Skip permissions flag
 */
async function executeAutonomousInternal(prompt, skipPermissions) {
    state.isAutoContinuing = true;
    state.autoContinueCount = 0;
    updateExecutionUI(true);
    setExecutionStatus('running', 'Starting autonomous execution...');
    notifyCharacterRequestStart(state.selectedSessionId);

    try {
        const result = await apiCall(`/api/agents/${state.selectedSessionId}/execute/autonomous`, {
            method: 'POST',
            body: JSON.stringify({
                prompt: prompt,
                skip_permissions: skipPermissions
            })
        });

        const sessionData = getSessionData(state.selectedSessionId);
        sessionData.input = prompt;

        if (result.success) {
            const statusText = `✅ Completed in ${result.total_iterations} iterations (${result.stop_reason})`;
            setExecutionStatus('success', statusText);
            const output = result.final_output || 'No output';
            document.getElementById('command-output').textContent = output;

            sessionData.output = output;
            sessionData.status = 'success';
            sessionData.statusText = statusText;

            notifyCharacterRequestEnd(state.selectedSessionId, true);
        } else {
            setExecutionStatus('error', `❌ Failed: ${result.stop_reason}`);
            const output = result.error || result.final_output || 'Unknown error';
            document.getElementById('command-output').textContent = output;

            sessionData.output = output;
            sessionData.status = 'error';
            sessionData.statusText = `Failed: ${result.stop_reason}`;

            notifyCharacterRequestEnd(state.selectedSessionId, false);
        }
    } catch (error) {
        setExecutionStatus('error', 'Error');
        document.getElementById('command-output').textContent = error.message;

        const sessionData = getSessionData(state.selectedSessionId);
        sessionData.output = error.message;
        sessionData.status = 'error';
        sessionData.statusText = 'Error';

        notifyCharacterRequestEnd(state.selectedSessionId, false);
    } finally {
        state.isAutoContinuing = false;
        updateExecutionUI(false);
    }
}

/**
 * Stop execution
 */
async function stopExecution() {
    if (!state.selectedSessionId) return;

    // Check if session is autonomous
    const session = state.sessions.find(s => s.session_id === state.selectedSessionId);

    if (session && session.autonomous && state.isAutoContinuing) {
        try {
            await apiCall(`/api/agents/${state.selectedSessionId}/execute/autonomous/stop`, {
                method: 'POST'
            });
            setExecutionStatus('warning', '🛑 Stop requested, waiting for current iteration...');
        } catch (error) {
            console.error('Failed to stop autonomous execution:', error);
        }
    }

    state.isAutoContinuing = false;
    updateExecutionUI(false);
}

/**
 * Update execution UI (show/hide buttons)
 * @param {boolean} isRunning - Is command running
 */
function updateExecutionUI(isRunning) {
    const executeBtn = document.getElementById('execute-btn');
    const stopBtn = document.getElementById('stop-btn');

    if (isRunning) {
        if (executeBtn) executeBtn.classList.add('hidden');
        if (stopBtn) stopBtn.classList.remove('hidden');
    } else {
        if (executeBtn) executeBtn.classList.remove('hidden');
        if (stopBtn) stopBtn.classList.add('hidden');
    }
}

/**
 * Set execution status display
 * @param {string} status - Status class
 * @param {string} text - Status text
 */
function setExecutionStatus(status, text) {
    const statusEl = document.getElementById('execution-status');
    statusEl.textContent = text;
    statusEl.className = 'execution-status ' + status;
}

/**
 * Clear output display
 */
function clearOutput() {
    if (state.selectedSessionId) {
        const sessionData = getSessionData(state.selectedSessionId);
        sessionData.output = 'No output yet';
        sessionData.status = '';
        sessionData.statusText = '';
    }
    document.getElementById('command-output').textContent = 'No output yet';
    setExecutionStatus('', '');
}
