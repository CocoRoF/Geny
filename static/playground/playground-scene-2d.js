/**
 * Playground Scene Manager - Three.js 2D Isometric Rendering
 * Uses orthographic camera with 2D positioning for pre-rendered isometric sprites
 */
(function() {
    'use strict';

    window.Playground = window.Playground || {};

    const DEBUG = true;

    function debugLog(...args) {
        if (DEBUG) {
            console.log('[PlaygroundScene]', ...args);
        }
    }

    // ==================== Sprite Configuration ====================
    // Kenney isometric miniature sprites are 256x512 pixels
    // The tile diamond is at the bottom ~148px
    const SPRITE_CONFIG = {
        TILE_W: 256,        // Tile width in pixels
        TILE_H: 128,        // Tile height (diamond height)
        SPRITE_W: 256,      // Full sprite width
        SPRITE_H: 512,      // Full sprite height
        PIXELS_PER_UNIT: 128, // How many pixels = 1 world unit (for scaling)
    };

    // ==================== Wall Type to Asset Mapping ====================
    const WALL_ASSET_MAP = {
        straight: { S: 'stone_S', E: 'stone_E' },
        window: { S: 'stoneWindow_S', E: 'stoneWindow_E' },
        corner: { S: 'stoneCorner_S', E: 'stoneCorner_E' },
        archway: { S: 'stoneArchway_S', E: 'stoneArchway_E' }
    };

    // ==================== PlaygroundScene Class ====================
    class PlaygroundScene {
        constructor() {
            // Core Three.js components
            this.renderer = null;
            this.scene = null;
            this.camera = null;

            // Playground systems
            this.assetLoader = null;
            this.characterSystem = null;
            this.behaviorManager = null;

            // Character management
            this.characters = new Map(); // sessionId -> characterData

            // State
            this.running = false;
            this.container = null;
            this.animationFrameId = null;
            this.lastFrameTime = 0;

            // Scene elements storage for cleanup
            this.floorTiles = [];
            this.wallSegments = [];
            this.furnitureItems = [];

            // Camera state
            this.cameraOffset = { x: 0, y: 0 };
            this.targetCameraOffset = { x: 0, y: 0 };
            this.zoom = 1.0;
            this.targetZoom = 1.0;

            // Drag state
            this.isDragging = false;
            this._dragStart = { x: 0, y: 0 };
            this._cameraStart = { x: 0, y: 0 };

            // For app.js compatibility
            this.isInitialized = false;

            debugLog('PlaygroundScene instance created');
        }

        /**
         * Get instance - for compatibility with app.js
         */
        static getInstance() {
            return window.Playground.Scene;
        }

        // ==================== Grid to Screen Conversion ====================
        /**
         * Convert grid coordinates to screen (world) coordinates
         * Uses standard isometric formula
         */
        gridToScreen(gx, gy) {
            const PPU = SPRITE_CONFIG.PIXELS_PER_UNIT;
            // Standard isometric conversion
            // x = (gx - gy) * (TILE_W / 2) / PPU
            // y = (gx + gy) * (TILE_H / 2) / PPU
            // Note: In Three.js, Y is up, so we negate the y value
            return {
                x: (gx - gy) * (SPRITE_CONFIG.TILE_W / 2) / PPU,
                y: -(gx + gy) * (SPRITE_CONFIG.TILE_H / 2) / PPU  // Negate for Three.js coordinate system
            };
        }

        /**
         * Calculate depth sort key
         * Higher values = rendered in front
         */
        depthKey(gx, gy, layer = 0) {
            return (gx + gy) * 100 + layer;
        }

        // ==================== Mount and Setup ====================
        /**
         * Mount the scene to a container element
         * @param {HTMLElement} container - The container to mount to
         */
        async mount(container) {
            debugLog('Mounting scene to container', container);

            this.container = container;
            const width = container.clientWidth;
            const height = container.clientHeight;

            // Create WebGLRenderer
            this.renderer = new THREE.WebGLRenderer({
                alpha: true,
                antialias: true
            });
            this.renderer.setSize(width, height);
            this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
            this.renderer.sortObjects = true;
            container.appendChild(this.renderer.domElement);

            // Create Scene with dark brown background
            this.scene = new THREE.Scene();
            this.scene.background = new THREE.Color(0x2a1a0a);

            // Create 2D orthographic camera (looking straight at scene)
            this._setupCamera(width, height);

            // Initialize AssetLoader and load all assets
            this.assetLoader = new window.Playground.AssetLoader();
            await this.assetLoader.loadAll((loaded, total, url) => {
                debugLog(`Loading assets: ${loaded}/${total}`);
            });
            debugLog('All assets loaded');

            // Initialize CharacterSystem
            if (window.Playground.CharacterSystem) {
                this.characterSystem = new window.Playground.CharacterSystem();
                await this.characterSystem.init(this.scene);
                await this.characterSystem.loadAllModels((loaded, total) => {
                    debugLog(`Loading characters: ${loaded}/${total}`);
                });
                debugLog('CharacterSystem initialized');
            } else {
                debugLog('Warning: CharacterSystem not available');
            }

            // Initialize BehaviorManager
            if (window.Playground.BehaviorManager) {
                this.behaviorManager = new window.Playground.BehaviorManager();
                this.behaviorManager.init();
                this.behaviorManager.characterSystem = this.characterSystem;
                debugLog('BehaviorManager initialized');
            }

            // Build the room
            this._buildRoom();

            // Center camera on room
            this._centerCameraOnRoom();

            // Add resize handler
            this._resizeHandler = () => this._onResize();
            window.addEventListener('resize', this._resizeHandler);

            // Add input event handlers for drag/pan
            this._setupInputHandlers();

            // Start game loop
            this.running = true;
            this.lastFrameTime = performance.now();
            this._gameLoop(this.lastFrameTime);

            // Mark as initialized
            this.isInitialized = true;

            debugLog('Scene mounted and running');
        }

        /**
         * Setup 2D orthographic camera
         * Camera looks straight at the XY plane (no isometric angle - sprites have it baked in)
         * @private
         */
        _setupCamera(width, height) {
            const aspect = width / height;
            const frustumHeight = 8; // World units visible vertically
            const frustumWidth = frustumHeight * aspect;

            this.camera = new THREE.OrthographicCamera(
                -frustumWidth / 2,
                frustumWidth / 2,
                frustumHeight / 2,
                -frustumHeight / 2,
                0.1,
                1000
            );

            // Camera looks straight at the scene from the front
            // Z+ is towards camera, so position at Z=100
            this.camera.position.set(0, 0, 100);
            this.camera.lookAt(0, 0, 0);
            this.camera.updateProjectionMatrix();

            this.frustumHeight = frustumHeight;

            debugLog('Camera setup complete (2D orthographic)');
        }

        /**
         * Center camera on the room
         * @private
         */
        _centerCameraOnRoom() {
            const Layout = window.Playground.Layout;
            if (!Layout) return;

            // Find center of room in grid coordinates
            const centerGX = Layout.ROOM.WIDTH / 2;
            const centerGY = Layout.ROOM.HEIGHT / 2;

            // Convert to screen coordinates
            const center = this.gridToScreen(centerGX, centerGY);

            // Offset camera
            this.cameraOffset = { x: -center.x, y: -center.y };
            this.targetCameraOffset = { x: -center.x, y: -center.y };
            this.camera.position.x = this.cameraOffset.x;
            this.camera.position.y = this.cameraOffset.y;
        }

        // ==================== Input Handlers ====================
        /**
         * Setup mouse/pointer event handlers for drag/pan
         * @private
         */
        _setupInputHandlers() {
            const canvas = this.renderer.domElement;

            // Mouse down - start drag
            this._onPointerDown = (e) => {
                if (e.button !== 0) return; // Only left mouse button
                this.isDragging = true;
                this._dragStart = { x: e.clientX, y: e.clientY };
                this._cameraStart = { x: this.targetCameraOffset.x, y: this.targetCameraOffset.y };
                canvas.style.cursor = 'grabbing';
            };

            // Mouse move - update drag
            this._onPointerMove = (e) => {
                if (!this.isDragging) return;

                const dx = e.clientX - this._dragStart.x;
                const dy = e.clientY - this._dragStart.y;

                // Scale by zoom (higher zoom = less movement needed)
                const scale = 1 / this.zoom;
                // Convert pixel delta to world units
                const PPU = SPRITE_CONFIG.PIXELS_PER_UNIT;
                // Negate both to drag in natural direction (drag right = view moves right)
                const worldDX = -(dx / PPU) * scale;
                const worldDY = (dy / PPU) * scale;

                this.targetCameraOffset.x = this._cameraStart.x + worldDX;
                this.targetCameraOffset.y = this._cameraStart.y + worldDY;
            };

            // Mouse up - end drag
            this._onPointerUp = () => {
                if (this.isDragging) {
                    this.isDragging = false;
                    canvas.style.cursor = 'grab';
                }
            };

            // Mouse leave - end drag
            this._onPointerLeave = () => {
                if (this.isDragging) {
                    this.isDragging = false;
                    canvas.style.cursor = 'grab';
                }
            };

            // Set initial cursor
            canvas.style.cursor = 'grab';

            // Add event listeners
            canvas.addEventListener('mousedown', this._onPointerDown);
            canvas.addEventListener('mousemove', this._onPointerMove);
            canvas.addEventListener('mouseup', this._onPointerUp);
            canvas.addEventListener('mouseleave', this._onPointerLeave);

            debugLog('Input handlers setup complete');
        }

        // ==================== Sprite Creation ====================
        /**
         * Create a sprite at grid position
         * @private
         */
        _createSprite(category, name, gx, gy, options = {}) {
            const texture = this.assetLoader.getTexture(category, name);
            if (!texture) {
                console.warn(`Texture not found: ${category}/${name}`);
                return null;
            }

            const PPU = SPRITE_CONFIG.PIXELS_PER_UNIT;
            const spriteW = (options.width || SPRITE_CONFIG.SPRITE_W) / PPU;
            const spriteH = (options.height || SPRITE_CONFIG.SPRITE_H) / PPU;

            // Create sprite material
            const material = new THREE.SpriteMaterial({
                map: texture,
                transparent: true,
                alphaTest: 0.1
            });

            const sprite = new THREE.Sprite(material);
            sprite.scale.set(spriteW, spriteH, 1);

            // Position: anchor at bottom-center
            // Sprite center is at (0.5, 0.5) by default
            // We want bottom-center, so offset Y by half height
            const screenPos = this.gridToScreen(gx, gy);
            sprite.position.set(
                screenPos.x,
                screenPos.y + spriteH / 2,  // Offset up by half height for bottom anchor
                0
            );

            // Depth sorting via renderOrder
            const layer = options.layer || 0;
            sprite.renderOrder = this.depthKey(gx, gy, layer);

            return sprite;
        }

        // ==================== Room Building ====================
        /**
         * Build the room from layout data
         * @private
         */
        _buildRoom() {
            const Layout = window.Playground.Layout;
            if (!Layout) {
                console.error('Layout not available');
                return;
            }

            debugLog('Building room...', {
                width: Layout.ROOM.WIDTH,
                height: Layout.ROOM.HEIGHT
            });

            // Build floor tiles
            this._buildFloor(Layout);

            // Build walls
            this._buildWalls(Layout);

            // Build furniture
            this._buildFurniture(Layout);

            debugLog('Room build complete');
        }

        /**
         * Build floor tiles
         * @private
         */
        _buildFloor(Layout) {
            const ROOM = Layout.ROOM;

            for (let gx = 0; gx < ROOM.WIDTH; gx++) {
                for (let gy = 0; gy < ROOM.HEIGHT; gy++) {
                    const sprite = this._createSprite('floor', 'stone_E', gx, gy, { layer: 0 });
                    if (sprite) {
                        this.scene.add(sprite);
                        this.floorTiles.push(sprite);
                    }
                }
            }

            debugLog(`Created ${this.floorTiles.length} floor tiles`);
        }

        /**
         * Build walls
         * @private
         */
        _buildWalls(Layout) {
            const WALLS = Layout.WALLS;
            if (!WALLS) return;

            // Back wall (along gy=0)
            if (WALLS.back) {
                for (const wallDef of WALLS.back) {
                    const assetName = this._getWallAsset(wallDef.type, wallDef.direction);
                    if (assetName) {
                        const sprite = this._createSprite('wall', assetName, wallDef.gx, 0, { layer: 10 });
                        if (sprite) {
                            this.scene.add(sprite);
                            this.wallSegments.push(sprite);
                        }
                    }
                }
            }

            // Left wall (along gx=0)
            if (WALLS.left) {
                for (const wallDef of WALLS.left) {
                    const assetName = this._getWallAsset(wallDef.type, wallDef.direction);
                    if (assetName) {
                        const sprite = this._createSprite('wall', assetName, 0, wallDef.gy, { layer: 10 });
                        if (sprite) {
                            this.scene.add(sprite);
                            this.wallSegments.push(sprite);
                        }
                    }
                }
            }

            debugLog(`Created ${this.wallSegments.length} wall segments`);
        }

        /**
         * Get wall asset name from type and direction
         * @private
         */
        _getWallAsset(type, direction) {
            const mapping = WALL_ASSET_MAP[type];
            if (!mapping) {
                console.warn(`Unknown wall type: ${type}`);
                return null;
            }
            return mapping[direction] || mapping['S'];
        }

        /**
         * Build furniture
         * @private
         */
        _buildFurniture(Layout) {
            const FURNITURE = Layout.FURNITURE;
            if (!FURNITURE) return;

            for (const item of FURNITURE) {
                const sprite = this._createSprite(item.type, item.asset, item.gridX, item.gridY, { layer: 5 });
                if (sprite) {
                    this.scene.add(sprite);
                    this.furnitureItems.push(sprite);
                }
            }

            debugLog(`Created ${this.furnitureItems.length} furniture items`);
        }

        // ==================== Character Management ====================
        /**
         * Add a character to the scene
         * @private
         */
        async _addCharacter(session) {
            const sessionId = session.session_id;
            if (this.characters.has(sessionId)) return;

            // Get variant from session or random
            const variant = session.variant || Math.floor(Math.random() * 12);

            // Spawn at entrance
            const Layout = window.Playground.Layout;
            const entrance = Layout?.ENTRANCE || { gridX: 4, gridY: 5 };

            if (this.characterSystem) {
                const character = this.characterSystem.createCharacter(sessionId, variant, entrance.gridX, entrance.gridY);
                if (character) {
                    this.characters.set(sessionId, {
                        session,
                        character,
                        gridX: entrance.gridX,
                        gridY: entrance.gridY
                    });

                    // Register with behavior manager
                    if (this.behaviorManager) {
                        this.behaviorManager.registerCharacter(sessionId, entrance.gridX, entrance.gridY);

                        // Find and move to seat
                        const seat = this.behaviorManager._findAvailableSeat();
                        if (seat) {
                            this.behaviorManager.moveToPosition(sessionId, seat.gridX, seat.gridY);
                        }
                    }

                    debugLog(`Added character ${sessionId.substring(0, 8)} at entrance`);
                }
            } else {
                // Fallback: create a simple placeholder sprite
                const sprite = this._createSprite('decor', 'displayCaseBooks_E', entrance.gridX, entrance.gridY, { layer: 20 });
                if (sprite) {
                    this.scene.add(sprite);
                    this.characters.set(sessionId, {
                        session,
                        sprite,
                        gridX: entrance.gridX,
                        gridY: entrance.gridY
                    });
                    debugLog(`Added placeholder for ${sessionId.substring(0, 8)}`);
                }
            }
        }

        /**
         * Remove a character from the scene
         * @private
         */
        _removeCharacter(sessionId) {
            const data = this.characters.get(sessionId);
            if (!data) return;

            if (this.characterSystem && data.character) {
                this.characterSystem.removeCharacter(sessionId);
            }

            if (data.sprite) {
                this.scene.remove(data.sprite);
                data.sprite.material.dispose();
            }

            if (this.behaviorManager) {
                this.behaviorManager.unregisterCharacter(sessionId);
            }

            this.characters.delete(sessionId);
            debugLog(`Removed character ${sessionId.substring(0, 8)}`);
        }

        /**
         * Sync sessions with the scene
         * @param {Array} sessions - Array of session objects
         */
        async syncSessions(sessions) {
            if (!this.isInitialized) return;

            const sessionIds = new Set(sessions.map(s => s.session_id));

            // Remove characters for disconnected sessions
            for (const sessionId of this.characters.keys()) {
                if (!sessionIds.has(sessionId)) {
                    this._removeCharacter(sessionId);
                }
            }

            // Add new characters
            for (const session of sessions) {
                if (!this.characters.has(session.session_id)) {
                    await this._addCharacter(session);
                }
            }

            debugLog(`Synced ${sessions.length} sessions, ${this.characters.size} characters active`);
        }

        // ==================== Game Loop ====================
        /**
         * Main game loop
         * @private
         */
        _gameLoop(timestamp) {
            if (!this.running) return;

            const deltaTime = timestamp - this.lastFrameTime;
            this.lastFrameTime = timestamp;

            // Update character system (animations)
            if (this.characterSystem) {
                this.characterSystem.update(deltaTime);
            }

            // Update behavior manager
            if (this.behaviorManager) {
                this.behaviorManager.update(deltaTime);

                // Update character positions based on behavior
                for (const [sessionId, data] of this.characters) {
                    const behaviorData = this.behaviorManager.characters.get(sessionId);
                    if (behaviorData && this.characterSystem) {
                        // Update position
                        this.characterSystem.setPosition(sessionId, behaviorData.currentGridX, behaviorData.currentGridY);
                        data.gridX = behaviorData.currentGridX;
                        data.gridY = behaviorData.currentGridY;
                    }
                }
            }

            // Smooth zoom
            if (Math.abs(this.zoom - this.targetZoom) > 0.01) {
                this.zoom += (this.targetZoom - this.zoom) * 0.1;
                this._updateCameraZoom();
            }

            // Smooth camera pan
            const panDx = this.targetCameraOffset.x - this.cameraOffset.x;
            const panDy = this.targetCameraOffset.y - this.cameraOffset.y;
            if (Math.abs(panDx) > 0.001 || Math.abs(panDy) > 0.001) {
                this.cameraOffset.x += panDx * 0.15;
                this.cameraOffset.y += panDy * 0.15;
                this.camera.position.x = this.cameraOffset.x;
                this.camera.position.y = this.cameraOffset.y;
            }

            // Render
            this.renderer.render(this.scene, this.camera);

            // Schedule next frame
            this.animationFrameId = requestAnimationFrame((t) => this._gameLoop(t));
        }

        /**
         * Update camera zoom
         * @private
         */
        _updateCameraZoom() {
            const aspect = this.container.clientWidth / this.container.clientHeight;
            const height = this.frustumHeight / this.zoom;
            const width = height * aspect;

            this.camera.left = -width / 2;
            this.camera.right = width / 2;
            this.camera.top = height / 2;
            this.camera.bottom = -height / 2;
            this.camera.updateProjectionMatrix();
        }

        // ==================== Public API ====================
        /**
         * Zoom in
         */
        zoomIn() {
            this.targetZoom = Math.min(this.targetZoom * 1.2, 3.0);
        }

        /**
         * Zoom out
         */
        zoomOut() {
            this.targetZoom = Math.max(this.targetZoom / 1.2, 0.5);
        }

        /**
         * Reset view
         */
        resetView() {
            this.targetZoom = 1.0;
            // Calculate center position and smoothly pan there
            const Layout = window.Playground.Layout;
            if (Layout) {
                const centerGX = Layout.ROOM.WIDTH / 2;
                const centerGY = Layout.ROOM.HEIGHT / 2;
                const center = this.gridToScreen(centerGX, centerGY);
                this.targetCameraOffset = { x: -center.x, y: -center.y };
            }
        }

        /**
         * Notify character of request start (for working animation)
         */
        notifyRequestStart(sessionId) {
            if (this.behaviorManager) {
                this.behaviorManager.startWorking(sessionId);
            }
            if (this.characterSystem) {
                this.characterSystem.setAnimState(sessionId, 'thinking');
            }
        }

        /**
         * Notify character of request end
         */
        notifyRequestEnd(sessionId, success) {
            if (this.behaviorManager) {
                this.behaviorManager.stopWorking(sessionId, success);
            }
            if (this.characterSystem) {
                this.characterSystem.setAnimState(sessionId, 'idle');
            }
        }

        // ==================== Resize and Cleanup ====================
        /**
         * Handle window resize
         * @private
         */
        _onResize() {
            if (!this.container || !this.renderer) return;

            const width = this.container.clientWidth;
            const height = this.container.clientHeight;

            this.renderer.setSize(width, height);
            this._updateCameraZoom();
        }

        /**
         * Destroy the scene and clean up resources
         */
        destroy() {
            this.running = false;

            if (this.animationFrameId) {
                cancelAnimationFrame(this.animationFrameId);
            }

            window.removeEventListener('resize', this._resizeHandler);

            // Remove input event listeners
            if (this.renderer && this.renderer.domElement) {
                const canvas = this.renderer.domElement;
                canvas.removeEventListener('mousedown', this._onPointerDown);
                canvas.removeEventListener('mousemove', this._onPointerMove);
                canvas.removeEventListener('mouseup', this._onPointerUp);
                canvas.removeEventListener('mouseleave', this._onPointerLeave);
            }

            // Dispose floor tiles
            for (const tile of this.floorTiles) {
                this.scene.remove(tile);
                tile.material.dispose();
            }
            this.floorTiles = [];

            // Dispose walls
            for (const wall of this.wallSegments) {
                this.scene.remove(wall);
                wall.material.dispose();
            }
            this.wallSegments = [];

            // Dispose furniture
            for (const item of this.furnitureItems) {
                this.scene.remove(item);
                item.material.dispose();
            }
            this.furnitureItems = [];

            // Remove characters
            for (const sessionId of this.characters.keys()) {
                this._removeCharacter(sessionId);
            }

            // Dispose renderer
            if (this.renderer) {
                this.renderer.dispose();
                if (this.container && this.renderer.domElement) {
                    this.container.removeChild(this.renderer.domElement);
                }
            }

            this.isInitialized = false;
            debugLog('Scene destroyed');
        }
    }

    // Create singleton instance
    window.Playground.Scene = new PlaygroundScene();

})();
