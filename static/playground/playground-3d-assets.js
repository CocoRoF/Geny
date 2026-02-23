/**
 * City 3D Asset Loader
 * Loads GLB models from Kenney city kits
 */
(function() {
    'use strict';

    window.Playground = window.Playground || {};

    const DEBUG = true;
    function debugLog(...args) {
        if (DEBUG) console.log('[City3DAssets]', ...args);
    }

    // ==================== Asset Paths ====================
    const ASSET_BASE = '/static/assets/';
    const ASSET_PACKS = {
        commercial: ASSET_BASE + 'kenney_city-kit-commercial_2.1/Models/GLB format/',
        roads: ASSET_BASE + 'kenney_city-kit-roads/Models/GLB format/',
        suburban: ASSET_BASE + 'kenney_city-kit-suburban_20/Models/GLB format/',
        survival: ASSET_BASE + 'kenney_survival-kit/Models/GLB format/',
        minigolf: ASSET_BASE + 'kenney_minigolf-kit/Models/GLB format/',
        market: ASSET_BASE + 'kenney_mini-market/Models/GLB format/'
    };

    // ==================== Asset Manifest ====================
    const ASSET_MANIFEST = {
        // Commercial buildings
        building: {
            a: { pack: 'commercial', file: 'building-a.glb' },
            b: { pack: 'commercial', file: 'building-b.glb' },
            c: { pack: 'commercial', file: 'building-c.glb' },
            d: { pack: 'commercial', file: 'building-d.glb' },
            e: { pack: 'commercial', file: 'building-e.glb' },
            f: { pack: 'commercial', file: 'building-f.glb' },
            g: { pack: 'commercial', file: 'building-g.glb' },
            h: { pack: 'commercial', file: 'building-h.glb' },
            i: { pack: 'commercial', file: 'building-i.glb' },
            j: { pack: 'commercial', file: 'building-j.glb' },
            k: { pack: 'commercial', file: 'building-k.glb' },
            l: { pack: 'commercial', file: 'building-l.glb' },
            skyscraperA: { pack: 'commercial', file: 'building-skyscraper-a.glb' },
            skyscraperB: { pack: 'commercial', file: 'building-skyscraper-b.glb' }
        },

        // Suburban path stones (ground tiles)
        suburban: {
            pathStonesShort: { pack: 'suburban', file: 'path-stones-short.glb' },
            pathStonesLong: { pack: 'suburban', file: 'path-stones-long.glb' },
            pathStonesMessy: { pack: 'suburban', file: 'path-stones-messy.glb' }
        },

        // Roads
        road: {
            straight: { pack: 'roads', file: 'road-straight.glb' },
            bend: { pack: 'roads', file: 'road-bend.glb' },
            crossing: { pack: 'roads', file: 'road-crossing.glb' },
            crossroad: { pack: 'roads', file: 'road-crossroad.glb' },
            intersection: { pack: 'roads', file: 'road-intersection.glb' },
            end: { pack: 'roads', file: 'road-end.glb' }
        },

        // Road tiles (ground)
        tile: {
            low: { pack: 'roads', file: 'tile-low.glb' }
        },

        // Survival Kit - Park Elements
        park: {
            // Trees
            tree: { pack: 'survival', file: 'tree.glb' },
            treeTall: { pack: 'survival', file: 'tree-tall.glb' },
            treeAutumn: { pack: 'survival', file: 'tree-autumn.glb' },
            treeAutumnTall: { pack: 'survival', file: 'tree-autumn-tall.glb' },
            treeLog: { pack: 'survival', file: 'tree-log.glb' },
            treeLogSmall: { pack: 'survival', file: 'tree-log-small.glb' },

            // Rocks
            rockA: { pack: 'survival', file: 'rock-a.glb' },
            rockB: { pack: 'survival', file: 'rock-b.glb' },
            rockC: { pack: 'survival', file: 'rock-c.glb' },
            rockFlat: { pack: 'survival', file: 'rock-flat.glb' },
            rockFlatGrass: { pack: 'survival', file: 'rock-flat-grass.glb' },

            // Grass and patches
            grass: { pack: 'survival', file: 'grass.glb' },
            grassLarge: { pack: 'survival', file: 'grass-large.glb' },
            patchGrass: { pack: 'survival', file: 'patch-grass.glb' },
            patchGrassLarge: { pack: 'survival', file: 'patch-grass-large.glb' },

            // Campfire
            campfirePit: { pack: 'survival', file: 'campfire-pit.glb' },

            // Props
            barrel: { pack: 'survival', file: 'barrel.glb' },
            boxLarge: { pack: 'survival', file: 'box-large.glb' },
            bucket: { pack: 'survival', file: 'bucket.glb' },
            metalPanel: { pack: 'survival', file: 'metal-panel.glb' },
            signpost: { pack: 'survival', file: 'signpost.glb' },
            signpostSingle: { pack: 'survival', file: 'signpost-single.glb' },

            // Floors/Tiles
            floorOld: { pack: 'survival', file: 'floor-old.glb' }
        },

        // Minigolf Kit - Park Ground Tiles (only tiles used in layout)
        minigolf: {
            open: { pack: 'minigolf', file: 'open.glb' },
            corner: { pack: 'minigolf', file: 'corner.glb' },
            side: { pack: 'minigolf', file: 'side.glb' }
        },

        // Mini-Market Kit - Floor Tiles
        market: {
            floor: { pack: 'market', file: 'floor.glb' }
        }
    };

    // ==================== Asset Loader Class ====================
    class Asset3DLoader {
        constructor() {
            this.models = new Map();
            this.gltfLoader = null;
            this.ready = false;
        }

        init() {
            if (!THREE.GLTFLoader) {
                console.error('THREE.GLTFLoader not available');
                return false;
            }
            this.gltfLoader = new THREE.GLTFLoader();
            debugLog('Asset3DLoader initialized');
            return true;
        }

        async loadAll(progressCallback) {
            if (!this.gltfLoader) {
                console.error('Loader not initialized');
                return;
            }

            const assets = [];
            for (const category of Object.keys(ASSET_MANIFEST)) {
                for (const name of Object.keys(ASSET_MANIFEST[category])) {
                    const asset = ASSET_MANIFEST[category][name];
                    assets.push({
                        category,
                        name,
                        url: ASSET_PACKS[asset.pack] + asset.file
                    });
                }
            }

            const total = assets.length;
            let loaded = 0;

            debugLog(`Loading ${total} models...`);

            const loadPromises = assets.map(asset => {
                return new Promise((resolve) => {
                    this.gltfLoader.load(
                        asset.url,
                        (gltf) => {
                            const model = gltf.scene;
                            const key = `${asset.category}/${asset.name}`;
                            this.models.set(key, model);
                            loaded++;
                            if (progressCallback) progressCallback(loaded, total, asset.url);
                            resolve();
                        },
                        undefined,
                        (error) => {
                            console.warn(`Failed to load ${asset.url}:`, error.message);
                            loaded++;
                            if (progressCallback) progressCallback(loaded, total, asset.url);
                            resolve();
                        }
                    );
                });
            });

            await Promise.all(loadPromises);
            this.ready = true;
            debugLog(`All models loaded. Total: ${this.models.size}`);
        }

        async loadEssential(progressCallback) {
            if (!this.gltfLoader) {
                console.error('Loader not initialized');
                return;
            }

            // Essential models for the city
            const essentialKeys = [
                // Buildings (a-l + 2 skyscrapers)
                'building/a', 'building/b', 'building/c', 'building/d',
                'building/e', 'building/f', 'building/g', 'building/h',
                'building/i', 'building/j', 'building/k', 'building/l',
                'building/skyscraperA', 'building/skyscraperB',
                // Roads
                'road/straight', 'road/bend', 'road/crossing', 'road/crossroad', 'road/intersection', 'road/end',
                // Concrete tile
                'tile/low',
                // Suburban path stones (ground tiles)
                'suburban/pathStonesShort', 'suburban/pathStonesLong', 'suburban/pathStonesMessy',
                // Park assets from survival kit (only those placed in NATURE array)
                'park/tree', 'park/treeTall', 'park/treeAutumn', 'park/treeAutumnTall',
                'park/treeLog', 'park/treeLogSmall',
                'park/rockA', 'park/rockB', 'park/rockC', 'park/rockFlat', 'park/rockFlatGrass',
                'park/grass', 'park/grassLarge', 'park/patchGrass', 'park/patchGrassLarge',
                'park/campfirePit',
                'park/barrel', 'park/boxLarge', 'park/bucket', 'park/metalPanel',
                'park/signpost', 'park/signpostSingle',
                'park/floorOld',
                // Minigolf grass tiles for park ground (only used: open, corner, side)
                'minigolf/open', 'minigolf/corner', 'minigolf/side',
                // Mini-market floor tiles
                'market/floor'
            ];

            const assets = [];
            for (const key of essentialKeys) {
                const [category, name] = key.split('/');
                if (ASSET_MANIFEST[category] && ASSET_MANIFEST[category][name]) {
                    const asset = ASSET_MANIFEST[category][name];
                    assets.push({
                        category,
                        name,
                        url: ASSET_PACKS[asset.pack] + asset.file
                    });
                }
            }

            const total = assets.length;
            let loaded = 0;

            debugLog(`Loading ${total} essential models...`);

            const loadPromises = assets.map(asset => {
                return new Promise((resolve) => {
                    this.gltfLoader.load(
                        asset.url,
                        (gltf) => {
                            const key = `${asset.category}/${asset.name}`;
                            this.models.set(key, gltf.scene);
                            loaded++;
                            if (progressCallback) progressCallback(loaded, total, asset.url);
                            resolve();
                        },
                        undefined,
                        (error) => {
                            console.warn(`Failed to load ${asset.url}`);
                            loaded++;
                            if (progressCallback) progressCallback(loaded, total, asset.url);
                            resolve();
                        }
                    );
                });
            });

            await Promise.all(loadPromises);
            this.ready = true;
            debugLog('Essential models loaded');
        }

        getModel(category, name) {
            const key = `${category}/${name}`;
            const template = this.models.get(key);
            if (!template) {
                return null;
            }
            return template.clone();
        }

        hasModel(category, name) {
            return this.models.has(`${category}/${name}`);
        }

        dispose() {
            for (const [key, model] of this.models) {
                model.traverse((child) => {
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
            this.models.clear();
            this.ready = false;
        }
    }

    // Export
    window.Playground.Asset3DLoader = Asset3DLoader;
    window.Playground.ASSET_MANIFEST_3D = ASSET_MANIFEST;
    window.Playground.ASSET_PACKS = ASSET_PACKS;

    debugLog('City3DAssets module loaded');

})();
