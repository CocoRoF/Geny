/**
 * Claude Control Dashboard - Playground UI Functions
 * (Wraps playground-3d-scene.js with UI interactions)
 */

// Playground initialization flag
let _playgroundInitialized = false;

/**
 * Initialize playground view
 */
function initPlaygroundView() {
    if (_playgroundInitialized) {
        // Just sync sessions
        syncPlaygroundSessions();
        return;
    }

    const container = document.getElementById('playground-canvas');
    const loading = document.getElementById('playground-loading');
    if (!container) return;

    // Check if Three.js and Playground are loaded
    if (typeof THREE === 'undefined' || !window.Playground || !window.Playground.Scene) {
        if (loading) loading.querySelector('.playground-loading-text').textContent = 'Loading Three.js...';
        console.error('Three.js or Playground not loaded');
        return;
    }

    // Wait a frame for the tab to become visible and sized
    requestAnimationFrame(() => {
        try {
            const scene = window.Playground.Scene;
            scene.mount(container).then(() => {
                _playgroundInitialized = true;
                if (loading) loading.style.display = 'none';

                // Initial session sync
                syncPlaygroundSessions();

                // Listen for avatar clicks
                document.addEventListener('playground-avatar-click', (e) => {
                    const sessionId = e.detail.sessionId;
                    selectSession(sessionId);
                    switchTab('command');
                });
            });
        } catch (err) {
            console.error('Failed to init playground view:', err);
            if (loading) {
                loading.querySelector('.playground-loading-text').textContent = 'Failed to initialize';
            }
        }
    });
}

/**
 * Sync playground sessions with current state
 */
function syncPlaygroundSessions() {
    if (!_playgroundInitialized) return;
    const scene = window.Playground.Scene;
    if (scene && scene.isInitialized) {
        scene.syncSessions(state.sessions);

        // Update UI
        const countEl = document.getElementById('playground-session-count');
        if (countEl) {
            countEl.textContent = `${state.sessions.length} citizen${state.sessions.length !== 1 ? 's' : ''}`;
        }

        const emptyState = document.getElementById('playground-empty-state');
        if (emptyState) {
            emptyState.style.display = state.sessions.length === 0 ? 'block' : 'none';
        }

        // Update status overlay
        updatePlaygroundStatusOverlay();
    }
}

/**
 * Update playground status overlay
 */
function updatePlaygroundStatusOverlay() {
    const overlay = document.getElementById('playground-status-overlay');
    if (!overlay) return;

    const running = state.sessions.filter(s => s.status === 'running').length;
    const idle = state.sessions.filter(s => s.status !== 'running' && s.status !== 'error').length;
    const errors = state.sessions.filter(s => s.status === 'error').length;

    let html = '';
    if (running > 0) {
        html += `<div class="playground-status-item"><span class="playground-status-dot running"></span>${running} working</div>`;
    }
    if (idle > 0) {
        html += `<div class="playground-status-item"><span class="playground-status-dot idle"></span>${idle} idle</div>`;
    }
    if (errors > 0) {
        html += `<div class="playground-status-item"><span class="playground-status-dot error"></span>${errors} error</div>`;
    }
    overlay.innerHTML = html;
}

/**
 * Notify character of request start
 * @param {string} sessionId - Session ID
 */
function notifyCharacterRequestStart(sessionId) {
    if (!_playgroundInitialized) return;
    const scene = window.Playground.Scene;
    if (scene && scene.isInitialized) {
        scene.notifyRequestStart(sessionId);
    }
}

/**
 * Notify character of request end
 * @param {string} sessionId - Session ID
 * @param {boolean} success - Was request successful
 */
function notifyCharacterRequestEnd(sessionId, success) {
    if (!_playgroundInitialized) return;
    const scene = window.Playground.Scene;
    if (scene && scene.isInitialized) {
        scene.notifyRequestEnd(sessionId, success);
    }
}

/**
 * Zoom in playground view
 */
function playgroundZoomIn() {
    const scene = window.Playground.Scene;
    if (scene) scene.zoomIn();
}

/**
 * Zoom out playground view
 */
function playgroundZoomOut() {
    const scene = window.Playground.Scene;
    if (scene) scene.zoomOut();
}

/**
 * Reset playground view
 */
function playgroundResetView() {
    const scene = window.Playground.Scene;
    if (scene) scene.resetView();
}
