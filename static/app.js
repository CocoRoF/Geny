/**
 * Claude Control Dashboard - Main Application
 *
 * This file contains initialization logic and tab navigation.
 * All other functionality is split into components/*.js
 */

// ========== Health Check ==========

/**
 * Check server health
 */
async function checkHealth() {
    try {
        const health = await apiCall('/health');
        updateHealthIndicator('connected', `${health.total_sessions} sessions`);
    } catch (error) {
        updateHealthIndicator('disconnected', 'Disconnected');
    }
}

/**
 * Update health UI from SSR status
 * @param {string} status - Health status
 */
function updateHealthUI(status) {
    // Update health indicator based on SSR status
    if (status === 'healthy') {
        updateHealthIndicator('connected', `${state.sessions.length} sessions`);
    } else {
        updateHealthIndicator('disconnected', 'Disconnected');
    }
}

/**
 * Update health indicator display
 * @param {string} status - Status class
 * @param {string} text - Status text
 */
function updateHealthIndicator(status, text) {
    const indicator = document.getElementById('health-indicator');
    const dot = indicator.querySelector('.health-dot');
    const textEl = indicator.querySelector('.health-text');

    dot.className = 'health-dot ' + status;
    textEl.textContent = text;
}

// ========== Tab Navigation ==========

/**
 * Switch to a tab
 * @param {string} tabName - Tab name
 */
function switchTab(tabName) {
    // Load configs when switching to settings tab
    if (tabName === 'settings' && configState.configs.length === 0) {
        loadConfigs();
    }

    // Update tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });

    // Update tab panes
    document.querySelectorAll('.tab-pane').forEach(pane => {
        pane.classList.toggle('active', pane.id === `${tabName}-tab`);
    });

    // Logs tab: start polling; other tabs: stop it
    if (tabName === 'logs') {
        if (state.selectedSessionId) loadSessionLogs();
        startLogsAutoRefresh();
    } else {
        stopLogsAutoRefresh();
    }

    // Load storage when switching to storage tab
    if (tabName === 'storage') {
        refreshStorage();
    }

    // Initialize or sync playground view; pause/resume 3D loop
    if (tabName === 'playground') {
        initPlaygroundView();
        // Resume 3D render loop
        if (_playgroundInitialized && window.Playground?.Scene?.resume) {
            window.Playground.Scene.resume();
        }
    } else {
        // Pause 3D render loop when leaving playground
        if (_playgroundInitialized && window.Playground?.Scene?.pause) {
            window.Playground.Scene.pause();
        }
    }

    // Refresh dashboard when switching to dashboard tab
    if (tabName === 'dashboard') {
        refreshManagerDashboard();
    }

    // Load graph when switching to graph tab
    if (tabName === 'graph') {
        refreshGraphTab();
    }

    // Load info when switching to info tab
    if (tabName === 'info') {
        refreshInfoTab();
    }
}

// ========== Main Refresh ==========

/**
 * Refresh all data
 */
async function refreshAll() {
    // Skip initial API calls if SSR data is available
    if (initFromSSR()) {
        console.log('[SSR] Using server-rendered data, skipping initial API calls');
        // Just update the UI with SSR data (HTML is already rendered)
        updateHealthUI(state.healthStatus);
        syncPlaygroundSessions();
        // Always load deleted sessions from API (not SSR'd)
        loadDeletedSessions();
    } else {
        // Fallback: fetch data from API
        await loadSessions();
        await loadPrompts();
        await checkHealth();
        await loadDeletedSessions();
    }
}

// ========== Initialization ==========

document.addEventListener('DOMContentLoaded', () => {
    // Initialize sidebar state
    initSidebarState();

    // Load initial data
    refreshAll();

    // Periodic refresh
    setInterval(checkHealth, 30000); // Health check every 30s
    setInterval(loadSessions, 60000); // Session list every 60s

    // Logs auto-refresh is started on-demand when switching to logs tab
    // (not started globally to avoid polling when tab is inactive)

    // Handle resize events
    window.addEventListener('resize', () => {
        const isMobile = window.innerWidth <= 768;
        const sidebar = document.getElementById('sidebar');

        if (!isMobile) {
            // Reset sidebar state on desktop
            sidebar.classList.remove('collapsed');
            state.sidebarCollapsed = false;
        }
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        // Ctrl/Cmd + Enter to execute command
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            const activeTab = document.querySelector('.tab-btn.active')?.dataset.tab;
            if (activeTab === 'command') {
                executeCommand();
            } else if (activeTab === 'batch') {
                executeBatchCommand();
            }
        }

        // Escape to close modals
        if (e.key === 'Escape') {
            hideCreateSessionModal();
            hideDeleteSessionModal();
            hideConfigEditModal();
            hideImportConfigModal();
        }
    });
});
