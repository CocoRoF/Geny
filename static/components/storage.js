/**
 * Claude Control Dashboard - Storage Management
 */

// Cache: skip redundant fetches
let _storageLastSessionId = null;
let _storageLastTimestamp = 0;
const _STORAGE_CACHE_TTL = 10000;  // 10 seconds

/**
 * Refresh storage view for selected session
 */
async function refreshStorage() {
    if (!state.selectedSessionId) {
        showStoragePlaceholder('Select a session to view its storage');
        return;
    }

    const now = Date.now();
    if (state.selectedSessionId === _storageLastSessionId
        && (now - _storageLastTimestamp) < _STORAGE_CACHE_TTL) {
        return; // fresh enough
    }
    _storageLastSessionId = state.selectedSessionId;
    _storageLastTimestamp = now;

    const storageTree = document.getElementById('storage-tree');
    storageTree.innerHTML = '<p class="storage-placeholder">Loading...</p>';

    try {
        const response = await fetch(`/api/agents/${state.selectedSessionId}/storage`);
        if (!response.ok) {
            if (response.status === 404) {
                showStoragePlaceholder('No storage found for this session');
                return;
            }
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        renderStorageTree(data.files || []);
    } catch (error) {
        console.error('Failed to load storage:', error);
        showStoragePlaceholder('Failed to load storage');
    }
}

/**
 * Show storage placeholder message
 * @param {string} message - Placeholder message
 */
function showStoragePlaceholder(message) {
    const storageTree = document.getElementById('storage-tree');
    storageTree.innerHTML = `<p class="storage-placeholder">${message}</p>`;

    const previewFilename = document.getElementById('preview-filename');
    const previewContent = document.getElementById('preview-content');
    previewFilename.textContent = 'No file selected';
    previewContent.textContent = '';
}

/**
 * Render storage file tree
 * @param {Array} files - List of files
 */
function renderStorageTree(files) {
    const storageTree = document.getElementById('storage-tree');

    if (!files || files.length === 0) {
        showStoragePlaceholder('Storage is empty');
        return;
    }

    // Build tree structure
    const tree = buildFileTree(files);
    storageTree.innerHTML = renderTreeNode(tree, '');
}

/**
 * Build file tree structure from flat file list
 * @param {Array} files - List of files
 * @returns {Object} Tree structure
 */
function buildFileTree(files) {
    const tree = { children: {}, files: [] };

    for (const file of files) {
        const parts = file.path.split('/').filter(p => p);
        let current = tree;

        for (let i = 0; i < parts.length - 1; i++) {
            const part = parts[i];
            if (!current.children[part]) {
                current.children[part] = { children: {}, files: [] };
            }
            current = current.children[part];
        }

        current.files.push({
            name: parts[parts.length - 1],
            path: file.path,
            size: file.size || 0
        });
    }

    return tree;
}

/**
 * Render tree node HTML
 * @param {Object} node - Tree node
 * @param {string} path - Current path
 * @returns {string} HTML string
 */
function renderTreeNode(node, path) {
    let html = '<ul class="file-tree">';

    // Render folders first
    for (const [name, child] of Object.entries(node.children)) {
        const folderPath = path ? `${path}/${name}` : name;
        html += `
            <li class="file-tree-folder" data-path="${escapeHtml(folderPath)}">
                <div class="file-tree-folder-header" onclick="toggleFolder(this.parentElement)">
                    <span class="folder-toggle">▼</span>
                    <span class="file-icon">📁</span>
                    <span class="file-name">${escapeHtml(name)}</span>
                </div>
                <div class="file-tree-folder-children">
                    ${renderTreeNode(child, folderPath)}
                </div>
            </li>
        `;
    }

    // Render files
    for (const file of node.files) {
        const icon = getFileIcon(file.name);
        const sizeStr = formatFileSize(file.size);
        html += `
            <li class="file-tree-item" data-path="${escapeHtml(file.path)}" onclick="loadStorageFile('${escapeHtml(file.path)}')">
                <span class="file-icon">${icon}</span>
                <span class="file-name">${escapeHtml(file.name)}</span>
                <span class="file-size">${sizeStr}</span>
            </li>
        `;
    }

    html += '</ul>';
    return html;
}

/**
 * Toggle folder collapsed state
 * @param {HTMLElement} folderElement - Folder element
 */
function toggleFolder(folderElement) {
    folderElement.classList.toggle('collapsed');
}

/**
 * Load storage file content
 * @param {string} filePath - File path
 */
async function loadStorageFile(filePath) {
    if (!state.selectedSessionId) return;

    // Update active state in tree
    document.querySelectorAll('.file-tree-item.active').forEach(el => el.classList.remove('active'));
    const activeItem = document.querySelector(`.file-tree-item[data-path="${CSS.escape(filePath)}"]`);
    if (activeItem) activeItem.classList.add('active');

    const previewFilename = document.getElementById('preview-filename');
    const previewContent = document.getElementById('preview-content');

    previewFilename.textContent = filePath;
    previewContent.textContent = 'Loading...';

    try {
        // Remove leading slash if present
        const cleanPath = filePath.startsWith('/') ? filePath.substring(1) : filePath;
        const response = await fetch(`/api/agents/${state.selectedSessionId}/storage/${encodeURIComponent(cleanPath)}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();
        previewContent.textContent = data.content || '(empty file)';
    } catch (error) {
        console.error('Failed to load file:', error);
        previewContent.textContent = `Error loading file: ${error.message}`;
    }
}
