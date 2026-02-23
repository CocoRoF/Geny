/**
 * Sprite Plane Rendering System for Three.js Isometric View
 * Renders 2D Kenney sprites as billboarded planes in a Three.js isometric scene.
 */
(function() {
    'use strict';

    // ============================================================
    // Constants - Kenney Isometric Miniature sprite dimensions
    // ============================================================
    const SPRITE_WIDTH = 256;
    const SPRITE_HEIGHT = 512;
    const TILE_DIAMOND_HEIGHT = 148; // Pixels from bottom where tile diamond ends
    const WORLD_TILE_SIZE = 1.0;     // One grid unit = 1 world unit
    const SPRITE_SCALE = WORLD_TILE_SIZE / 256; // Convert pixels to world units

    // ============================================================
    // SpritePlane Class
    // ============================================================
    class SpritePlane {
        /**
         * Create a sprite plane from a texture
         * @param {THREE.Texture} texture - The sprite texture
         * @param {Object} options - Configuration options
         * @param {number} [options.width=256] - Width in pixels
         * @param {number} [options.height=512] - Height in pixels
         * @param {number} [options.anchorX=0.5] - Horizontal anchor (0=left, 0.5=center, 1=right)
         * @param {number} [options.anchorY=1.0] - Vertical anchor (0=top, 0.5=center, 1=bottom)
         */
        constructor(texture, options = {}) {
            this.texture = texture;

            // Parse options with defaults
            this.pixelWidth = options.width || SPRITE_WIDTH;
            this.pixelHeight = options.height || SPRITE_HEIGHT;
            this.anchorX = options.anchorX !== undefined ? options.anchorX : 0.5;
            this.anchorY = options.anchorY !== undefined ? options.anchorY : 1.0;

            // Calculate world dimensions
            this.worldWidth = this.pixelWidth * SPRITE_SCALE;
            this.worldHeight = this.pixelHeight * SPRITE_SCALE;

            // Create the mesh
            this.mesh = this._createMesh();

            // Grid position tracking
            this.gridX = 0;
            this.gridY = 0;
        }

        /**
         * Create the Three.js sprite (always faces camera)
         * @returns {THREE.Sprite}
         * @private
         */
        _createMesh() {
            // Use Sprite instead of Mesh+Plane for proper camera-facing behavior
            const material = new THREE.SpriteMaterial({
                map: this.texture,
                transparent: true,
                alphaTest: 0.1
            });

            const sprite = new THREE.Sprite(material);

            // Scale sprite to match world dimensions
            sprite.scale.set(this.worldWidth, this.worldHeight, 1);

            // Adjust center (anchor point) - SpriteMaterial.center is 0.5, 0.5 by default
            // We need to offset for our anchor
            // center.x: 0 = left edge, 0.5 = center, 1 = right edge
            // center.y: 0 = bottom edge, 0.5 = center, 1 = top edge
            sprite.center.set(this.anchorX, 1 - this.anchorY);

            return sprite;
        }

        /**
         * Set position in grid coordinates
         * @param {number} gridX - Grid X position
         * @param {number} gridY - Grid Y position
         * @param {number} [layerOffset=0] - Layer offset for depth sorting
         */
        setPosition(gridX, gridY, layerOffset = 0) {
            this.gridX = gridX;
            this.gridY = gridY;

            // Convert grid to world coordinates
            const worldPos = IsometricUtils.gridToWorld(gridX, gridY);

            // Position the mesh
            // Y in Three.js is vertical, worldPos.y is ground level
            // The anchor offset in geometry handles vertical positioning
            this.mesh.position.set(worldPos.x, worldPos.y, worldPos.z);

            // Set render order based on depth key for proper sorting
            // Higher values render in front (later in the render queue)
            const depth = IsometricUtils.depthKey(gridX, gridY, layerOffset);
            this.mesh.renderOrder = depth;

            return this;
        }

        /**
         * Set world position directly
         * @param {number} x - World X position
         * @param {number} y - World Y position (vertical)
         * @param {number} z - World Z position
         */
        setWorldPosition(x, y, z) {
            this.mesh.position.set(x, y, z);
            return this;
        }

        /**
         * Set render order manually
         * @param {number} order - Render order value
         */
        setRenderOrder(order) {
            this.mesh.renderOrder = order;
            return this;
        }

        /**
         * Add this sprite plane to a Three.js scene
         * @param {THREE.Scene} scene - The scene to add to
         */
        addToScene(scene) {
            scene.add(this.mesh);
            return this;
        }

        /**
         * Remove this sprite plane from its parent scene
         */
        removeFromScene() {
            if (this.mesh.parent) {
                this.mesh.parent.remove(this.mesh);
            }
            return this;
        }

        /**
         * Dispose of resources
         */
        dispose() {
            this.removeFromScene();
            if (this.mesh.material) {
                this.mesh.material.dispose();
            }
        }

        /**
         * Get the underlying Three.js mesh
         * @returns {THREE.Mesh}
         */
        getMesh() {
            return this.mesh;
        }

        // ============================================================
        // Static Factory Methods
        // ============================================================

        /**
         * Create a positioned sprite plane from an asset loader
         * @param {AssetLoader} assetLoader - The asset loader instance
         * @param {string} category - Asset category (e.g., 'floor', 'wall')
         * @param {string} name - Asset name within category
         * @param {number} gridX - Grid X position
         * @param {number} gridY - Grid Y position
         * @param {Object} [options] - Additional options passed to constructor
         * @returns {SpritePlane|null} The created sprite plane, or null if texture not found
         */
        static create(assetLoader, category, name, gridX, gridY, options = {}) {
            const texture = assetLoader.getTexture(category, name);

            if (!texture) {
                console.warn(`SpritePlane.create: Texture not found: ${category}/${name}`);
                return null;
            }

            const spritePlane = new SpritePlane(texture, options);
            spritePlane.setPosition(gridX, gridY, options.layerOffset || 0);

            return spritePlane;
        }

        /**
         * Create a sprite plane from a texture URL
         * @param {string} url - The texture URL
         * @param {number} gridX - Grid X position
         * @param {number} gridY - Grid Y position
         * @param {Object} [options] - Additional options
         * @returns {Promise<SpritePlane>} Promise resolving to the created sprite plane
         */
        static async createFromUrl(url, gridX, gridY, options = {}) {
            return new Promise((resolve, reject) => {
                const textureLoader = new THREE.TextureLoader();
                textureLoader.load(
                    url,
                    (texture) => {
                        // Configure texture for pixel art
                        texture.colorSpace = THREE.SRGBColorSpace;
                        texture.magFilter = THREE.NearestFilter;
                        texture.minFilter = THREE.NearestFilter;

                        const spritePlane = new SpritePlane(texture, options);
                        spritePlane.setPosition(gridX, gridY, options.layerOffset || 0);

                        resolve(spritePlane);
                    },
                    undefined,
                    (error) => {
                        console.error(`SpritePlane.createFromUrl: Failed to load ${url}`, error);
                        reject(error);
                    }
                );
            });
        }
    }

    // ============================================================
    // Export Constants
    // ============================================================
    SpritePlane.SPRITE_WIDTH = SPRITE_WIDTH;
    SpritePlane.SPRITE_HEIGHT = SPRITE_HEIGHT;
    SpritePlane.TILE_DIAMOND_HEIGHT = TILE_DIAMOND_HEIGHT;
    SpritePlane.WORLD_TILE_SIZE = WORLD_TILE_SIZE;
    SpritePlane.SPRITE_SCALE = SPRITE_SCALE;

    // ============================================================
    // Export to global namespace
    // ============================================================
    window.Playground = window.Playground || {};
    window.Playground.SpritePlane = SpritePlane;

})();
