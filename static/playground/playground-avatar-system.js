/**
 * Playground Avatar System
 * 3D Character management for Claude sessions in the city playground
 *
 * Features:
 * - GLB model loading from kenney_mini-characters
 * - Bone-based procedural animations (idle, walk, run)
 * - A* pathfinding on road tiles only
 * - Direction-based rotation
 * - Random wandering behavior
 * - Session integration
 */
(function() {
    'use strict';

    window.Playground = window.Playground || {};

    const DEBUG = true;
    function debugLog(...args) {
        if (DEBUG) console.log('[AvatarSystem]', ...args);
    }

    // ==================== Configuration ====================
    const AVATAR_CONFIG = {
        // Model paths
        modelBasePath: '/static/assets/kenney_mini-characters/Models/GLB format/',

        // Available character models (5 total — reduced for faster loading)
        characters: [
            'character-female-a', 'character-female-b',
            'character-male-a', 'character-male-b', 'character-male-c',
        ],

        // Model scale (adjusted for city scene)
        modelScale: 0.5,
        modelYOffset: 0.0,  // Y position offset

        // Animation speeds (radians/second)
        animSpeed: {
            idle: 2.0,
            walk: 8.0,
            run: 12.0,
            thinking: 3.0,
        },

        // Bone animation configurations
        boneAnim: {
            idle: {
                torso: { rotX: 0.03, rotZ: 0.01 },
                head: { rotX: 0.04, rotY: 0.06 },
                armLeft: { rotX: 0.08, rotZ: 0.0, phaseOffset: 0 },
                armRight: { rotX: 0.08, rotZ: 0.0, phaseOffset: Math.PI },
                legLeft: { rotX: 0.02, phaseOffset: 0 },
                legRight: { rotX: 0.02, phaseOffset: Math.PI },
            },
            walk: {
                torso: { rotX: 0.06, rotZ: 0.08 },
                head: { rotX: 0.04 },
                armLeft: { rotX: 0.6, rotZ: 0.0, phaseOffset: 0 },
                armRight: { rotX: 0.6, rotZ: 0.0, phaseOffset: Math.PI },
                legLeft: { rotX: 0.5, phaseOffset: Math.PI },
                legRight: { rotX: 0.5, phaseOffset: 0 },
            },
            run: {
                torso: { rotX: 0.1, rotZ: 0.12 },
                head: { rotX: 0.06 },
                armLeft: { rotX: 0.9, rotZ: 0.0, phaseOffset: 0 },
                armRight: { rotX: 0.9, rotZ: 0.0, phaseOffset: Math.PI },
                legLeft: { rotX: 0.8, phaseOffset: Math.PI },
                legRight: { rotX: 0.8, phaseOffset: 0 },
            },
            thinking: {
                torso: { rotX: 0.05 },
                head: { rotX: 0.08, rotY: 0.15 },
                armLeft: { rotX: 0.2, rotZ: 0.0 },
                armRight: { rotX: 1.0, rotZ: 0.2 },  // Hand on chin
                legLeft: { rotX: 0.0 },
                legRight: { rotX: 0.0 },
            },
        },

        // Direction to Y-axis rotation mapping (model faces -Z by default)
        directionRotation: {
            'N': 0,
            'NE': -Math.PI / 4,
            'E': -Math.PI / 2,
            'SE': -Math.PI * 3 / 4,
            'S': Math.PI,
            'SW': Math.PI * 3 / 4,
            'W': Math.PI / 2,
            'NW': Math.PI / 4,
        },

        // Movement configuration
        movement: {
            walkSpeed: 1.5,     // Units per second
            runSpeed: 3.0,      // Units per second
            rotationSpeed: 8.0, // Rotation interpolation speed
        },

        // Wandering behavior
        wander: {
            enabled: true,
            minIdleTime: 3000,   // Minimum time before wandering (ms)
            maxIdleTime: 10000,  // Maximum time before wandering (ms)
            maxWanderDistance: 6, // Maximum grid tiles to wander
        },

        // Name label configuration
        nameLabel: {
            enabled: true,
            fontSize: 24,
            fontFamily: 'Arial, sans-serif',
            backgroundColor: 0x333333,
            textColor: 0xffffff,
            yOffset: 0.8,  // Above character
            scale: 0.005,
        },
    };

    // ==================== Helper Functions ====================

    /**
     * Simple hash function for deterministic avatar assignment
     */
    function simpleHash(str) {
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
            const char = str.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash;
        }
        return Math.abs(hash);
    }

    /**
     * Calculate direction from movement delta
     */
    function calculateDirection(dx, dz) {
        if (dx === 0 && dz === 0) return 'S';

        const angle = Math.atan2(dx, dz);  // x, z for proper orientation
        const deg = (angle * 180 / Math.PI + 360) % 360;

        // Map angle to 8 directions
        if (deg >= 337.5 || deg < 22.5) return 'N';
        if (deg >= 22.5 && deg < 67.5) return 'NW';   // Swapped NE<->NW
        if (deg >= 67.5 && deg < 112.5) return 'W';   // Swapped E<->W
        if (deg >= 112.5 && deg < 157.5) return 'SW'; // Swapped SE<->SW
        if (deg >= 157.5 && deg < 202.5) return 'S';
        if (deg >= 202.5 && deg < 247.5) return 'SE'; // Swapped SW<->SE
        if (deg >= 247.5 && deg < 292.5) return 'E';  // Swapped W<->E
        if (deg >= 292.5 && deg < 337.5) return 'NE'; // Swapped NW<->NE
        return 'S';
    }

    // ==================== AvatarSystem Class ====================
    class AvatarSystem {
        constructor() {
            // Three.js references (set during init)
            this.scene = null;
            this.loader = null;

            // Pathfinding
            this.pathfinder = null;
            this.walkableGrid = null;

            // Model templates (shared across all avatars)
            this.modelTemplates = new Map();  // variant index -> gltf scene

            // Avatar instances
            this.avatars = new Map();  // sessionId -> AvatarData

            // State
            this.ready = false;
            this.lastUpdateTime = 0;

            debugLog('AvatarSystem instance created');
        }

        /**
         * Initialize the avatar system
         * @param {THREE.Scene} scene - The Three.js scene
         */
        async init(scene) {
            debugLog('Initializing avatar system...');

            this.scene = scene;

            // Create GLTF loader
            this.loader = new THREE.GLTFLoader();

            // Initialize pathfinding
            this._initPathfinding();

            // Load all character templates
            await this._loadAllTemplates();

            this.ready = true;
            debugLog('Avatar system ready');
        }

        /**
         * Initialize pathfinding grid from layout
         */
        _initPathfinding() {
            const Layout = window.Playground.Layout3D;
            if (!Layout) {
                console.error('[AvatarSystem] Layout3D not available');
                return;
            }

            const walkableData = Layout.generateWalkableMap();
            this.walkableGrid = new window.Playground.Pathfinding.Grid(
                walkableData.width,
                walkableData.height,
                walkableData.grid
            );
            this.pathfinder = new window.Playground.Pathfinding.Pathfinder(this.walkableGrid);

            // Cache road positions for random wandering
            this.roadPositions = [];
            for (let z = 0; z < walkableData.height; z++) {
                for (let x = 0; x < walkableData.width; x++) {
                    if (walkableData.grid[z][x] === 1) {
                        this.roadPositions.push({ x, z });
                    }
                }
            }

            debugLog(`Pathfinding initialized: ${this.roadPositions.length} walkable tiles`);
        }

        /**
         * Load all character model templates
         */
        async _loadAllTemplates() {
            const total = AVATAR_CONFIG.characters.length;
            let loaded = 0;

            debugLog(`Loading ${total} character templates...`);

            for (let i = 0; i < total; i++) {
                const name = AVATAR_CONFIG.characters[i];
                try {
                    const gltf = await this._loadGLTF(name);
                    this.modelTemplates.set(i, gltf);
                    loaded++;

                    // Debug first model structure
                    if (i === 0 && DEBUG) {
                        this._debugModelStructure(gltf.scene);
                    }
                } catch (error) {
                    console.warn(`[AvatarSystem] Failed to load ${name}:`, error);
                }
            }

            debugLog(`Loaded ${loaded}/${total} character templates`);
        }

        /**
         * Load a single GLTF model
         */
        _loadGLTF(name) {
            return new Promise((resolve, reject) => {
                const url = AVATAR_CONFIG.modelBasePath + name + '.glb';
                this.loader.load(
                    url,
                    (gltf) => resolve(gltf),
                    undefined,
                    (error) => reject(error)
                );
            });
        }

        /**
         * Debug model structure
         */
        _debugModelStructure(scene) {
            console.log('[AvatarSystem] Model structure:');
            scene.traverse((child) => {
                const info = [];
                if (child.isMesh) info.push('Mesh');
                if (child.isSkinnedMesh) info.push('SkinnedMesh');
                if (child.isBone) info.push('Bone');
                console.log(`  - ${child.name} (${child.type}) ${info.join(', ')}`);
            });
        }

        /**
         * Create an avatar for a session
         * @param {string} sessionId - The session ID
         * @param {string} sessionName - Display name for the session
         * @returns {Object} Avatar data
         */
        createAvatar(sessionId, sessionName) {
            if (!this.ready) {
                console.warn('[AvatarSystem] Not ready yet');
                return null;
            }

            if (this.avatars.has(sessionId)) {
                debugLog(`Avatar already exists: ${sessionId.substring(0, 8)}`);
                return this.avatars.get(sessionId);
            }

            // Deterministic character variant based on sessionId
            const hash = simpleHash(sessionId);
            const variant = hash % this.modelTemplates.size;

            // Get template
            const template = this.modelTemplates.get(variant);
            if (!template) {
                console.error('[AvatarSystem] Template not found for variant:', variant);
                return null;
            }

            // Clone model using SkeletonUtils for proper bone support
            let model;
            if (THREE.SkeletonUtils) {
                model = THREE.SkeletonUtils.clone(template.scene);
            } else {
                console.warn('[AvatarSystem] SkeletonUtils not available, animations may not work');
                model = template.scene.clone();
            }

            // Scale and position model
            model.scale.setScalar(AVATAR_CONFIG.modelScale);

            // Cache bone references
            const bones = this._cacheBones(model);

            // Enable shadows
            model.traverse((child) => {
                if (child.isMesh) {
                    child.castShadow = true;
                    child.receiveShadow = true;
                }
            });

            // Find a random spawn position on a road
            const spawnPos = this._getRandomRoadPosition();

            // Create container group for the avatar
            const container = new THREE.Group();
            container.add(model);
            container.position.set(spawnPos.x, AVATAR_CONFIG.modelYOffset, spawnPos.z);

            // Create name label
            const nameLabel = this._createNameLabel(sessionName);
            if (nameLabel) {
                container.add(nameLabel);
            }

            // Add to scene
            this.scene.add(container);

            // Create avatar data
            const avatarData = {
                sessionId,
                sessionName,
                variant,
                container,
                model,
                bones,
                nameLabel,

                // Position (grid coordinates)
                gridX: spawnPos.x,
                gridZ: spawnPos.z,

                // Animation state
                animState: 'idle',
                animPhase: Math.random() * Math.PI * 2,  // Random start phase

                // Direction
                direction: 'S',
                targetDirection: 'S',
                currentRotationY: Math.PI,  // Facing south initially

                // Movement
                path: [],
                pathIndex: 0,
                isMoving: false,

                // Wandering
                idleTimer: 0,
                nextWanderTime: this._getRandomWanderDelay(),

                // Status
                isProcessing: false,  // True when handling a request
            };

            this.avatars.set(sessionId, avatarData);
            debugLog(`Created avatar: ${sessionId.substring(0, 8)} (${sessionName}), variant: ${variant}`);

            return avatarData;
        }

        /**
         * Get a random road position for spawning
         */
        _getRandomRoadPosition() {
            if (this.roadPositions.length === 0) {
                return { x: 8, z: 8 };  // Fallback to center
            }
            const pos = this.roadPositions[Math.floor(Math.random() * this.roadPositions.length)];
            return { x: pos.x, z: pos.z };
        }

        /**
         * Get random wander delay
         */
        _getRandomWanderDelay() {
            const { minIdleTime, maxIdleTime } = AVATAR_CONFIG.wander;
            return minIdleTime + Math.random() * (maxIdleTime - minIdleTime);
        }

        /**
         * Cache bone references from model skeleton
         */
        _cacheBones(model) {
            const bones = {
                root: null,
                torso: null,
                head: null,
                armLeft: null,
                armRight: null,
                legLeft: null,
                legRight: null,
                initialRotations: {},
            };

            // Find skeleton
            let skeleton = null;
            model.traverse((child) => {
                if (child.isSkinnedMesh && child.skeleton && !skeleton) {
                    skeleton = child.skeleton;
                }
            });

            if (skeleton) {
                for (const bone of skeleton.bones) {
                    const name = bone.name.toLowerCase();

                    if (name === 'root') {
                        bones.root = bone;
                        bones.initialRotations.root = bone.rotation.clone();
                    } else if (name === 'torso') {
                        bones.torso = bone;
                        bones.initialRotations.torso = bone.rotation.clone();
                    } else if (name === 'head') {
                        bones.head = bone;
                        bones.initialRotations.head = bone.rotation.clone();
                    } else if (name === 'arm-left') {
                        bones.armLeft = bone;
                        bones.initialRotations.armLeft = bone.rotation.clone();
                    } else if (name === 'arm-right') {
                        bones.armRight = bone;
                        bones.initialRotations.armRight = bone.rotation.clone();
                    } else if (name === 'leg-left') {
                        bones.legLeft = bone;
                        bones.initialRotations.legLeft = bone.rotation.clone();
                    } else if (name === 'leg-right') {
                        bones.legRight = bone;
                        bones.initialRotations.legRight = bone.rotation.clone();
                    }
                }
            } else {
                // Fallback: traverse model directly
                model.traverse((child) => {
                    if (child.isBone) {
                        const name = child.name.toLowerCase();
                        if (name === 'root') {
                            bones.root = child;
                            bones.initialRotations.root = child.rotation.clone();
                        } else if (name === 'torso') {
                            bones.torso = child;
                            bones.initialRotations.torso = child.rotation.clone();
                        } else if (name === 'head') {
                            bones.head = child;
                            bones.initialRotations.head = child.rotation.clone();
                        } else if (name === 'arm-left') {
                            bones.armLeft = child;
                            bones.initialRotations.armLeft = child.rotation.clone();
                        } else if (name === 'arm-right') {
                            bones.armRight = child;
                            bones.initialRotations.armRight = child.rotation.clone();
                        } else if (name === 'leg-left') {
                            bones.legLeft = child;
                            bones.initialRotations.legLeft = child.rotation.clone();
                        } else if (name === 'leg-right') {
                            bones.legRight = child;
                            bones.initialRotations.legRight = child.rotation.clone();
                        }
                    }
                });
            }

            const foundBones = Object.keys(bones).filter(k => k !== 'initialRotations' && bones[k]);
            debugLog(`Cached ${foundBones.length} bones:`, foundBones.join(', '));

            return bones;
        }

        /**
         * Create a name label sprite
         */
        _createNameLabel(name) {
            if (!AVATAR_CONFIG.nameLabel.enabled) return null;

            const config = AVATAR_CONFIG.nameLabel;

            // Create canvas for text
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');

            // Measure text
            ctx.font = `bold ${config.fontSize}px ${config.fontFamily}`;
            const metrics = ctx.measureText(name);
            const textWidth = metrics.width;
            const textHeight = config.fontSize;

            // Set canvas size with padding
            const padding = 12;
            canvas.width = textWidth + padding * 2;
            canvas.height = textHeight + padding;

            // Draw background
            ctx.fillStyle = `#${config.backgroundColor.toString(16).padStart(6, '0')}`;
            ctx.beginPath();
            ctx.roundRect(0, 0, canvas.width, canvas.height, 6);
            ctx.fill();

            // Draw text
            ctx.font = `bold ${config.fontSize}px ${config.fontFamily}`;
            ctx.fillStyle = `#${config.textColor.toString(16).padStart(6, '0')}`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(name, canvas.width / 2, canvas.height / 2);

            // Create sprite
            const texture = new THREE.CanvasTexture(canvas);
            texture.needsUpdate = true;

            const material = new THREE.SpriteMaterial({
                map: texture,
                transparent: true,
                depthTest: false,
            });

            const sprite = new THREE.Sprite(material);

            // Scale sprite
            const scale = config.scale;
            sprite.scale.set(canvas.width * scale, canvas.height * scale, 1);
            sprite.position.y = config.yOffset;

            return sprite;
        }

        /**
         * Remove an avatar
         */
        removeAvatar(sessionId) {
            const avatar = this.avatars.get(sessionId);
            if (!avatar) return;

            // Remove from scene
            this.scene.remove(avatar.container);

            // Dispose resources
            avatar.container.traverse((child) => {
                if (child.geometry) child.geometry.dispose();
                if (child.material) {
                    if (Array.isArray(child.material)) {
                        child.material.forEach(m => m.dispose());
                    } else {
                        child.material.dispose();
                    }
                }
            });

            this.avatars.delete(sessionId);
            debugLog(`Removed avatar: ${sessionId.substring(0, 8)}`);
        }

        /**
         * Update all avatars (called each frame)
         * @param {number} deltaTime - Time since last frame in ms
         */
        update(deltaTime) {
            if (!this.ready) return;

            const dt = deltaTime * 0.001;  // Convert to seconds

            for (const [sessionId, avatar] of this.avatars) {
                // Update movement
                this._updateMovement(avatar, dt);

                // Update animations
                this._updateAnimation(avatar, dt);

                // Update wandering behavior
                this._updateWandering(avatar, deltaTime);

                // Update rotation
                this._updateRotation(avatar, dt);
            }
        }

        /**
         * Update avatar movement along path
         */
        _updateMovement(avatar, dt) {
            if (!avatar.isMoving || avatar.path.length === 0) return;

            const speed = AVATAR_CONFIG.movement.walkSpeed;
            const currentWaypoint = avatar.path[avatar.pathIndex];

            if (!currentWaypoint) {
                this._stopMovement(avatar);
                return;
            }

            // Calculate direction to waypoint
            const dx = currentWaypoint.x - avatar.gridX;
            const dz = currentWaypoint.y - avatar.gridZ;  // Note: pathfinder uses y for z
            const distance = Math.sqrt(dx * dx + dz * dz);

            if (distance < 0.05) {
                // Reached waypoint
                avatar.gridX = currentWaypoint.x;
                avatar.gridZ = currentWaypoint.y;
                avatar.pathIndex++;

                if (avatar.pathIndex >= avatar.path.length) {
                    // Reached destination
                    this._stopMovement(avatar);
                    return;
                }
            } else {
                // Move towards waypoint
                const moveStep = speed * dt;
                const normalizedDx = dx / distance;
                const normalizedDz = dz / distance;

                avatar.gridX += normalizedDx * Math.min(moveStep, distance);
                avatar.gridZ += normalizedDz * Math.min(moveStep, distance);

                // Update target direction based on movement
                avatar.targetDirection = calculateDirection(normalizedDx, normalizedDz);
            }

            // Update container position
            avatar.container.position.x = avatar.gridX;
            avatar.container.position.z = avatar.gridZ;
        }

        /**
         * Stop avatar movement
         */
        _stopMovement(avatar) {
            avatar.isMoving = false;
            avatar.path = [];
            avatar.pathIndex = 0;
            avatar.animState = 'idle';
            avatar.idleTimer = 0;
            avatar.nextWanderTime = this._getRandomWanderDelay();
        }

        /**
         * Update bone-based animation
         */
        _updateAnimation(avatar, dt) {
            const { animState, bones, animPhase } = avatar;
            if (!bones) return;

            // Update animation phase
            const speed = AVATAR_CONFIG.animSpeed[animState] || AVATAR_CONFIG.animSpeed.idle;
            avatar.animPhase += dt * speed;
            const t = avatar.animPhase;

            // Get bone animation config
            const boneAnim = AVATAR_CONFIG.boneAnim[animState] || AVATAR_CONFIG.boneAnim.idle;
            const initRot = bones.initialRotations || {};

            // Apply animations to each bone
            this._animateBone(bones.torso, boneAnim.torso, initRot.torso, t);
            this._animateBone(bones.head, boneAnim.head, initRot.head, t);
            this._animateBone(bones.armLeft, boneAnim.armLeft, initRot.armLeft, t);
            this._animateBone(bones.armRight, boneAnim.armRight, initRot.armRight, t);
            this._animateBone(bones.legLeft, boneAnim.legLeft, initRot.legLeft, t);
            this._animateBone(bones.legRight, boneAnim.legRight, initRot.legRight, t);
        }

        /**
         * Animate a single bone
         */
        _animateBone(bone, config, initialRotation, t) {
            if (!bone || !config) return;

            const init = initialRotation || { x: 0, y: 0, z: 0 };
            const phase = t + (config.phaseOffset || 0);

            // Apply rotation animations
            if (config.rotX !== undefined) {
                bone.rotation.x = init.x + config.rotX * Math.sin(phase);
            }
            if (config.rotY !== undefined) {
                bone.rotation.y = init.y + config.rotY * Math.sin(phase * 0.7);
            }
            if (config.rotZ !== undefined) {
                bone.rotation.z = init.z + config.rotZ * Math.sin(phase * 0.8);
            }
        }

        /**
         * Update wandering behavior
         */
        _updateWandering(avatar, deltaTime) {
            if (!AVATAR_CONFIG.wander.enabled) return;
            if (avatar.isMoving) return;
            if (avatar.isProcessing) return;  // Don't wander during request processing

            avatar.idleTimer += deltaTime;

            if (avatar.idleTimer >= avatar.nextWanderTime) {
                // Time to wander
                this._startRandomWander(avatar);
            }
        }

        /**
         * Start random wandering
         */
        _startRandomWander(avatar) {
            // Find a random destination within wander distance
            const maxDist = AVATAR_CONFIG.wander.maxWanderDistance;
            const currentX = Math.round(avatar.gridX);
            const currentZ = Math.round(avatar.gridZ);

            // Get nearby road positions
            const nearbyRoads = this.roadPositions.filter(pos => {
                const dx = pos.x - currentX;
                const dz = pos.z - currentZ;
                const dist = Math.sqrt(dx * dx + dz * dz);
                return dist > 0 && dist <= maxDist;
            });

            if (nearbyRoads.length === 0) {
                avatar.idleTimer = 0;
                avatar.nextWanderTime = this._getRandomWanderDelay();
                return;
            }

            // Pick random destination
            const dest = nearbyRoads[Math.floor(Math.random() * nearbyRoads.length)];

            // Find path
            this.moveTo(avatar.sessionId, dest.x, dest.z);
        }

        /**
         * Update direction rotation (smooth interpolation)
         */
        _updateRotation(avatar, dt) {
            const targetRotY = AVATAR_CONFIG.directionRotation[avatar.targetDirection] || 0;
            const rotSpeed = AVATAR_CONFIG.movement.rotationSpeed;

            // Calculate rotation difference
            let rotDiff = targetRotY - avatar.currentRotationY;

            // Normalize to [-PI, PI]
            while (rotDiff > Math.PI) rotDiff -= Math.PI * 2;
            while (rotDiff < -Math.PI) rotDiff += Math.PI * 2;

            // Smooth interpolation
            avatar.currentRotationY += rotDiff * Math.min(dt * rotSpeed, 1);

            // Apply to model (not container)
            avatar.model.rotation.y = avatar.currentRotationY;
            avatar.direction = avatar.targetDirection;
        }

        // ==================== Public API ====================

        /**
         * Move avatar to a specific grid position
         */
        moveTo(sessionId, targetX, targetZ) {
            const avatar = this.avatars.get(sessionId);
            if (!avatar) return false;

            const startX = Math.round(avatar.gridX);
            const startZ = Math.round(avatar.gridZ);
            const endX = Math.round(targetX);
            const endZ = Math.round(targetZ);

            // Find path
            const path = this.pathfinder.findPath(startX, startZ, endX, endZ);

            if (path.length === 0) {
                debugLog(`No path found from (${startX},${startZ}) to (${endX},${endZ})`);
                return false;
            }

            // Start movement
            avatar.path = path;
            avatar.pathIndex = 0;
            avatar.isMoving = true;
            avatar.animState = 'walk';
            avatar.idleTimer = 0;

            debugLog(`${sessionId.substring(0, 8)} moving to (${endX}, ${endZ}), ${path.length} waypoints`);
            return true;
        }

        /**
         * Set avatar animation state
         */
        setAnimState(sessionId, state) {
            const avatar = this.avatars.get(sessionId);
            if (avatar && avatar.animState !== state) {
                avatar.animState = state;
                debugLog(`${sessionId.substring(0, 8)} animState: ${state}`);
            }
        }

        /**
         * Mark avatar as processing a request
         */
        setProcessing(sessionId, isProcessing) {
            const avatar = this.avatars.get(sessionId);
            if (avatar) {
                avatar.isProcessing = isProcessing;
                if (isProcessing) {
                    // Stop wandering and set thinking animation
                    if (!avatar.isMoving) {
                        avatar.animState = 'thinking';
                    }
                } else {
                    // Return to idle when done
                    if (!avatar.isMoving) {
                        avatar.animState = 'idle';
                    }
                }
            }
        }

        /**
         * Get avatar data by session ID
         */
        getAvatar(sessionId) {
            return this.avatars.get(sessionId);
        }

        /**
         * Get all avatars
         */
        getAllAvatars() {
            return this.avatars;
        }

        /**
         * Sync avatars with session list
         * @param {Array} sessions - Array of session objects with session_id and name
         */
        syncSessions(sessions) {
            if (!this.ready) return;

            const currentIds = new Set(this.avatars.keys());
            const newIds = new Set(sessions.map(s => s.session_id));

            // Remove avatars for sessions that no longer exist
            for (const sessionId of currentIds) {
                if (!newIds.has(sessionId)) {
                    this.removeAvatar(sessionId);
                }
            }

            // Add avatars for new sessions
            for (const session of sessions) {
                if (!currentIds.has(session.session_id)) {
                    const name = session.session_name || `Session ${session.session_id.substring(0, 8)}`;
                    this.createAvatar(session.session_id, name);
                }
            }

            debugLog(`Synced ${sessions.length} sessions, ${this.avatars.size} avatars`);
        }

        /**
         * Dispose all resources
         */
        dispose() {
            // Remove all avatars
            for (const sessionId of this.avatars.keys()) {
                this.removeAvatar(sessionId);
            }

            // Clear templates
            this.modelTemplates.clear();

            this.ready = false;
            debugLog('Avatar system disposed');
        }
    }

    // Export
    window.Playground.AvatarSystem = AvatarSystem;
    debugLog('AvatarSystem module loaded');

})();
