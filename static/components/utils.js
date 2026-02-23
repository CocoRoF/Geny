/**
 * Claude Control Dashboard - Utility Functions
 */

/**
 * Escape HTML to prevent XSS
 * @param {string} text - Text to escape
 * @returns {string} Escaped HTML
 */
function escapeHtml(text) {
    if (!text) return '';
    if (typeof text !== 'string') return text;
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Format ISO timestamp to local time
 * @param {string} isoString - ISO timestamp string
 * @returns {string} Formatted time string
 */
function formatTimestamp(isoString) {
    try {
        const date = new Date(isoString);
        return date.toLocaleTimeString('en-US', {
            hour12: false,
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    } catch {
        return isoString;
    }
}

/**
 * Format file size in bytes to human readable format
 * @param {number} bytes - File size in bytes
 * @returns {string} Formatted file size
 */
function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

/**
 * Get file icon based on extension
 * @param {string} filename - File name
 * @returns {string} Icon emoji
 */
function getFileIcon(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    const iconMap = {
        'md': '📝',
        'txt': '📄',
        'json': '📋',
        'js': '📜',
        'py': '🐍',
        'html': '🌐',
        'css': '🎨',
        'log': '📊',
        'yml': '⚙️',
        'yaml': '⚙️'
    };
    return iconMap[ext] || '📄';
}

/**
 * Show error message
 * @param {string} message - Error message
 */
function showError(message) {
    console.error(message);
    // Could implement toast notifications here
    alert('Error: ' + message);
}

/**
 * Show success message
 * @param {string} message - Success message
 */
function showSuccess(message) {
    console.log('Success:', message);
    // Could implement toast notification here
    alert('✅ ' + message);
}

/**
 * Get session name by ID
 * @param {string} sessionId - Session ID
 * @returns {string} Session name or truncated ID
 */
function getSessionName(sessionId) {
    const session = state.sessions.find(s => s.session_id === sessionId);
    return session ? (session.session_name || sessionId.substring(0, 8)) : sessionId.substring(0, 8);
}

// ========== Sidebar Functions ==========

/**
 * Toggle sidebar collapsed state
 */
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    state.sidebarCollapsed = !state.sidebarCollapsed;

    if (state.sidebarCollapsed) {
        sidebar.classList.add('collapsed');
    } else {
        sidebar.classList.remove('collapsed');
    }

    // Save state to localStorage
    localStorage.setItem('sidebarCollapsed', state.sidebarCollapsed);
}

/**
 * Initialize sidebar state from localStorage
 */
function initSidebarState() {
    // Check if we're on mobile
    const isMobile = window.innerWidth <= 768;

    if (isMobile) {
        // On mobile, start collapsed by default or restore saved state
        const savedState = localStorage.getItem('sidebarCollapsed');
        state.sidebarCollapsed = savedState === null ? true : savedState === 'true';

        const sidebar = document.getElementById('sidebar');
        if (state.sidebarCollapsed) {
            sidebar.classList.add('collapsed');
        }
    }
}
