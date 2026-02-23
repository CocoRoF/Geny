/**
 * Claude Control Dashboard - Modal Management
 */

/**
 * Show create session modal
 */
function showCreateSessionModal() {
    document.getElementById('create-session-modal').classList.remove('hidden');
    document.getElementById('new-session-name').value = '';
    document.getElementById('new-session-prompt').value = 'self-manager';
    document.getElementById('new-session-custom-prompt').value = '';
    document.getElementById('custom-prompt-group').classList.add('hidden');
    document.getElementById('new-session-model').value = '';
    document.getElementById('new-session-max-turns').value = '100';
    document.getElementById('new-session-autonomous').checked = true;
}

/**
 * Hide create session modal
 */
function hideCreateSessionModal() {
    document.getElementById('create-session-modal').classList.add('hidden');
}
