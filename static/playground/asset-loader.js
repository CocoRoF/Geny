(function() {
    'use strict';

    const ASSET_BASE = '/static/assets/';

    const ASSET_PATHS = {
        dungeon: ASSET_BASE + 'kenney_isometric-miniature-dungeon/Isometric/',
        farm: ASSET_BASE + 'kenney_isometric-miniature-farm/Isometric/',
        library: ASSET_BASE + 'kenney_isometric-miniature-library/Isometric/'
    };

    const ASSET_MANIFEST = {
        floor: {
            stone_E: { path: 'dungeon', file: 'stone_E.png' },
            stone_S: { path: 'dungeon', file: 'stone_S.png' },
            stoneTile_E: { path: 'dungeon', file: 'stoneTile_E.png' }
        },

        wall: {
            stone_E: { path: 'dungeon', file: 'stoneWall_E.png' },
            stone_S: { path: 'dungeon', file: 'stoneWall_S.png' },
            stoneCorner_E: { path: 'dungeon', file: 'stoneWallCorner_E.png' },
            stoneCorner_S: { path: 'dungeon', file: 'stoneWallCorner_S.png' },
            stoneWindow_E: { path: 'dungeon', file: 'stoneWallWindow_E.png' },
            stoneWindow_S: { path: 'dungeon', file: 'stoneWallWindow_S.png' },
            stoneArchway_E: { path: 'dungeon', file: 'stoneWallArchway_E.png' },
            stoneArchway_S: { path: 'dungeon', file: 'stoneWallArchway_S.png' }
        },

        bookcase: {
            glass_E: { path: 'library', file: 'bookcaseGlass_E.png' },
            glass_S: { path: 'library', file: 'bookcaseGlass_S.png' },
            wide_E: { path: 'library', file: 'bookcaseWideBooks_E.png' },
            wide_S: { path: 'library', file: 'bookcaseWideBooks_S.png' },
            booksLadder_E: { path: 'library', file: 'bookcaseBooksLadder_E.png' },
            booksLadder_S: { path: 'library', file: 'bookcaseBooksLadder_S.png' },
            half_E: { path: 'library', file: 'bookcaseHalfBooks_E.png' },
            half_S: { path: 'library', file: 'bookcaseHalfBooks_S.png' },
            wideDesk_E: { path: 'library', file: 'bookcaseWideBooksDesk_E.png' },
            wideDesk_S: { path: 'library', file: 'bookcaseWideBooksDesk_S.png' }
        },

        table: {
            longDecoratedChairsBooks_E: { path: 'library', file: 'longTableDecoratedChairsBooks_E.png' },
            longDecoratedChairsBooks_S: { path: 'library', file: 'longTableDecoratedChairsBooks_S.png' },
            longDecoratedChairs_E: { path: 'library', file: 'longTableDecoratedChairs_E.png' },
            longDecoratedChairs_S: { path: 'library', file: 'longTableDecoratedChairs_S.png' },
            roundChairs_E: { path: 'dungeon', file: 'tableRoundChairs_E.png' },
            roundChairs_S: { path: 'dungeon', file: 'tableRoundChairs_S.png' }
        },

        chair: {
            library_E: { path: 'library', file: 'libraryChair_E.png' },
            library_S: { path: 'library', file: 'libraryChair_S.png' }
        },

        decor: {
            displayCaseBooks_E: { path: 'library', file: 'displayCaseBooks_E.png' }
        }
    };

    class AssetLoader {
        constructor() {
            this.textures = new Map();
            this.textureLoader = new THREE.TextureLoader();
            this.ready = false;
        }

        async loadAll(progressCallback) {
            const assets = [];

            // Collect all assets from manifest
            for (const category of Object.keys(ASSET_MANIFEST)) {
                for (const name of Object.keys(ASSET_MANIFEST[category])) {
                    const asset = ASSET_MANIFEST[category][name];
                    assets.push({
                        category,
                        name,
                        url: ASSET_PATHS[asset.path] + asset.file
                    });
                }
            }

            const total = assets.length;
            let loaded = 0;

            // Load all textures
            const loadPromises = assets.map(asset => {
                return new Promise((resolve, reject) => {
                    this.textureLoader.load(
                        asset.url,
                        (texture) => {
                            // Configure texture for pixel art
                            texture.colorSpace = THREE.SRGBColorSpace;
                            texture.magFilter = THREE.NearestFilter;
                            texture.minFilter = THREE.NearestFilter;

                            // Cache texture
                            const key = `${asset.category}/${asset.name}`;
                            this.textures.set(key, texture);

                            loaded++;
                            if (progressCallback) {
                                progressCallback(loaded, total, asset.url);
                            }

                            resolve(texture);
                        },
                        undefined,
                        (error) => {
                            console.error(`Failed to load texture: ${asset.url}`, error);
                            loaded++;
                            if (progressCallback) {
                                progressCallback(loaded, total, asset.url);
                            }
                            resolve(null); // Continue loading other assets
                        }
                    );
                });
            });

            await Promise.all(loadPromises);
            this.ready = true;

            return this.textures;
        }

        getTexture(category, name) {
            const key = `${category}/${name}`;
            return this.textures.get(key);
        }

        createMaterial(category, name) {
            const texture = this.getTexture(category, name);

            if (!texture) {
                console.warn(`Texture not found: ${category}/${name}`);
                return null;
            }

            // Return SpriteMaterial for sprite usage
            return new THREE.SpriteMaterial({
                map: texture,
                transparent: true
            });
        }

        createMeshMaterial(category, name) {
            const texture = this.getTexture(category, name);

            if (!texture) {
                console.warn(`Texture not found: ${category}/${name}`);
                return null;
            }

            // Return MeshBasicMaterial for mesh usage
            return new THREE.MeshBasicMaterial({
                map: texture,
                transparent: true,
                side: THREE.DoubleSide
            });
        }
    }

    // Export to global namespace
    window.Playground = window.Playground || {};
    window.Playground.AssetLoader = AssetLoader;
})();
