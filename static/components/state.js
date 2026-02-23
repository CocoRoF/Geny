/**
 * Claude Control Dashboard - Global State Management
 */

// Global state
const state = {
    sessions: [],
    selectedSessionId: null,
    isLoading: false,
    healthStatus: 'connecting',
    sidebarCollapsed: false,
    // Session-specific data cache
    sessionData: {}, // { sessionId: { input: '', output: '', status: '', statusText: '' } }
    // Available prompt templates
    prompts: [], // [{ name, filename, description }]
    promptContents: {}, // { promptName: content }
    // Auto-continue state
    isAutoContinuing: false,
    autoContinueCount: 0,
    autoContinueRetries: 0,
    maxRetries: 3,
    // SSR initial state loaded flag
    ssrInitialized: false,
    // Logs auto-refresh state
    logsAutoRefreshInterval: null,
    logsAutoRefreshEnabled: true
};

// Config state (separate namespace)
const configState = {
    configs: [],
    categories: [],
    selectedCategory: 'all',
    currentConfig: null
};

// Initialize from SSR data if available
function initFromSSR() {
    if (window.__INITIAL_STATE__ && !state.ssrInitialized) {
        const ssr = window.__INITIAL_STATE__;
        console.log('[SSR] Initializing from server-rendered state');

        // Load sessions from SSR
        if (ssr.sessions && Array.isArray(ssr.sessions)) {
            state.sessions = ssr.sessions;
            console.log(`[SSR] Loaded ${state.sessions.length} sessions`);
        }

        // Load prompts from SSR
        if (ssr.prompts && Array.isArray(ssr.prompts)) {
            state.prompts = ssr.prompts;
            console.log(`[SSR] Loaded ${state.prompts.length} prompts`);
        }

        // Load health status from SSR
        if (ssr.health) {
            state.healthStatus = ssr.health.status === 'healthy' ? 'healthy' : 'error';
        }

        state.ssrInitialized = true;
        return true;
    }
    return false;
}

// Get or initialize session data
function getSessionData(sessionId) {
    if (!state.sessionData[sessionId]) {
        state.sessionData[sessionId] = {
            input: '',
            output: 'No output yet',
            status: '',
            statusText: ''
        };
    }
    return state.sessionData[sessionId];
}

// Save current session's input to cache
function saveCurrentSessionInput() {
    if (state.selectedSessionId) {
        const data = getSessionData(state.selectedSessionId);
        const inputEl = document.getElementById('command-input');
        if (inputEl) {
            data.input = inputEl.value;
        }
    }
}
