/**
 * Playground Scene Manager - Three.js Isometric Library Scene
 * Core controller for the entire isometric library visualization
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
            this.characterAnimator = null;

            // Character management
            this.characters = new Map(); // sessionId -> characterData
            this.behaviorManager = null; // Will implement behavior

            // State
            this.running = false;
            this.container = null;
            this.animationFrameId = null;
            this.lastFrameTime = 0;

            // Scene elements storage for cleanup
            this.floorTiles = [];
            this.wallSegments = [];
            this.furnitureItems = [];

            // Camera zoom state
            this.zoom = 1.0;
            this.targetZoom = 1.0;

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
            this.renderer.sortObjects = true; // Enable render order sorting
            container.appendChild(this.renderer.domElement);

            // Create Scene with dark brown background
            this.scene = new THREE.Scene();
            this.scene.background = new THREE.Color(0x2a1a0a);

            // Create isometric OrthographicCamera
            this._setupCamera(width, height);

            // Add lighting
            this._setupLighting();

            // Initialize AssetLoader and load all assets
            this.assetLoader = new window.Playground.AssetLoader();
            await this.assetLoader.loadAll((loaded, total, url) => {
                debugLog(`Loading assets: ${loaded}/${total}`);
            });
            debugLog('All assets loaded');

            // Initialize CharacterAnimator3D (from CompanyView)
            if (window.CompanyView && window.CompanyView.CharacterAnimator3D) {
                this.characterAnimator = new window.CompanyView.CharacterAnimator3D();
                await this.characterAnimator.init();
                debugLog('CharacterAnimator3D initialized');
            } else {
                debugLog('Warning: CharacterAnimator3D not available');
            }

            // Build the room
            this._buildRoom();

            // Add resize handler
            this._resizeHandler = () => this._onResize();
            window.addEventListener('resize', this._resizeHandler);

            // Start game loop
            this.running = true;
            this.lastFrameTime = performance.now();
            this._gameLoop(this.lastFrameTime);

            // Mark as initialized
            this.isInitialized = true;

            debugLog('Scene mounted and running');
        }

        /**
         * Setup the isometric orthographic camera
         * @private
         */
        _setupCamera(width, height) {
            const frustumSize = 6;
            const aspect = width / height;

            this.camera = new THREE.OrthographicCamera(
                -frustumSize * aspect / 2,
                frustumSize * aspect / 2,
                frustumSize / 2,
                -frustumSize / 2,
                0.1,
                100
            );

            // Isometric camera angle: 45° rotation around Y, ~35.26° pitch (atan(1/√2))
            const distance = 10;
            const isoAngle = Math.PI / 4; // 45 degrees
            const isoPitch = Math.atan(1 / Math.sqrt(2)); // ~35.26 degrees

            this.camera.position.set(
                distance * Math.cos(isoAngle) * Math.cos(isoPitch),
                distance * Math.sin(isoPitch),
                distance * Math.sin(isoAngle) * Math.cos(isoPitch)
            );

            this.camera.lookAt(0, 0, 0);
            this.camera.updateProjectionMatrix();

            debugLog('Camera setup complete', {
                position: this.camera.position,
                frustumSize,
                aspect
            });
        }

        /**
         * Setup scene lighting
         * @private
         */
        _setupLighting() {
            // Ambient light for overall illumination
            const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
            this.scene.add(ambientLight);

            // Directional light for shadows and depth
            const directionalLight = new THREE.DirectionalLight(0xffffff, 0.5);
            directionalLight.position.set(3, 8, 5);
            this.scene.add(directionalLight);

            debugLog('Lighting setup complete');
        }

        /**
         * Build the room from layout data
         * @private
         */
        _buildRoom() {
            const Layout = window.Playground.Layout;
            const SpritePlane = window.Playground.SpritePlane;

            if (!Layout || !SpritePlane) {
                console.error('Layout or SpritePlane not available');
                return;
            }

            debugLog('Building room...', {
                width: Layout.ROOM.WIDTH,
                height: Layout.ROOM.HEIGHT
            });

            // Build floor tiles
            this._buildFloor(Layout, SpritePlane);

            // Build walls
            this._buildWalls(Layout, SpritePlane);

            // Build furniture
            this._buildFurniture(Layout, SpritePlane);

            debugLog('Room build complete');
        }

        /**
         * Build floor tiles
         * @private
         */
        _buildFloor(Layout, SpritePlane) {
            const ROOM = Layout.ROOM;

            for (let gx = 0; gx < ROOM.WIDTH; gx++) {
                for (let gy = 0; gy < ROOM.HEIGHT; gy++) {
                    const tile = SpritePlane.create(
                        this.assetLoader,
                        'floor',
                        'stone_E',
                        gx,
                        gy,
                        { layerOffset: 0 }
                    );

                    if (tile) {
                        tile.addToScene(this.scene);
                        this.floorTiles.push(tile);
                    }
                }
            }

            debugLog(`Created ${this.floorTiles.length} floor tiles`);
        }

        /**
         * Build wall segments
         * @private
         */
        _buildWalls(Layout, SpritePlane) {
            const WALLS = Layout.WALLS;

            // Build back walls (along gy=0)
            if (WALLS.back) {
                for (const wallDef of WALLS.back) {
                    const assetName = this._getWallAsset(wallDef.type, wallDef.direction);

                    const wall = SpritePlane.create(
                        this.assetLoader,
                        'wall',
                        assetName,
                        wallDef.gx,
                        0,
                        { layerOffset: 1 }
                    );

                    if (wall) {
                        wall.addToScene(this.scene);
                        this.wallSegments.push(wall);
                    }
                }
            }

            // Build left walls (along gx=0)
            if (WALLS.left) {
                for (const wallDef of WALLS.left) {
                    const assetName = this._getWallAsset(wallDef.type, wallDef.direction);

                    const wall = SpritePlane.create(
                        this.assetLoader,
                        'wall',
                        assetName,
                        0,
                        wallDef.gy,
                        { layerOffset: 1 }
                    );

                    if (wall) {
                        wall.addToScene(this.scene);
                        this.wallSegments.push(wall);
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
            if (mapping && mapping[direction]) {
                return mapping[direction];
            }
            // Fallback to straight wall
            return direction === 'S' ? 'stone_S' : 'stone_E';
        }

        /**
         * Build furniture items
         * @private
         */
        _buildFurniture(Layout, SpritePlane) {
            const FURNITURE = Layout.FURNITURE;

            for (const item of FURNITURE) {
                const furniture = SpritePlane.create(
                    this.assetLoader,
                    item.type,
                    item.asset,
                    item.gridX,
                    item.gridY,
                    { layerOffset: 2 }
                );

                if (furniture) {
                    furniture.addToScene(this.scene);
                    this.furnitureItems.push(furniture);
                }
            }

            debugLog(`Created ${this.furnitureItems.length} furniture items`);
        }

        /**
         * Main game loop
         * @private
         */
        _gameLoop(timestamp) {
            if (!this.running) return;

            // Calculate delta time
            const deltaTime = (timestamp - this.lastFrameTime) / 1000;
            this.lastFrameTime = timestamp;

            // Update CharacterAnimator3D
            if (this.characterAnimator) {
                this.characterAnimator.update(deltaTime);
            }

            // Update character behaviors
            this._updateBehaviors(deltaTime);

            // Render scene
            this.renderer.render(this.scene, this.camera);

            // Request next frame
            this.animationFrameId = requestAnimationFrame((t) => this._gameLoop(t));
        }

        /**
         * Update character behaviors
         * @private
         */
        _updateBehaviors(deltaTime) {
            // Placeholder for behavior updates
            // Will be implemented with behavior manager
            for (const [sessionId, charData] of this.characters) {
                if (charData.behavior) {
                    // Update behavior logic here
                }
            }
        }

        /**
         * Handle window resize
         * @private
         */
        _onResize() {
            if (!this.container || !this.renderer || !this.camera) return;

            const width = this.container.clientWidth;
            const height = this.container.clientHeight;

            // Update renderer size
            this.renderer.setSize(width, height);

            // Update camera aspect
            const frustumSize = 6;
            const aspect = width / height;

            this.camera.left = -frustumSize * aspect / 2;
            this.camera.right = frustumSize * aspect / 2;
            this.camera.top = frustumSize / 2;
            this.camera.bottom = -frustumSize / 2;
            this.camera.updateProjectionMatrix();

            debugLog('Resized to', width, 'x', height);
        }

        /**
         * Sync sessions - add/remove/update characters
         * @param {Array} sessions - Array of session data
         */
        async syncSessions(sessions) {
            const currentIds = new Set(sessions.map(s => s.sessionId));

            // Remove disconnected characters
            for (const [sessionId, charData] of this.characters) {
                if (!currentIds.has(sessionId)) {
                    this._removeCharacter(sessionId);
                }
            }

            // Add or update characters
            for (const session of sessions) {
                if (!this.characters.has(session.sessionId)) {
                    await this._addCharacter(session);
                } else {
                    this._updateCharacter(session);
                }
            }

            debugLog(`Synced ${sessions.length} sessions, ${this.characters.size} characters active`);
        }

        /**
         * Add a new character
         * @private
         */
        async _addCharacter(session) {
            const Layout = window.Playground.Layout;
            const entrance = Layout.ENTRANCE;

            const charData = {
                sessionId: session.sessionId,
                gridX: entrance.gridX,
                gridY: entrance.gridY,
                state: session.state || 'idle',
                behavior: null,
                mesh: null // Will be sprite or 3D model
            };

            this.characters.set(session.sessionId, charData);
            debugLog('Added character', session.sessionId);
        }

        /**
         * Remove a character
         * @private
         */
        _removeCharacter(sessionId) {
            const charData = this.characters.get(sessionId);
            if (charData) {
                if (charData.mesh) {
                    this.scene.remove(charData.mesh);
                }
                this.characters.delete(sessionId);
                debugLog('Removed character', sessionId);
            }
        }

        /**
         * Update an existing character
         * @private
         */
        _updateCharacter(session) {
            const charData = this.characters.get(session.sessionId);
            if (charData) {
                charData.state = session.state || charData.state;
                // Additional state updates can be added here
            }
        }

        /**
         * Destroy the scene and cleanup resources
         */
        destroy() {
            debugLog('Destroying scene...');

            // Stop game loop
            this.running = false;
            if (this.animationFrameId) {
                cancelAnimationFrame(this.animationFrameId);
                this.animationFrameId = null;
            }

            // Remove resize handler
            if (this._resizeHandler) {
                window.removeEventListener('resize', this._resizeHandler);
                this._resizeHandler = null;
            }

            // Dispose floor tiles
            for (const tile of this.floorTiles) {
                tile.dispose();
            }
            this.floorTiles = [];

            // Dispose wall segments
            for (const wall of this.wallSegments) {
                wall.dispose();
            }
            this.wallSegments = [];

            // Dispose furniture items
            for (const furniture of this.furnitureItems) {
                furniture.dispose();
            }
            this.furnitureItems = [];

            // Clear characters
            for (const [sessionId, charData] of this.characters) {
                if (charData.mesh) {
                    this.scene.remove(charData.mesh);
                }
            }
            this.characters.clear();

            // Dispose renderer
            if (this.renderer) {
                this.renderer.dispose();
                if (this.renderer.domElement && this.renderer.domElement.parentNode) {
                    this.renderer.domElement.parentNode.removeChild(this.renderer.domElement);
                }
                this.renderer = null;
            }

            // Clear scene
            if (this.scene) {
                this.scene.clear();
                this.scene = null;
            }

            this.camera = null;
            this.container = null;

            debugLog('Scene destroyed');
        }

        /**
         * Notify that a request has started for a character
         */
        notifyRequestStart(sessionId) {
            debugLog('Request started:', sessionId);
            // TODO: Show working animation/bubble
        }

        /**
         * Notify that a request has ended for a character
         */
        notifyRequestEnd(sessionId, success) {
            debugLog('Request ended:', sessionId, success ? 'success' : 'failed');
            // TODO: Show success/failure feedback
        }

        /**
         * Zoom in
         */
        zoomIn() {
            this.targetZoom = Math.min(this.targetZoom * 1.2, 3.0);
            this._updateZoom();
        }

        /**
         * Zoom out
         */
        zoomOut() {
            this.targetZoom = Math.max(this.targetZoom / 1.2, 0.5);
            this._updateZoom();
        }

        /**
         * Reset view to default
         */
        resetView() {
            this.targetZoom = 1.0;
            this._updateZoom();
        }

        /**
         * Update camera zoom
         * @private
         */
        _updateZoom() {
            if (!this.camera || !this.container) return;

            this.zoom = this.targetZoom;
            const frustumSize = 6 / this.zoom;
            const aspect = this.container.clientWidth / this.container.clientHeight;

            this.camera.left = -frustumSize * aspect / 2;
            this.camera.right = frustumSize * aspect / 2;
            this.camera.top = frustumSize / 2;
            this.camera.bottom = -frustumSize / 2;
            this.camera.updateProjectionMatrix();

            debugLog('Zoom updated to', this.zoom);
        }

        /**
         * Get the current scene state for debugging
         */
        getDebugInfo() {
            return {
                running: this.running,
                floorTiles: this.floorTiles.length,
                wallSegments: this.wallSegments.length,
                furnitureItems: this.furnitureItems.length,
                characters: this.characters.size,
                assetsLoaded: this.assetLoader ? this.assetLoader.ready : false
            };
        }
    }

    // ==================== Export ====================
    window.Playground.Scene = new PlaygroundScene();

})();
