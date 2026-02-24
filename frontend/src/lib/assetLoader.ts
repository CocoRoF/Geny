/**
 * Asset3DLoader — TypeScript port of playground-3d-assets.js
 * Handles loading and caching GLB/GLTF 3D models
 *
 * Key design: models are cached with composite key "category/name",
 * matching the legacy getModel(category, name) API used by cityLayout.ts
 */
import * as THREE from 'three';
import { GLTFLoader, type GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js';

// ==================== Asset Pack Paths ====================
// Next.js serves public/ at root, so public/assets/ → /assets/
const ASSET_BASE = '/assets/';
const ASSET_PACKS: Record<string, string> = {
  commercial: ASSET_BASE + 'kenney_city-kit-commercial_2.1/Models/GLB format',
  roads:      ASSET_BASE + 'kenney_city-kit-roads/Models/GLB format',
  suburban:   ASSET_BASE + 'kenney_city-kit-suburban_20/Models/GLB format',
  survival:   ASSET_BASE + 'kenney_survival-kit/Models/GLB format',
  minigolf:   ASSET_BASE + 'kenney_minigolf-kit/Models/GLB format',
  market:     ASSET_BASE + 'kenney_mini-market/Models/GLB format',
  characters: ASSET_BASE + 'kenney_mini-characters/Models/GLB format',
};

// ==================== Asset Manifest ====================
// Nested: ASSET_MANIFEST[category][name] = { pack, file }
// Matches legacy playground-3d-assets.js exactly
interface AssetDef {
  pack: string;
  file: string;
}

const ASSET_MANIFEST: Record<string, Record<string, AssetDef>> = {
  // Commercial buildings — actual filenames are "building-*.glb"
  building: {
    a:            { pack: 'commercial', file: 'building-a.glb' },
    b:            { pack: 'commercial', file: 'building-b.glb' },
    c:            { pack: 'commercial', file: 'building-c.glb' },
    d:            { pack: 'commercial', file: 'building-d.glb' },
    e:            { pack: 'commercial', file: 'building-e.glb' },
    f:            { pack: 'commercial', file: 'building-f.glb' },
    g:            { pack: 'commercial', file: 'building-g.glb' },
    h:            { pack: 'commercial', file: 'building-h.glb' },
    i:            { pack: 'commercial', file: 'building-i.glb' },
    j:            { pack: 'commercial', file: 'building-j.glb' },
    k:            { pack: 'commercial', file: 'building-k.glb' },
    l:            { pack: 'commercial', file: 'building-l.glb' },
    skyscraperA:  { pack: 'commercial', file: 'building-skyscraper-a.glb' },
    skyscraperB:  { pack: 'commercial', file: 'building-skyscraper-b.glb' },
  },

  // Suburban path stones (ground tiles)
  suburban: {
    pathStonesShort: { pack: 'suburban', file: 'path-stones-short.glb' },
    pathStonesLong:  { pack: 'suburban', file: 'path-stones-long.glb' },
    pathStonesMessy: { pack: 'suburban', file: 'path-stones-messy.glb' },
  },

  // Roads
  road: {
    straight:     { pack: 'roads', file: 'road-straight.glb' },
    bend:         { pack: 'roads', file: 'road-bend.glb' },
    crossing:     { pack: 'roads', file: 'road-crossing.glb' },
    crossroad:    { pack: 'roads', file: 'road-crossroad.glb' },
    intersection: { pack: 'roads', file: 'road-intersection.glb' },
    end:          { pack: 'roads', file: 'road-end.glb' },
  },

  // Road tiles (ground)
  tile: {
    low: { pack: 'roads', file: 'tile-low.glb' },
  },

  // Survival Kit — Park Elements
  park: {
    // Trees
    tree:             { pack: 'survival', file: 'tree.glb' },
    treeTall:         { pack: 'survival', file: 'tree-tall.glb' },
    treeAutumn:       { pack: 'survival', file: 'tree-autumn.glb' },
    treeAutumnTall:   { pack: 'survival', file: 'tree-autumn-tall.glb' },
    treeLog:          { pack: 'survival', file: 'tree-log.glb' },
    treeLogSmall:     { pack: 'survival', file: 'tree-log-small.glb' },
    // Rocks
    rockA:            { pack: 'survival', file: 'rock-a.glb' },
    rockB:            { pack: 'survival', file: 'rock-b.glb' },
    rockC:            { pack: 'survival', file: 'rock-c.glb' },
    rockFlat:         { pack: 'survival', file: 'rock-flat.glb' },
    rockFlatGrass:    { pack: 'survival', file: 'rock-flat-grass.glb' },
    // Grass and patches
    grass:            { pack: 'survival', file: 'grass.glb' },
    grassLarge:       { pack: 'survival', file: 'grass-large.glb' },
    patchGrass:       { pack: 'survival', file: 'patch-grass.glb' },
    patchGrassLarge:  { pack: 'survival', file: 'patch-grass-large.glb' },
    // Campfire
    campfirePit:      { pack: 'survival', file: 'campfire-pit.glb' },
    // Props
    barrel:           { pack: 'survival', file: 'barrel.glb' },
    boxLarge:         { pack: 'survival', file: 'box-large.glb' },
    bucket:           { pack: 'survival', file: 'bucket.glb' },
    metalPanel:       { pack: 'survival', file: 'metal-panel.glb' },
    signpost:         { pack: 'survival', file: 'signpost.glb' },
    signpostSingle:   { pack: 'survival', file: 'signpost-single.glb' },
    // Floors/Tiles
    floorOld:         { pack: 'survival', file: 'floor-old.glb' },
  },

  // Minigolf Kit — Park Ground Tiles
  minigolf: {
    open:   { pack: 'minigolf', file: 'open.glb' },
    corner: { pack: 'minigolf', file: 'corner.glb' },
    side:   { pack: 'minigolf', file: 'side.glb' },
  },

  // Mini-Market Kit — Floor Tiles
  market: {
    floor: { pack: 'market', file: 'floor.glb' },
  },
};

// Character model names (actual filenames in kenney_mini-characters)
export const CHARACTER_MODELS = [
  'character-female-a',
  'character-female-b',
  'character-female-c',
  'character-female-d',
  'character-female-e',
  'character-female-f',
  'character-male-a',
  'character-male-b',
  'character-male-c',
  'character-male-d',
  'character-male-e',
  'character-male-f',
];

// ==================== Asset3DLoader Class ====================

export class Asset3DLoader {
  private loader: GLTFLoader;
  private cache: Map<string, THREE.Object3D> = new Map();
  private characterCache: Map<string, GLTF> = new Map();
  private loaded = false;

  constructor() {
    this.loader = new GLTFLoader();
  }

  /**
   * Load all assets from the manifest.
   * Models are stored with composite key "category/name"
   * (e.g. "building/a", "road/straight", "park/tree")
   */
  async loadAll(
    onProgress?: (loaded: number, total: number) => void,
  ): Promise<void> {
    // Flatten manifest into array of { category, name, pack, file }
    const assets: { category: string; name: string; pack: string; file: string }[] = [];
    for (const category of Object.keys(ASSET_MANIFEST)) {
      for (const name of Object.keys(ASSET_MANIFEST[category])) {
        const def = ASSET_MANIFEST[category][name];
        assets.push({ category, name, pack: def.pack, file: def.file });
      }
    }

    const total = assets.length + CHARACTER_MODELS.length;
    let loaded = 0;

    // Load manifest assets
    const promises = assets.map(async (asset) => {
      const url = `${ASSET_PACKS[asset.pack]}/${asset.file}`;
      try {
        const gltf = await this.load(url);
        const model = gltf.scene.clone();
        const key = `${asset.category}/${asset.name}`;
        this.cache.set(key, model);
      } catch (err) {
        console.warn(`[AssetLoader] Failed to load ${asset.category}/${asset.name}: ${url}`, err);
      } finally {
        loaded++;
        onProgress?.(loaded, total);
      }
    });

    // Load character models
    const charPromises = CHARACTER_MODELS.map(async (name) => {
      const url = `${ASSET_PACKS.characters}/${name}.glb`;
      try {
        const gltf = await this.load(url);
        this.characterCache.set(name, gltf);
      } catch (err) {
        console.warn(`[AssetLoader] Failed to load character ${name}`, err);
      } finally {
        loaded++;
        onProgress?.(loaded, total);
      }
    });

    await Promise.all([...promises, ...charPromises]);
    this.loaded = true;
  }

  /**
   * Get a cloned model by category + name.
   * Cache key is "category/name" (e.g. "building/a", "road/straight", "park/tree").
   */
  getModel(category: string, name: string): THREE.Object3D | null {
    const key = `${category}/${name}`;
    const original = this.cache.get(key);
    if (!original) return null;
    return original.clone();
  }

  /** Get a character GLTF (for SkeletonUtils cloning) */
  getCharacterGLTF(name: string): GLTF | null {
    return this.characterCache.get(name) ?? null;
  }

  /** Get a random character model name */
  getRandomCharacterName(): string {
    return CHARACTER_MODELS[Math.floor(Math.random() * CHARACTER_MODELS.length)];
  }

  /** Whether all assets have been loaded */
  isLoaded(): boolean {
    return this.loaded;
  }

  /** Dispose all cached models */
  dispose(): void {
    for (const model of this.cache.values()) {
      model.traverse((child) => {
        if (child instanceof THREE.Mesh) {
          child.geometry?.dispose();
          if (Array.isArray(child.material)) {
            child.material.forEach((m) => m.dispose());
          } else {
            child.material?.dispose();
          }
        }
      });
    }
    this.cache.clear();
    this.characterCache.clear();
    this.loaded = false;
  }

  private load(url: string): Promise<GLTF> {
    return new Promise((resolve, reject) => {
      this.loader.load(url, resolve, undefined, reject);
    });
  }
}
