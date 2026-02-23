/**
 * City 3D Scene Manager
 * Full 3D city rendering with buildings and roads
 */
(function() {
    'use strict';

    window.Playground = window.Playground || {};

    const DEBUG = true;
    function debugLog(...args) {
        if (DEBUG) console.log('[City3DScene]', ...args);
    }

    // ==================== Scene Configuration ====================
    const SCENE_CONFIG = {
        backgroundColor: 0x9DD5F5,  // Softer pastel sky blue
        groundColor: 0x5B8C5A,      // Softer pastel green grass
        ambientLightIntensity: 0.5,
        directionalLightIntensity: 1.2,
        fillLightIntensity: 0.4,
        cameraFov: 45,
        cameraNear: 0.1,
        cameraFar: 200,
        // Tone mapping for that soft pastel look
        toneMapping: THREE.ACESFilmicToneMapping,
        toneMappingExposure: 1.3,
        // Sky background image path (JPG is lighter than HDR)
        skyImagePath: '/static/assets/kloofendal_48d_partly_cloudy_puresky_4k.jpg'
    };

    // ==================== PlaygroundScene3D Class ====================
    class PlaygroundScene3D {
        constructor() {
            // Core Three.js components
            this.renderer = null;
            this.scene = null;
            this.camera = null;

            // Systems
            this.assetLoader = null;
            this.avatarSystem = null;

            // Scene elements
            this.groundTiles = [];
            this.roads = [];
            this.buildings = [];
            this.natureItems = [];

            // State
            this.running = false;
            this.container = null;
            this.animationFrameId = null;
            this.lastFrameTime = 0;

            // Camera control state
            this.cameraAngle = Math.PI / 4;      // 45 degrees horizontal
            this.cameraPitch = Math.PI / 5;      // ~36 degrees vertical
            this.cameraDistance = 38;            // Increased for larger 21x21 city
            this.cameraTarget = new THREE.Vector3(10, 0, 10);  // Center of 21x21 city

            // Pan drag (left mouse)
            this.isPanning = false;
            this._panStart = { x: 0, y: 0 };
            this._targetStart = new THREE.Vector3();

            // Rotation drag (right mouse)
            this.isRotating = false;
            this._rotateStart = { x: 0, y: 0 };
            this._angleStart = 0;
            this._pitchStart = 0;

            // For app.js compatibility
            this.isInitialized = false;

            debugLog('PlaygroundScene3D instance created');
        }

        static getInstance() {
            return window.Playground.Scene;
        }

        async mount(container) {
            debugLog('Mounting City 3D scene...');

            this.container = container;
            const width = container.clientWidth;
            const height = container.clientHeight;

            // Create WebGL Renderer with enhanced quality
            this.renderer = new THREE.WebGLRenderer({
                antialias: true,
                alpha: false,
                powerPreference: 'high-performance'
            });
            this.renderer.setSize(width, height);
            this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
            this.renderer.shadowMap.enabled = true;
            this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

            // Enhanced rendering quality for pastel look
            this.renderer.outputColorSpace = THREE.SRGBColorSpace;
            this.renderer.toneMapping = SCENE_CONFIG.toneMapping;
            this.renderer.toneMappingExposure = SCENE_CONFIG.toneMappingExposure;

            container.appendChild(this.renderer.domElement);

            // Create Scene
            this.scene = new THREE.Scene();
            this.scene.background = new THREE.Color(SCENE_CONFIG.backgroundColor);

            // Add soft fog for dreamy atmosphere
            this.scene.fog = new THREE.FogExp2(SCENE_CONFIG.backgroundColor, 0.012);

            // Setup camera
            this._setupCamera(width, height);

            // Setup lighting
            this._setupLighting();

            // Create thick platform for the city
            this._createCityPlatform();

            // Initialize asset loader
            this.assetLoader = new window.Playground.Asset3DLoader();
            this.assetLoader.init();

            // Load essential assets
            await this.assetLoader.loadEssential((loaded, total) => {
                debugLog(`Loading: ${loaded}/${total}`);
            });
            debugLog('Assets loaded');

            // Build the city
            this._buildCity();

            // Initialize avatar system
            await this._initAvatarSystem();

            // Setup input handlers
            this._setupInputHandlers();

            // Add resize handler
            this._resizeHandler = () => this._onResize();
            window.addEventListener('resize', this._resizeHandler);

            // Prevent context menu on right-click
            this.renderer.domElement.addEventListener('contextmenu', (e) => e.preventDefault());

            // Start render loop
            this.running = true;
            this.lastFrameTime = performance.now();
            this._gameLoop(this.lastFrameTime);

            this.isInitialized = true;
            debugLog('City scene mounted and running');
        }

        _setupCamera(width, height) {
            const aspect = width / height;

            this.camera = new THREE.PerspectiveCamera(
                SCENE_CONFIG.cameraFov,
                aspect,
                SCENE_CONFIG.cameraNear,
                SCENE_CONFIG.cameraFar
            );

            this._updateCameraPosition();
            debugLog('Camera setup complete');
        }

        _updateCameraPosition() {
            const x = this.cameraTarget.x + this.cameraDistance * Math.cos(this.cameraPitch) * Math.sin(this.cameraAngle);
            const y = this.cameraTarget.y + this.cameraDistance * Math.sin(this.cameraPitch);
            const z = this.cameraTarget.z + this.cameraDistance * Math.cos(this.cameraPitch) * Math.cos(this.cameraAngle);

            this.camera.position.set(x, y, z);
            this.camera.lookAt(this.cameraTarget);
        }

        _setupLighting() {
            // Soft ambient light with warm tint
            const ambient = new THREE.AmbientLight(0xFFF5E6, SCENE_CONFIG.ambientLightIntensity);
            this.scene.add(ambient);

            // Main directional light (sun) - warm white
            const sun = new THREE.DirectionalLight(0xFFFAF0, SCENE_CONFIG.directionalLightIntensity);
            sun.position.set(20, 30, 15);
            sun.castShadow = true;

            // Enhanced shadow settings for softer shadows
            sun.shadow.mapSize.width = 4096;
            sun.shadow.mapSize.height = 4096;
            sun.shadow.camera.near = 1;
            sun.shadow.camera.far = 80;
            sun.shadow.camera.left = -30;
            sun.shadow.camera.right = 30;
            sun.shadow.camera.top = 30;
            sun.shadow.camera.bottom = -30;
            sun.shadow.bias = -0.0003;
            sun.shadow.normalBias = 0.02;
            sun.shadow.radius = 2;  // Soft shadow edges

            this.scene.add(sun);
            this.sunLight = sun;

            // Fill light from opposite side (cooler tone)
            const fill = new THREE.DirectionalLight(0xE6F0FF, SCENE_CONFIG.fillLightIntensity);
            fill.position.set(-15, 15, -10);
            this.scene.add(fill);

            // Hemisphere light for natural sky/ground bounce
            const hemi = new THREE.HemisphereLight(0xB4D7FF, 0x80C080, 0.4);
            this.scene.add(hemi);

            // Load sky background image
            this._loadSkyBackground();

            debugLog('Lighting setup complete');
        }

        _loadSkyBackground() {
            const textureLoader = new THREE.TextureLoader();
            textureLoader.load(
                SCENE_CONFIG.skyImagePath,
                (texture) => {
                    texture.mapping = THREE.EquirectangularReflectionMapping;
                    this.scene.background = texture;
                    this.scene.environment = texture;  // Also use for reflections
                    debugLog('Sky background loaded');
                },
                undefined,
                (err) => {
                    debugLog('Sky background load failed:', err.message);
                }
            );
        }

        _createGround() {
            // Legacy - not used
        }

        _createCityPlatform() {
            // Create a thick platform/island for the city to sit on
            const platformWidth = 24;   // Slightly larger than 21x21 city
            const platformDepth = 24;
            const platformHeight = 2;   // Thick base

            // Main platform box - positioned so top is at y=-0.02 (just below tiles)
            const platformGeo = new THREE.BoxGeometry(platformWidth, platformHeight, platformDepth);
            const platformMat = new THREE.MeshStandardMaterial({
                color: 0x4A5568,  // Dark gray concrete look
                roughness: 0.9,
                metalness: 0.1
            });
            const platform = new THREE.Mesh(platformGeo, platformMat);
            platform.position.set(10, -platformHeight / 2 - 0.02, 10);  // Top surface at y=-0.02
            platform.receiveShadow = true;
            platform.castShadow = true;
            this.scene.add(platform);

            debugLog('City platform created');
        }

        _buildCity() {
            const Layout = window.Playground.Layout3D;
            if (!Layout) {
                console.error('Layout3D not available');
                return;
            }

            debugLog('Building city...');

            // Build ground tiles (under buildings/parks)
            this._buildGroundTiles(Layout);

            // Build roads
            this._buildRoads(Layout);

            // Build buildings
            this._buildBuildings(Layout);

            // Build nature
            this._buildNature(Layout);

            debugLog('City build complete');
        }

        _buildGroundTiles(Layout) {
            const tiles = Layout.getGroundTiles();

            for (const tile of tiles) {
                const model = this.assetLoader.getModel(tile.type, tile.name);
                if (model) {
                    model.position.set(tile.gx, 0, tile.gz);
                    model.rotation.y = tile.rotation || 0;
                    model.receiveShadow = true;
                    this.scene.add(model);
                    this.groundTiles.push(model);
                } else if (tile.isGround) {
                    // Fallback: create simple green tile if model not loaded
                    const fallbackGeo = new THREE.PlaneGeometry(1, 1);
                    const fallbackMat = new THREE.MeshLambertMaterial({ color: 0x4a7c3f });
                    const fallback = new THREE.Mesh(fallbackGeo, fallbackMat);
                    fallback.rotation.x = -Math.PI / 2;
                    fallback.position.set(tile.gx + 0.5, 0.001, tile.gz + 0.5);
                    fallback.receiveShadow = true;
                    this.scene.add(fallback);
                    this.groundTiles.push(fallback);
                }
            }

            debugLog(`Created ${this.groundTiles.length} ground tiles`);
        }

        _buildRoads(Layout) {
            const roads = Layout.getRoads();

            for (const road of roads) {
                const model = this.assetLoader.getModel(road.type, road.name);
                if (model) {
                    model.position.set(road.gx, 0, road.gz);
                    model.rotation.y = road.rotation || 0;
                    model.receiveShadow = true;
                    this.scene.add(model);
                    this.roads.push(model);
                }
            }

            debugLog(`Created ${this.roads.length} road segments`);
        }

        _buildBuildings(Layout) {
            const buildings = Layout.BUILDINGS;

            for (let i = 0; i < buildings.length; i++) {
                const building = buildings[i];
                const model = this.assetLoader.getModel(building.type, building.name);
                if (model) {
                    model.position.set(building.gx, 0, building.gz);
                    model.rotation.y = building.rotation || 0;
                    model.castShadow = true;
                    model.receiveShadow = true;
                    this.scene.add(model);
                    this.buildings.push(model);
                }
            }

            debugLog(`Created ${this.buildings.length} buildings`);
        }

        _buildNature(Layout) {
            const nature = Layout.NATURE;

            for (const item of nature) {
                const model = this.assetLoader.getModel(item.type, item.name);
                if (model) {
                    // Support fractional positions for natural placement
                    // Support optional y offset for items that need height adjustment
                    model.position.set(item.gx, item.y || 0, item.gz);
                    model.rotation.y = item.rotation || 0;

                    // Support optional scale for variety
                    if (item.scale) {
                        model.scale.setScalar(item.scale);
                    }

                    model.castShadow = true;
                    model.receiveShadow = true;
                    this.scene.add(model);
                    this.natureItems.push(model);
                } else {
                    console.warn(`[City3DScene] Nature model not found: ${item.type}/${item.name}`);
                }
            }

            debugLog(`Created ${this.natureItems.length} nature items`);
        }

        _setupInputHandlers() {
            const canvas = this.renderer.domElement;

            // Raycaster for avatar click detection
            this._raycaster = new THREE.Raycaster();
            this._mouse = new THREE.Vector2();

            // Mouse down
            this._onPointerDown = (e) => {
                if (e.button === 0) {
                    // Left mouse - pan
                    this.isPanning = true;
                    this._panStart = { x: e.clientX, y: e.clientY };
                    this._clickStart = { x: e.clientX, y: e.clientY }; // For click detection
                    this._targetStart.copy(this.cameraTarget);
                    canvas.style.cursor = 'move';
                } else if (e.button === 2) {
                    // Right mouse - rotate
                    this.isRotating = true;
                    this._rotateStart = { x: e.clientX, y: e.clientY };
                    this._angleStart = this.cameraAngle;
                    this._pitchStart = this.cameraPitch;
                    canvas.style.cursor = 'grabbing';
                }
            };

            // Mouse move
            this._onPointerMove = (e) => {
                if (this.isRotating) {
                    const dx = e.clientX - this._rotateStart.x;
                    const dy = e.clientY - this._rotateStart.y;

                    this.cameraAngle = this._angleStart - dx * 0.005;
                    this.cameraPitch = Math.max(0.1, Math.min(Math.PI / 2.2, this._pitchStart + dy * 0.005));

                    this._updateCameraPosition();
                }

                if (this.isPanning) {
                    const dx = e.clientX - this._panStart.x;
                    const dy = e.clientY - this._panStart.y;

                    // Calculate pan direction based on camera angle
                    const panSpeed = 0.02 * (this.cameraDistance / 15);

                    // Right vector (perpendicular to camera direction in XZ plane)
                    const rightX = Math.cos(this.cameraAngle);
                    const rightZ = -Math.sin(this.cameraAngle);

                    // Forward vector (in XZ plane)
                    const forwardX = Math.sin(this.cameraAngle);
                    const forwardZ = Math.cos(this.cameraAngle);

                    this.cameraTarget.x = this._targetStart.x - dx * rightX * panSpeed - dy * forwardX * panSpeed;
                    this.cameraTarget.z = this._targetStart.z - dx * rightZ * panSpeed - dy * forwardZ * panSpeed;

                    this._updateCameraPosition();
                }
            };

            // Mouse up
            this._onPointerUp = (e) => {
                // Check for click (not drag) on left mouse button
                if (e.button === 0 && this._clickStart) {
                    const dx = e.clientX - this._clickStart.x;
                    const dy = e.clientY - this._clickStart.y;
                    const dist = Math.sqrt(dx * dx + dy * dy);

                    // If mouse moved less than 5px, treat as click
                    if (dist < 5) {
                        this._handleAvatarClick(e);
                    }
                    this._clickStart = null;
                }

                if (e.button === 0) {
                    this.isPanning = false;
                } else if (e.button === 2) {
                    this.isRotating = false;
                }

                if (!this.isRotating && !this.isPanning) {
                    canvas.style.cursor = 'grab';
                }
            };

            // Mouse leave
            this._onPointerLeave = () => {
                this.isRotating = false;
                this.isPanning = false;
                canvas.style.cursor = 'grab';
            };

            // Mouse wheel - zoom
            this._onWheel = (e) => {
                e.preventDefault();
                const zoomDelta = e.deltaY > 0 ? 1.1 : 0.9;
                this.cameraDistance = Math.max(8, Math.min(40, this.cameraDistance * zoomDelta));
                this._updateCameraPosition();
            };

            // Set initial cursor
            canvas.style.cursor = 'grab';

            // Add event listeners
            canvas.addEventListener('mousedown', this._onPointerDown);
            canvas.addEventListener('mousemove', this._onPointerMove);
            canvas.addEventListener('mouseup', this._onPointerUp);
            canvas.addEventListener('mouseleave', this._onPointerLeave);
            canvas.addEventListener('wheel', this._onWheel, { passive: false });

            debugLog('Input handlers setup complete');
        }

        /**
         * Handle click on avatar
         * @private
         */
        _handleAvatarClick(e) {
            if (!this.avatarSystem || !this.avatarSystem.avatars) return;

            const rect = this.renderer.domElement.getBoundingClientRect();
            this._mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
            this._mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

            this._raycaster.setFromCamera(this._mouse, this.camera);

            // Collect all avatar meshes
            const avatarMeshes = [];
            for (const [sessionId, avatarData] of this.avatarSystem.avatars) {
                if (avatarData.container) {
                    avatarData.container.traverse((child) => {
                        if (child.isMesh) {
                            child.userData.sessionId = sessionId;
                            avatarMeshes.push(child);
                        }
                    });
                }
            }

            const intersects = this._raycaster.intersectObjects(avatarMeshes, false);

            if (intersects.length > 0) {
                const sessionId = intersects[0].object.userData.sessionId;
                if (sessionId) {
                    debugLog('Avatar clicked:', sessionId);
                    document.dispatchEvent(new CustomEvent('playground-avatar-click', {
                        detail: { sessionId }
                    }));
                }
            }
        }

        _onResize() {
            if (!this.container) return;

            const width = this.container.clientWidth;
            const height = this.container.clientHeight;

            this.camera.aspect = width / height;
            this.camera.updateProjectionMatrix();

            this.renderer.setSize(width, height);
        }

        _gameLoop(timestamp) {
            if (!this.running) return;

            const deltaTime = timestamp - this.lastFrameTime;
            this.lastFrameTime = timestamp;

            // Update avatar system
            if (this.avatarSystem) {
                this.avatarSystem.update(deltaTime);
            }

            // Render
            this.renderer.render(this.scene, this.camera);

            // Next frame
            this.animationFrameId = requestAnimationFrame((t) => this._gameLoop(t));
        }

        async _initAvatarSystem() {
            if (!window.Playground.AvatarSystem) {
                console.warn('[City3DScene] AvatarSystem not available');
                return;
            }

            this.avatarSystem = new window.Playground.AvatarSystem();
            await this.avatarSystem.init(this.scene);
            debugLog('Avatar system initialized');
        }

        // ==================== Public API ====================

        syncSessions(sessions) {
            if (!this.isInitialized) return;

            // Sync with avatar system
            if (this.avatarSystem) {
                this.avatarSystem.syncSessions(sessions);
            }

            debugLog(`syncSessions called with ${sessions.length} sessions`);
        }

        notifyRequestStart(sessionId) {
            debugLog(`Request started for ${sessionId.substring(0, 8)}`);

            // Mark avatar as processing
            if (this.avatarSystem) {
                this.avatarSystem.setProcessing(sessionId, true);
            }
        }

        notifyRequestComplete(sessionId) {
            debugLog(`Request completed for ${sessionId.substring(0, 8)}`);

            // Mark avatar as done processing
            if (this.avatarSystem) {
                this.avatarSystem.setProcessing(sessionId, false);
            }
        }

        notifyRequestEnd(sessionId, success) {
            debugLog(`Request ended for ${sessionId.substring(0, 8)}: ${success ? 'success' : 'failed'}`);

            // Mark avatar as done processing
            if (this.avatarSystem) {
                this.avatarSystem.setProcessing(sessionId, false);
            }
        }

        zoomIn() {
            this.cameraDistance = Math.max(8, this.cameraDistance * 0.8);
            this._updateCameraPosition();
        }

        zoomOut() {
            this.cameraDistance = Math.min(60, this.cameraDistance * 1.2);
            this._updateCameraPosition();
        }

        resetView() {
            this.cameraAngle = Math.PI / 4;
            this.cameraPitch = Math.PI / 5;
            this.cameraDistance = 38;
            this.cameraTarget.set(10, 0, 10);  // Center of 21x21 city
            this._updateCameraPosition();
        }

        /**
         * Pause the render loop (when tab is hidden).
         * Lightweight — keeps Three.js context alive, just stops rAF.
         */
        pause() {
            if (!this.running) return;
            this.running = false;
            if (this.animationFrameId) {
                cancelAnimationFrame(this.animationFrameId);
                this.animationFrameId = null;
            }
        }

        /**
         * Resume the render loop (when tab becomes visible).
         */
        resume() {
            if (this.running) return;          // already running
            if (!this.isInitialized) return;   // never mounted
            this.running = true;
            this.lastFrameTime = performance.now();
            this.animationFrameId = requestAnimationFrame((t) => this._gameLoop(t));
        }

        destroy() {
            this.running = false;

            if (this.animationFrameId) {
                cancelAnimationFrame(this.animationFrameId);
            }

            window.removeEventListener('resize', this._resizeHandler);

            // Remove input handlers
            if (this.renderer && this.renderer.domElement) {
                const canvas = this.renderer.domElement;
                canvas.removeEventListener('mousedown', this._onPointerDown);
                canvas.removeEventListener('mousemove', this._onPointerMove);
                canvas.removeEventListener('mouseup', this._onPointerUp);
                canvas.removeEventListener('mouseleave', this._onPointerLeave);
                canvas.removeEventListener('wheel', this._onWheel);
            }

            // Dispose scene objects
            const disposeList = [...this.groundTiles, ...this.roads, ...this.buildings, ...this.natureItems];
            for (const obj of disposeList) {
                this._disposeObject(obj);
            }
            this.groundTiles = [];
            this.roads = [];
            this.buildings = [];
            this.natureItems = [];

            // Dispose asset loader
            if (this.assetLoader) {
                this.assetLoader.dispose();
            }

            // Dispose avatar system
            if (this.avatarSystem) {
                this.avatarSystem.dispose();
                this.avatarSystem = null;
            }

            // Dispose renderer
            if (this.renderer) {
                this.renderer.dispose();
                if (this.container && this.renderer.domElement) {
                    this.container.removeChild(this.renderer.domElement);
                }
            }

            this.isInitialized = false;
            debugLog('City scene destroyed');
        }

        _disposeObject(object) {
            this.scene.remove(object);
            object.traverse((child) => {
                if (child.geometry) child.geometry.dispose();
                if (child.material) {
                    if (Array.isArray(child.material)) {
                        child.material.forEach(m => m.dispose());
                    } else {
                        child.material.dispose();
                    }
                }
            });
        }
    }

    // Create singleton instance
    window.Playground.Scene = new PlaygroundScene3D();
    window.Playground.PlaygroundScene3D = PlaygroundScene3D;

    debugLog('City3DScene module loaded');

})();
