/**
 * Claude Control Dashboard - Prompts Management
 */

/**
 * Load all prompts from API
 */
async function loadPrompts() {
    try {
        const response = await apiCall('/api/command/prompts');
        state.prompts = response.prompts || [];
        updatePromptDropdown();
    } catch (error) {
        console.error('Failed to load prompts:', error);
        // Non-critical, don't show error to user
    }
}

/**
 * Update prompt dropdown with loaded prompts
 */
function updatePromptDropdown() {
    const select = document.getElementById('new-session-prompt');
    if (!select) return;

    // Clear existing options except first (None) and last (Custom)
    while (select.options.length > 2) {
        select.remove(1);
    }

    // Insert prompt options before "Custom..."
    const customOption = select.options[select.options.length - 1];
    state.prompts.forEach(prompt => {
        const option = document.createElement('option');
        option.value = prompt.name;
        option.textContent = prompt.description || prompt.name;
        select.insertBefore(option, customOption);
    });

    // Set self-manager as default if available
    const selfManagerOption = Array.from(select.options).find(opt => opt.value === 'self-manager');
    if (selfManagerOption) {
        select.value = 'self-manager';
    }
}

/**
 * Handle prompt selection change
 */
async function onPromptSelect() {
    const select = document.getElementById('new-session-prompt');
    const customGroup = document.getElementById('custom-prompt-group');
    const customTextarea = document.getElementById('new-session-custom-prompt');

    if (select.value === 'custom') {
        customGroup.classList.remove('hidden');
        customTextarea.focus();
    } else {
        customGroup.classList.add('hidden');

        // Load prompt content if selecting a template
        if (select.value && select.value !== '') {
            await loadPromptContent(select.value);
        }
    }
}

/**
 * Load prompt content by name
 * @param {string} promptName - Prompt name
 * @returns {Promise<string|null>} Prompt content
 */
async function loadPromptContent(promptName) {
    if (state.promptContents[promptName]) {
        return state.promptContents[promptName];
    }

    try {
        const response = await apiCall(`/api/command/prompts/${promptName}`);
        state.promptContents[promptName] = response.content;
        return response.content;
    } catch (error) {
        console.error(`Failed to load prompt ${promptName}:`, error);
        return null;
    }
}

/**
 * Get content of selected prompt
 * @returns {Promise<string|null>} Prompt content
 */
async function getSelectedPromptContent() {
    const select = document.getElementById('new-session-prompt');
    const customTextarea = document.getElementById('new-session-custom-prompt');

    if (!select.value || select.value === '') {
        return null;
    }

    if (select.value === 'custom') {
        const content = customTextarea.value.trim();
        return content || null;
    }

    // Load template content
    return await loadPromptContent(select.value);
}
