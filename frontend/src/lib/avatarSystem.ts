/**
 * AvatarSystem — TypeScript port of playground-avatar-system.js + pathfinding.js
 * Handles avatar rendering, bone-based animation, A* pathfinding, and wandering AI
 *
 * Bone names come from Kenney mini-characters GLB models:
 *   root, torso, head, arm-left, arm-right, leg-left, leg-right
 *
 * Usage (matches PlaygroundTab expectations):
 *   const sys = new AvatarSystem();
 *   await sys.init(scene);
 *   sys.syncSessions(sessionList);
 *   sys.update(dtMs);
 *   sys.dispose();
 */
import * as THREE from 'three';
import { GLTFLoader, type GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { clone as skeletonClone } from 'three/examples/jsm/utils/SkeletonUtils.js';
import { CITY, generateWalkableMap } from './cityLayout';

// ==================== Pathfinding ====================

interface PathNode {
  x: number;
  y: number;
  g: number;
  h: number;
  f: number;
  parent: PathNode | null;
}

class Grid {
  width: number;
  height: number;
  data: number[][];

  constructor(width: number, height: number, data: number[][]) {
    this.width = width;
    this.height = height;
    this.data = data;
  }

  isWalkable(x: number, y: number): boolean {
    if (x < 0 || x >= this.width || y < 0 || y >= this.height) return false;
    return this.data[y][x] === 1;
  }

  getNeighbors(x: number, y: number): [number, number][] {
    const neighbors: [number, number][] = [];
    const dirs: [number, number][] = [
      [0, -1], [0, 1], [-1, 0], [1, 0],
      [-1, -1], [-1, 1], [1, -1], [1, 1],
    ];
    for (const [dx, dy] of dirs) {
      const nx = x + dx;
      const ny = y + dy;
      if (this.isWalkable(nx, ny)) {
        if (dx !== 0 && dy !== 0) {
          if (!this.isWalkable(x + dx, y) || !this.isWalkable(x, y + dy)) continue;
        }
        neighbors.push([nx, ny]);
      }
    }
    return neighbors;
  }
}

class Pathfinder {
  private grid: Grid;

  constructor(grid: Grid) {
    this.grid = grid;
  }

  findPath(sx: number, sy: number, ex: number, ey: number): [number, number][] | null {
    if (!this.grid.isWalkable(sx, sy) || !this.grid.isWalkable(ex, ey)) return null;
    if (sx === ex && sy === ey) return [[sx, sy]];

    const open: PathNode[] = [];
    const closedSet = new Set<string>();
    const key = (x: number, y: number) => `${x},${y}`;

    const heuristic = (ax: number, ay: number, bx: number, by: number) => {
      const dx = Math.abs(ax - bx);
      const dy = Math.abs(ay - by);
      return Math.max(dx, dy) + (Math.SQRT2 - 1) * Math.min(dx, dy);
    };

    const startNode: PathNode = { x: sx, y: sy, g: 0, h: heuristic(sx, sy, ex, ey), f: 0, parent: null };
    startNode.f = startNode.h;
    open.push(startNode);

    const gScores = new Map<string, number>();
    gScores.set(key(sx, sy), 0);

    while (open.length > 0) {
      let lowestIdx = 0;
      for (let i = 1; i < open.length; i++) {
        if (open[i].f < open[lowestIdx].f) lowestIdx = i;
      }
      const current = open.splice(lowestIdx, 1)[0];

      if (current.x === ex && current.y === ey) {
        const path: [number, number][] = [];
        let node: PathNode | null = current;
        while (node) {
          path.unshift([node.x, node.y]);
          node = node.parent;
        }
        return path;
      }

      closedSet.add(key(current.x, current.y));

      for (const [nx, ny] of this.grid.getNeighbors(current.x, current.y)) {
        if (closedSet.has(key(nx, ny))) continue;
        const isDiag = nx !== current.x && ny !== current.y;
        const cost = isDiag ? Math.SQRT2 : 1;
        const ng = current.g + cost;
        const existingG = gScores.get(key(nx, ny));

        if (existingG !== undefined && ng >= existingG) continue;
        gScores.set(key(nx, ny), ng);

        const h = heuristic(nx, ny, ex, ey);
        const neighbor: PathNode = { x: nx, y: ny, g: ng, h, f: ng + h, parent: current };

        const existIdx = open.findIndex(n => n.x === nx && n.y === ny);
        if (existIdx >= 0) {
          open[existIdx] = neighbor;
        } else {
          open.push(neighbor);
        }
      }
    }

    return null;
  }
}

// ==================== Avatar Configuration (matches legacy exactly) ====================

type AnimState = 'idle' | 'walk' | 'run' | 'thinking';

/** Animation speeds in radians/second — must match legacy AVATAR_CONFIG.animSpeed */
const ANIM_SPEED: Record<AnimState, number> = {
  idle: 2.0,
  walk: 8.0,
  run: 12.0,
  thinking: 3.0,
};

/** Per-bone rotation amplitudes & phase offsets — exact copy of legacy boneAnim */
interface BoneAnimConfig {
  rotX?: number;
  rotY?: number;
  rotZ?: number;
  phaseOffset?: number;
}

type BoneAnimSet = {
  torso?: BoneAnimConfig;
  head?: BoneAnimConfig;
  armLeft?: BoneAnimConfig;
  armRight?: BoneAnimConfig;
  legLeft?: BoneAnimConfig;
  legRight?: BoneAnimConfig;
};

const BONE_ANIM: Record<AnimState, BoneAnimSet> = {
  idle: {
    torso:    { rotX: 0.03, rotZ: 0.01 },
    head:     { rotX: 0.04, rotY: 0.06 },
    armLeft:  { rotX: 0.08, rotZ: 0.0, phaseOffset: 0 },
    armRight: { rotX: 0.08, rotZ: 0.0, phaseOffset: Math.PI },
    legLeft:  { rotX: 0.02, phaseOffset: 0 },
    legRight: { rotX: 0.02, phaseOffset: Math.PI },
  },
  walk: {
    torso:    { rotX: 0.06, rotZ: 0.08 },
    head:     { rotX: 0.04 },
    armLeft:  { rotX: 0.6, rotZ: 0.0, phaseOffset: 0 },
    armRight: { rotX: 0.6, rotZ: 0.0, phaseOffset: Math.PI },
    legLeft:  { rotX: 0.5, phaseOffset: Math.PI },
    legRight: { rotX: 0.5, phaseOffset: 0 },
  },
  run: {
    torso:    { rotX: 0.1, rotZ: 0.12 },
    head:     { rotX: 0.06 },
    armLeft:  { rotX: 0.9, rotZ: 0.0, phaseOffset: 0 },
    armRight: { rotX: 0.9, rotZ: 0.0, phaseOffset: Math.PI },
    legLeft:  { rotX: 0.8, phaseOffset: Math.PI },
    legRight: { rotX: 0.8, phaseOffset: 0 },
  },
  thinking: {
    torso:    { rotX: 0.05 },
    head:     { rotX: 0.08, rotY: 0.15 },
    armLeft:  { rotX: 0.2, rotZ: 0.0 },
    armRight: { rotX: 1.0, rotZ: 0.2 },   // hand on chin
    legLeft:  { rotX: 0.0 },
    legRight: { rotX: 0.0 },
  },
};

/** Direction to Y-axis rotation mapping (model faces −Z by default) */
const DIRECTION_ROTATION: Record<string, number> = {
  N:  0,
  NE: -Math.PI / 4,
  E:  -Math.PI / 2,
  SE: -Math.PI * 3 / 4,
  S:  Math.PI,
  SW: Math.PI * 3 / 4,
  W:  Math.PI / 2,
  NW: Math.PI / 4,
};

const MOVEMENT = {
  walkSpeed: 1.5,
  runSpeed: 3.0,
  rotationSpeed: 8.0,
} as const;

const WANDER = {
  minIdleTime: 3000,   // ms
  maxIdleTime: 10000,  // ms
  maxWanderDistance: 6,
} as const;

// ==================== Character Models ====================

const CHARACTER_MODELS = [
  'character-female-a', 'character-female-b', 'character-female-c',
  'character-female-d', 'character-female-e', 'character-female-f',
  'character-male-a', 'character-male-b', 'character-male-c',
  'character-male-d', 'character-male-e', 'character-male-f',
];

const CHARACTERS_PATH = '/assets/kenney_mini-characters/Models/GLB format';

// ==================== Bone Cache Interface ====================

interface BoneCache {
  root: THREE.Bone | null;
  torso: THREE.Bone | null;
  head: THREE.Bone | null;
  armLeft: THREE.Bone | null;
  armRight: THREE.Bone | null;
  legLeft: THREE.Bone | null;
  legRight: THREE.Bone | null;
  initialRotations: Record<string, THREE.Euler>;
}

// ==================== Avatar Data ====================

interface AvatarData {
  name: string;
  sessionId: string;
  /** The THREE.Group placed in the scene — PlaygroundTab reads this */
  container: THREE.Group;
  model: THREE.Object3D;
  bones: BoneCache;
  state: AnimState;
  animPhase: number;
  label: THREE.Sprite;
  gridX: number;
  gridZ: number;
  path: [number, number][] | null;
  pathIndex: number;
  isMoving: boolean;
  /** Direction label (N,NE,E,...) */
  direction: string;
  targetDirection: string;
  currentRotationY: number;
  /** Accumulated idle time in ms */
  idleTimer: number;
  nextWanderTime: number;
  isProcessing: boolean;
  lastStatus: string;
}

// ==================== Helper ====================

function calculateDirection(dx: number, dz: number): string {
  if (dx === 0 && dz === 0) return 'S';
  const angle = Math.atan2(dx, dz);
  const deg = (angle * 180 / Math.PI + 360) % 360;
  if (deg >= 337.5 || deg < 22.5)  return 'N';
  if (deg >= 22.5  && deg < 67.5)  return 'NW';
  if (deg >= 67.5  && deg < 112.5) return 'W';
  if (deg >= 112.5 && deg < 157.5) return 'SW';
  if (deg >= 157.5 && deg < 202.5) return 'S';
  if (deg >= 202.5 && deg < 247.5) return 'SE';
  if (deg >= 247.5 && deg < 292.5) return 'E';
  if (deg >= 292.5 && deg < 337.5) return 'NE';
  return 'S';
}

function randomWanderDelay(): number {
  return WANDER.minIdleTime + Math.random() * (WANDER.maxIdleTime - WANDER.minIdleTime);
}

// ==================== AvatarSystem ====================

export class AvatarSystem {
  /** Public avatar map — keyed by session_id */
  avatars: Map<string, AvatarData> = new Map();

  private scene!: THREE.Scene;
  private pathfinder!: Pathfinder;
  private characterGLTFs: Map<string, GLTF> = new Map();
  private characterAssignment: Map<string, string> = new Map();
  private usedCharacters: Set<string> = new Set();
  private walkableCandidates: [number, number][] = [];
  private disposed = false;

  constructor() {
    // Lightweight — actual setup happens in init()
  }

  /** Load character models & build pathfinding grid */
  async init(scene: THREE.Scene): Promise<void> {
    this.scene = scene;

    // Pathfinder
    const walkable = generateWalkableMap();
    const grid = new Grid(walkable.width, walkable.height, walkable.grid);
    this.pathfinder = new Pathfinder(grid);

    // Cache walkable cells
    for (let z = 0; z < walkable.height; z++) {
      for (let x = 0; x < walkable.width; x++) {
        if (walkable.grid[z][x] === 1) this.walkableCandidates.push([x, z]);
      }
    }

    // Load character GLBs
    const loader = new GLTFLoader();
    const loadOne = (name: string): Promise<void> =>
      new Promise((resolve) => {
        const url = `${CHARACTERS_PATH}/${name}.glb`;
        loader.load(url, (gltf) => {
          this.characterGLTFs.set(name, gltf);
          resolve();
        }, undefined, () => {
          console.warn(`[AvatarSystem] Failed to load ${name}`);
          resolve();
        });
      });

    await Promise.all(CHARACTER_MODELS.map(loadOne));
  }

  /** Sync avatars with current session list */
  syncSessions(sessions: Array<{ session_id: string; session_name?: string; status?: string }>): void {
    if (this.disposed) return;

    const activeIds = new Set(sessions.map(s => s.session_id));

    // Remove gone sessions
    for (const id of [...this.avatars.keys()]) {
      if (!activeIds.has(id)) this.removeAvatar(id);
    }

    // Add / update
    for (const session of sessions) {
      const existing = this.avatars.get(session.session_id);
      if (existing) {
        if (session.status && session.status !== existing.lastStatus) {
          existing.lastStatus = session.status;
          if (session.status === 'thinking' || session.status === 'processing') {
            existing.state = 'thinking';
            existing.isProcessing = true;
          }
        }
      } else {
        this.addAvatar(session.session_id, session.session_name || session.session_id.substring(0, 8));
      }
    }
  }

  /** Frame update — dt is in **milliseconds** (performance.now delta) */
  update(dtMs: number): void {
    if (this.disposed) return;
    const dt = dtMs / 1000; // convert to seconds internally

    for (const avatar of this.avatars.values()) {
      this.updateMovement(avatar, dt);
      this.updateAnimation(avatar, dt);
      this.updateWandering(avatar, dtMs);     // legacy passes ms here
      this.updateRotation(avatar, dt);
    }
  }

  /** Clean up everything */
  dispose(): void {
    this.disposed = true;
    for (const id of [...this.avatars.keys()]) this.removeAvatar(id);
    this.avatars.clear();
    this.characterAssignment.clear();
    this.usedCharacters.clear();
    this.characterGLTFs.clear();
  }

  // ==================== Private Methods ====================

  private addAvatar(sessionId: string, name: string): void {
    const charName = this.assignCharacter(sessionId);
    const gltf = this.characterGLTFs.get(charName);
    if (!gltf) return;

    const model = skeletonClone(gltf.scene) as THREE.Object3D;
    model.scale.setScalar(0.5);

    // Cache bones by matching Kenney bone names (lowercase)
    const bones = this.cacheBones(model);

    // Enable shadows
    model.traverse((child) => {
      if ((child as THREE.Mesh).isMesh) {
        (child as THREE.Mesh).castShadow = true;
        (child as THREE.Mesh).receiveShadow = true;
      }
    });

    const container = new THREE.Group();
    container.add(model);

    const spawn = this.randomWalkable();
    container.position.set(spawn[0], 0, spawn[1]);

    const label = this.createLabel(name);
    label.position.set(0, 0.8, 0);
    container.add(label);

    this.scene.add(container);

    this.avatars.set(sessionId, {
      name, sessionId, container, model, bones,
      state: 'idle',
      animPhase: Math.random() * Math.PI * 2,
      label,
      gridX: spawn[0], gridZ: spawn[1],
      path: null, pathIndex: 0, isMoving: false,
      direction: 'S', targetDirection: 'S',
      currentRotationY: Math.PI,   // facing south initially
      idleTimer: 0,
      nextWanderTime: randomWanderDelay(),
      isProcessing: false, lastStatus: '',
    });
  }

  /**
   * Cache bone references from model skeleton.
   * Kenney mini-characters have: root, torso, head, arm-left, arm-right, leg-left, leg-right
   * We map the lowercase bone names to our camelCase keys and store initial rotations.
   */
  private cacheBones(model: THREE.Object3D): BoneCache {
    const cache: BoneCache = {
      root: null, torso: null, head: null,
      armLeft: null, armRight: null,
      legLeft: null, legRight: null,
      initialRotations: {},
    };

    // Name mapping: GLB bone name (lowercase) → key in BoneCache
    const nameMap: Record<string, keyof Omit<BoneCache, 'initialRotations'>> = {
      'root':      'root',
      'torso':     'torso',
      'head':      'head',
      'arm-left':  'armLeft',
      'arm-right': 'armRight',
      'leg-left':  'legLeft',
      'leg-right': 'legRight',
    };

    // Try to get skeleton from SkinnedMesh first
    let skeleton: THREE.Skeleton | null = null;
    model.traverse((child) => {
      if ((child as THREE.SkinnedMesh).isSkinnedMesh && (child as THREE.SkinnedMesh).skeleton && !skeleton) {
        skeleton = (child as THREE.SkinnedMesh).skeleton;
      }
    });

    const processBone = (bone: THREE.Bone) => {
      const lowerName = bone.name.toLowerCase();
      const key = nameMap[lowerName];
      if (key) {
        cache[key] = bone;
        cache.initialRotations[key] = bone.rotation.clone();
      }
    };

    if (skeleton) {
      for (const bone of (skeleton as THREE.Skeleton).bones) {
        processBone(bone);
      }
    } else {
      // Fallback: traverse model directly
      model.traverse((child) => {
        if ((child as THREE.Bone).isBone) {
          processBone(child as THREE.Bone);
        }
      });
    }

    return cache;
  }

  private removeAvatar(sessionId: string): void {
    const avatar = this.avatars.get(sessionId);
    if (!avatar) return;
    this.scene.remove(avatar.container);
    avatar.container.traverse((child) => {
      if (child instanceof THREE.Mesh) {
        child.geometry?.dispose();
        const mats = Array.isArray(child.material) ? child.material : [child.material];
        mats.forEach(m => m?.dispose());
      }
      if (child instanceof THREE.Sprite) {
        (child.material as THREE.SpriteMaterial).map?.dispose();
        child.material.dispose();
      }
    });
    this.avatars.delete(sessionId);
    const charName = this.characterAssignment.get(sessionId);
    if (charName) { this.usedCharacters.delete(charName); this.characterAssignment.delete(sessionId); }
  }

  private assignCharacter(sessionId: string): string {
    if (this.characterAssignment.has(sessionId)) return this.characterAssignment.get(sessionId)!;
    const available = CHARACTER_MODELS.filter(n => !this.usedCharacters.has(n));
    const chosen = available.length > 0
      ? available[Math.floor(Math.random() * available.length)]
      : CHARACTER_MODELS[Math.floor(Math.random() * CHARACTER_MODELS.length)];
    this.characterAssignment.set(sessionId, chosen);
    this.usedCharacters.add(chosen);
    return chosen;
  }

  private randomWalkable(): [number, number] {
    if (this.walkableCandidates.length === 0) return [10, 10];
    return this.walkableCandidates[Math.floor(Math.random() * this.walkableCandidates.length)];
  }

  private createLabel(text: string): THREE.Sprite {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d')!;

    // Measure text first
    ctx.font = 'bold 24px Arial, sans-serif';
    const metrics = ctx.measureText(text);
    const textWidth = metrics.width;
    const padding = 12;
    canvas.width = textWidth + padding * 2;
    canvas.height = 24 + padding;

    // Background
    ctx.fillStyle = '#333333';
    ctx.beginPath();
    ctx.roundRect(0, 0, canvas.width, canvas.height, 6);
    ctx.fill();

    // Text
    ctx.font = 'bold 24px Arial, sans-serif';
    ctx.fillStyle = '#ffffff';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, canvas.width / 2, canvas.height / 2);

    const texture = new THREE.CanvasTexture(canvas);
    texture.needsUpdate = true;
    const material = new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false });
    const sprite = new THREE.Sprite(material);
    const scale = 0.005;
    sprite.scale.set(canvas.width * scale, canvas.height * scale, 1);
    return sprite;
  }

  // ==================== Movement ====================

  private updateMovement(avatar: AvatarData, dt: number): void {
    if (!avatar.isMoving || !avatar.path || avatar.path.length === 0) return;

    const currentWaypoint = avatar.path[avatar.pathIndex];
    if (!currentWaypoint) {
      this.stopMovement(avatar);
      return;
    }

    const [wpX, wpZ] = currentWaypoint;
    const dx = wpX - avatar.gridX;
    const dz = wpZ - avatar.gridZ;
    const distance = Math.sqrt(dx * dx + dz * dz);

    if (distance < 0.05) {
      // Reached waypoint
      avatar.gridX = wpX;
      avatar.gridZ = wpZ;
      avatar.pathIndex++;

      if (avatar.pathIndex >= avatar.path.length) {
        this.stopMovement(avatar);
        return;
      }
    } else {
      // Move towards waypoint
      const speed = avatar.state === 'run' ? MOVEMENT.runSpeed : MOVEMENT.walkSpeed;
      const moveStep = speed * dt;
      const nx = dx / distance;
      const nz = dz / distance;

      avatar.gridX += nx * Math.min(moveStep, distance);
      avatar.gridZ += nz * Math.min(moveStep, distance);

      // Update target direction based on movement
      avatar.targetDirection = calculateDirection(nx, nz);
    }

    // Update container position
    avatar.container.position.x = avatar.gridX;
    avatar.container.position.z = avatar.gridZ;
  }

  private stopMovement(avatar: AvatarData): void {
    avatar.isMoving = false;
    avatar.path = null;
    avatar.pathIndex = 0;
    avatar.state = 'idle';
    avatar.idleTimer = 0;
    avatar.nextWanderTime = randomWanderDelay();
  }

  /** Wandering timer uses milliseconds (matching legacy) */
  private updateWandering(avatar: AvatarData, deltaTimeMs: number): void {
    if (avatar.isMoving) return;
    if (avatar.isProcessing) return;

    avatar.idleTimer += deltaTimeMs;

    if (avatar.idleTimer >= avatar.nextWanderTime) {
      this.startRandomWander(avatar);
    }
  }

  private startRandomWander(avatar: AvatarData): void {
    const maxDist = WANDER.maxWanderDistance;
    const currentX = Math.round(avatar.gridX);
    const currentZ = Math.round(avatar.gridZ);

    // Filter nearby road positions within wander distance
    const nearbyRoads = this.walkableCandidates.filter(([px, pz]) => {
      const dx = px - currentX;
      const dz = pz - currentZ;
      const dist = Math.sqrt(dx * dx + dz * dz);
      return dist > 0 && dist <= maxDist;
    });

    if (nearbyRoads.length === 0) {
      avatar.idleTimer = 0;
      avatar.nextWanderTime = randomWanderDelay();
      return;
    }

    const dest = nearbyRoads[Math.floor(Math.random() * nearbyRoads.length)];
    const path = this.pathfinder.findPath(currentX, currentZ, dest[0], dest[1]);

    if (path && path.length > 1) {
      avatar.path = path;
      avatar.pathIndex = 1; // skip the start position
      avatar.isMoving = true;
      avatar.state = 'walk';
      avatar.idleTimer = 0;
    } else {
      avatar.idleTimer = 0;
      avatar.nextWanderTime = randomWanderDelay();
    }
  }

  // ==================== Smooth Direction Rotation ====================

  private updateRotation(avatar: AvatarData, dt: number): void {
    const targetRotY = DIRECTION_ROTATION[avatar.targetDirection] ?? 0;
    const rotSpeed = MOVEMENT.rotationSpeed;

    // Rotation difference normalised to [−π, π]
    let diff = targetRotY - avatar.currentRotationY;
    while (diff > Math.PI) diff -= Math.PI * 2;
    while (diff < -Math.PI) diff += Math.PI * 2;

    // Smooth interpolation
    avatar.currentRotationY += diff * Math.min(dt * rotSpeed, 1);

    // Apply to model (not container) — matches legacy
    avatar.model.rotation.y = avatar.currentRotationY;
    avatar.direction = avatar.targetDirection;
  }

  // ==================== Bone-Based Procedural Animation ====================

  /**
   * Update bone animation exactly as legacy does:
   * 1. Advance animPhase by dt * speed
   * 2. Look up boneAnim config for current animState
   * 3. For each bone, call _animateBone with config + initial rotation + phase
   */
  private updateAnimation(avatar: AvatarData, dt: number): void {
    const { state, bones } = avatar;
    if (!bones) return;

    const speed = ANIM_SPEED[state] ?? ANIM_SPEED.idle;
    avatar.animPhase += dt * speed;
    const t = avatar.animPhase;

    const boneAnim = BONE_ANIM[state] ?? BONE_ANIM.idle;
    const initRot = bones.initialRotations;

    this.animateBone(bones.torso,    boneAnim.torso,    initRot.torso,    t);
    this.animateBone(bones.head,     boneAnim.head,     initRot.head,     t);
    this.animateBone(bones.armLeft,  boneAnim.armLeft,  initRot.armLeft,  t);
    this.animateBone(bones.armRight, boneAnim.armRight, initRot.armRight, t);
    this.animateBone(bones.legLeft,  boneAnim.legLeft,  initRot.legLeft,  t);
    this.animateBone(bones.legRight, boneAnim.legRight, initRot.legRight, t);
  }

  /**
   * Animate a single bone — exact port of legacy _animateBone:
   *   bone.rotation.x = init.x + config.rotX * sin(phase)
   *   bone.rotation.y = init.y + config.rotY * sin(phase * 0.7)
   *   bone.rotation.z = init.z + config.rotZ * sin(phase * 0.8)
   */
  private animateBone(
    bone: THREE.Bone | null,
    config: BoneAnimConfig | undefined,
    initialRotation: THREE.Euler | undefined,
    t: number,
  ): void {
    if (!bone || !config) return;

    const init = initialRotation ?? { x: 0, y: 0, z: 0 };
    const phase = t + (config.phaseOffset ?? 0);

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
}
