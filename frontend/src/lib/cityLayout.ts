/**
 * City 3D Layout — TypeScript port of playground-3d-layout.js
 * Defines the 21×21 city grid with buildings, roads, and nature
 */

// ==================== City Configuration ====================

export const CITY = { WIDTH: 21, DEPTH: 21, TILE_SIZE: 1 } as const;

// ==================== Grid Cell Interface ====================

export interface PlacedItem {
  gx: number;
  gz: number;
  type: string;
  name: string;
  rotation: number;
  isGround?: boolean;
  scale?: number;
  y?: number;
}

// ==================== City Grid ====================
// Legend:
// Roads: R=straight(Z), H=straight(X), +=crossroad, T=T-intersection, L=bend, E=dead-end
// Ground: B=building slot, .=empty, P=park, G=garden, M=market, C=corner, S=side
// Path: PS=short, PL=long, PM=messy  (suffix 1-4 = rotation 0°/90°/180°/270°)

const CITY_GRID: string[][] = [
  ['B','B','E4','B','B','E4','B','B','E4','B','B','E4','B','B','E4','C3','S2','S2','S2','S2','C2'],
  ['B','B','H','B','B','H','B','B','H','B','B','H','B','B','H','S3','P','P','P','P','S1'],
  ['E','R','+','R','R','+','R','R','+','R','R','+','R','R','T4','S3','P','P','P','P','S1'],
  ['B','B','H','B','B','H','B','B','H','B','B','H','B','B','H','S3','P','P','P','P','S1'],
  ['B','B','H','B','B','H','B','B','H','B','B','H','B','B','H','S3','P','P','P','P','S1'],
  ['E','R','+','R','R','+','R','R','+','R','R','+','R','R','T4','S3','P','P','P','P','S1'],
  ['B','B','H','B','B','H','C3','C2','H','B','B','H','B','B','H','S3','P','P','P','P','S1'],
  ['B','B','H','B','B','H','C4','C1','H','B','B','H','B','B','H','C4','S4','S4','S4','S4','C1'],
  ['E','R','+','R','R','+','R','R','+','R','R','+','R','R','+','R','R','R','R','R','L'],
  ['B','B','H','B','B','H','B','B','H','B','B','H','B','B','H','B','B','B','B','B','H'],
  ['B','B','H','B','B','H','B','B','H','B','B','H','B','B','H','B','B','B','B','B','H'],
  ['E','R','+','R','R','T3','R','R','T3','R','R','+','R','R','T4','B','B','B','B','B','H'],
  ['B','B','H','M','M','M','M','M','M','M','M','H','B','B','H','B','B','B','B','B','H'],
  ['B','B','H','M','M','M','M','M','M','M','M','H','B','B','H','B','B','B','B','B','H'],
  ['E','R','T4','M','M','M','M','M','M','M','M','T2','R','R','+','R','R','R','R','R','L4'],
  ['C3','C2','H','M','M','M','M','M','M','M','M','H','M','M','H','C3','S2','S2','S2','S2','C2'],
  ['C4','C1','H','M','M','M','M','M','M','M','M','H','M','M','H','C4','S4','S4','S4','S4','C1'],
  ['E','R','T4','M','M','M','M','M','L2','R','R','+','R','R','+','R','R','R','R','R','E3'],
  ['B','B','H','M','M','M','M','M','H','B','B','H','B','B','H','C3','S2','S2','S2','S2','C2'],
  ['B','B','H','M','M','M','M','M','H','B','B','H','B','B','H','C4','S4','S4','S4','S4','C1'],
  ['E','R','T3','R','R','R','R','R','T3','R','R','T3','R','R','T3','R','R','R','R','R','E3'],
];

// ==================== Building Definitions ====================

export const BUILDINGS: PlacedItem[] = [
  // Zone A: Back-left blocks
  { gx:0, gz:0, type:'building', name:'skyscraperA', rotation:0 },
  { gx:1, gz:0, type:'building', name:'a', rotation:0 },
  { gx:0, gz:1, type:'building', name:'b', rotation:0 },
  { gx:1, gz:1, type:'building', name:'c', rotation:0 },
  { gx:0, gz:3, type:'building', name:'d', rotation:0 },
  { gx:1, gz:3, type:'building', name:'e', rotation:0 },
  { gx:0, gz:4, type:'building', name:'f', rotation:0 },
  { gx:1, gz:4, type:'building', name:'g', rotation:0 },
  // Zone B: Second column (X=3-4)
  { gx:3, gz:0, type:'building', name:'i', rotation:Math.PI/2 },
  { gx:4, gz:0, type:'building', name:'h', rotation:Math.PI/2 },
  { gx:3, gz:1, type:'building', name:'a', rotation:Math.PI/2 },
  { gx:4, gz:1, type:'building', name:'b', rotation:Math.PI/2 },
  { gx:3, gz:3, type:'building', name:'c', rotation:Math.PI/2 },
  { gx:4, gz:3, type:'building', name:'d', rotation:Math.PI/2 },
  { gx:3, gz:4, type:'building', name:'e', rotation:Math.PI/2 },
  { gx:4, gz:4, type:'building', name:'skyscraperA', rotation:Math.PI/2 },
  // Zone C: Third column (X=6-7)
  { gx:6, gz:0, type:'building', name:'f', rotation:0 },
  { gx:7, gz:0, type:'building', name:'g', rotation:0 },
  { gx:6, gz:1, type:'building', name:'h', rotation:0 },
  { gx:7, gz:1, type:'building', name:'j', rotation:0 },
  { gx:6, gz:3, type:'building', name:'a', rotation:0 },
  { gx:7, gz:3, type:'building', name:'b', rotation:0 },
  { gx:6, gz:4, type:'building', name:'c', rotation:0 },
  { gx:7, gz:4, type:'building', name:'d', rotation:0 },
  // Zone D: Fourth column (X=9-10)
  { gx:9, gz:0, type:'building', name:'skyscraperA', rotation:Math.PI },
  { gx:10,gz:0, type:'building', name:'e', rotation:Math.PI },
  { gx:9, gz:1, type:'building', name:'f', rotation:Math.PI },
  { gx:10,gz:1, type:'building', name:'g', rotation:Math.PI },
  { gx:9, gz:3, type:'building', name:'h', rotation:Math.PI },
  { gx:10,gz:3, type:'building', name:'a', rotation:Math.PI },
  { gx:9, gz:4, type:'building', name:'b', rotation:Math.PI },
  { gx:10,gz:4, type:'building', name:'k', rotation:Math.PI },
  // Zone E: Fifth column (X=12-13)
  { gx:12,gz:0, type:'building', name:'c', rotation:-Math.PI/2 },
  { gx:13,gz:0, type:'building', name:'d', rotation:-Math.PI/2 },
  { gx:12,gz:1, type:'building', name:'e', rotation:-Math.PI/2 },
  { gx:13,gz:1, type:'building', name:'f', rotation:-Math.PI/2 },
  { gx:12,gz:3, type:'building', name:'g', rotation:-Math.PI/2 },
  { gx:13,gz:3, type:'building', name:'h', rotation:-Math.PI/2 },
  { gx:12,gz:4, type:'building', name:'a', rotation:-Math.PI/2 },
  { gx:13,gz:4, type:'building', name:'skyscraperA', rotation:-Math.PI/2 },
  // Central blocks (Z=6-7)
  { gx:0, gz:6, type:'building', name:'b', rotation:0 },
  { gx:1, gz:6, type:'building', name:'c', rotation:0 },
  { gx:0, gz:7, type:'building', name:'d', rotation:0 },
  { gx:1, gz:7, type:'building', name:'e', rotation:0 },
  { gx:3, gz:6, type:'building', name:'f', rotation:Math.PI/2 },
  { gx:4, gz:6, type:'building', name:'l', rotation:Math.PI/2 },
  { gx:3, gz:7, type:'building', name:'g', rotation:Math.PI/2 },
  { gx:4, gz:7, type:'building', name:'h', rotation:Math.PI/2 },
  { gx:9, gz:6, type:'building', name:'a', rotation:Math.PI },
  { gx:10,gz:6, type:'building', name:'b', rotation:Math.PI },
  { gx:9, gz:7, type:'building', name:'c', rotation:Math.PI },
  { gx:10,gz:7, type:'building', name:'d', rotation:Math.PI },
  { gx:12,gz:6, type:'building', name:'e', rotation:-Math.PI/2 },
  { gx:13,gz:6, type:'building', name:'skyscraperA', rotation:-Math.PI/2 },
  { gx:12,gz:7, type:'building', name:'f', rotation:-Math.PI/2 },
  { gx:13,gz:7, type:'building', name:'g', rotation:-Math.PI/2 },
  // Zone F: Lower section (Z=9-10)
  { gx:0, gz:9, type:'building', name:'skyscraperA', rotation:0 },
  { gx:1, gz:9, type:'building', name:'h', rotation:0 },
  { gx:0, gz:10,type:'building', name:'a', rotation:0 },
  { gx:1, gz:10,type:'building', name:'b', rotation:0 },
  { gx:3, gz:9, type:'building', name:'c', rotation:Math.PI/2 },
  { gx:4, gz:9, type:'building', name:'d', rotation:Math.PI/2 },
  { gx:3, gz:10,type:'building', name:'e', rotation:Math.PI/2 },
  { gx:4, gz:10,type:'building', name:'f', rotation:Math.PI/2 },
  { gx:6, gz:9, type:'building', name:'g', rotation:0 },
  { gx:7, gz:9, type:'building', name:'skyscraperA', rotation:0 },
  { gx:6, gz:10,type:'building', name:'h', rotation:0 },
  { gx:7, gz:10,type:'building', name:'a', rotation:0 },
  { gx:9, gz:9, type:'building', name:'b', rotation:Math.PI },
  { gx:10,gz:9, type:'building', name:'c', rotation:Math.PI },
  { gx:9, gz:10,type:'building', name:'d', rotation:Math.PI },
  { gx:10,gz:10,type:'building', name:'skyscraperA', rotation:Math.PI },
  { gx:12,gz:9, type:'building', name:'e', rotation:-Math.PI/2 },
  { gx:13,gz:9, type:'building', name:'f', rotation:-Math.PI/2 },
  { gx:12,gz:10,type:'building', name:'g', rotation:-Math.PI/2 },
  { gx:13,gz:10,type:'building', name:'h', rotation:-Math.PI/2 },
  // Lower blocks
  { gx:3, gz:12,type:'building', name:'skyscraperB', rotation:Math.PI/2 },
  { gx:3, gz:13,type:'building', name:'skyscraperB', rotation:Math.PI/2 },
  { gx:4, gz:12,type:'building', name:'skyscraperB', rotation:Math.PI/2 },
  { gx:4, gz:13,type:'building', name:'skyscraperB', rotation:Math.PI/2 },
  { gx:3, gz:15,type:'building', name:'skyscraperB', rotation:Math.PI/2 },
  { gx:3, gz:16,type:'building', name:'skyscraperB', rotation:Math.PI/2 },
  { gx:4, gz:15,type:'building', name:'skyscraperB', rotation:Math.PI/2 },
  { gx:4, gz:16,type:'building', name:'skyscraperB', rotation:Math.PI/2 },
  { gx:12,gz:12,type:'building', name:'f', rotation:-Math.PI/2 },
  { gx:13,gz:12,type:'building', name:'g', rotation:-Math.PI/2 },
  { gx:12,gz:13,type:'building', name:'h', rotation:-Math.PI/2 },
  { gx:13,gz:13,type:'building', name:'a', rotation:-Math.PI/2 },
  { gx:12,gz:15,type:'building', name:'d', rotation:-Math.PI/2 },
  { gx:13,gz:15,type:'building', name:'e', rotation:-Math.PI/2 },
  { gx:12,gz:16,type:'building', name:'f', rotation:-Math.PI/2 },
  { gx:13,gz:16,type:'building', name:'g', rotation:-Math.PI/2 },
  // Bottom rows (Z=18-19)
  { gx:0, gz:18,type:'building', name:'g', rotation:0 },
  { gx:1, gz:18,type:'building', name:'h', rotation:0 },
  { gx:0, gz:19,type:'building', name:'skyscraperA', rotation:0 },
  { gx:1, gz:19,type:'building', name:'a', rotation:0 },
  { gx:3, gz:18,type:'building', name:'b', rotation:Math.PI/2 },
  { gx:4, gz:18,type:'building', name:'c', rotation:Math.PI/2 },
  { gx:3, gz:19,type:'building', name:'d', rotation:Math.PI/2 },
  { gx:4, gz:19,type:'building', name:'e', rotation:Math.PI/2 },
  { gx:9, gz:18,type:'building', name:'a', rotation:Math.PI },
  { gx:10,gz:18,type:'building', name:'b', rotation:Math.PI },
  { gx:9, gz:19,type:'building', name:'c', rotation:Math.PI },
  { gx:10,gz:19,type:'building', name:'skyscraperA', rotation:Math.PI },
  { gx:12,gz:18,type:'building', name:'d', rotation:-Math.PI/2 },
  { gx:13,gz:18,type:'building', name:'e', rotation:-Math.PI/2 },
  { gx:12,gz:19,type:'building', name:'f', rotation:-Math.PI/2 },
  { gx:13,gz:19,type:'building', name:'g', rotation:-Math.PI/2 },
  // Right side
  { gx:15,gz:15,type:'building', name:'d', rotation:-Math.PI/2 },
  { gx:16,gz:15,type:'building', name:'e', rotation:-Math.PI/2 },
  { gx:15,gz:16,type:'building', name:'f', rotation:-Math.PI/2 },
  { gx:16,gz:16,type:'building', name:'h', rotation:-Math.PI/2 },
  { gx:15,gz:18,type:'building', name:'g', rotation:-Math.PI/2 },
  { gx:16,gz:18,type:'building', name:'h', rotation:-Math.PI/2 },
];

// ==================== Nature Definitions ====================

export const NATURE: PlacedItem[] = [
  // Main Park (X=15-20, Z=0-7)
  { gx:15, gz:0, type:'park', name:'treeTall', rotation:0, scale:1.2 },
  { gx:16.5, gz:0.3, type:'park', name:'tree', rotation:Math.PI/6 },
  { gx:18, gz:0, type:'park', name:'treeAutumnTall', rotation:Math.PI/3 },
  { gx:19.5, gz:0.2, type:'park', name:'treeTall', rotation:Math.PI/2 },
  { gx:20, gz:1, type:'park', name:'tree', rotation:-Math.PI/4 },
  { gx:20, gz:3, type:'park', name:'treeAutumn', rotation:0 },
  { gx:20, gz:5, type:'park', name:'treeTall', rotation:Math.PI/5 },
  { gx:20, gz:7, type:'park', name:'tree', rotation:Math.PI/3 },
  { gx:15, gz:1.5, type:'park', name:'treeAutumn', rotation:Math.PI/4 },
  { gx:15, gz:3.5, type:'park', name:'tree', rotation:-Math.PI/6 },
  { gx:15, gz:5.5, type:'park', name:'treeTall', rotation:Math.PI/2 },
  { gx:15, gz:7, type:'park', name:'treeAutumnTall', rotation:0 },
  // Central pond
  { gx:17.5, gz:3, type:'park', name:'rockFlatGrass', rotation:0, scale:1.5 },
  { gx:17, gz:2.5, type:'park', name:'rockA', rotation:Math.PI/4 },
  { gx:18.5, gz:2.3, type:'park', name:'rockB', rotation:Math.PI/2 },
  { gx:19, gz:3.5, type:'park', name:'rockC', rotation:-Math.PI/3 },
  { gx:17.2, gz:4, type:'park', name:'rockFlat', rotation:Math.PI },
  { gx:18.8, gz:4.2, type:'park', name:'rockA', rotation:0 },
  { gx:16.2, gz:2, type:'park', name:'patchGrassLarge', rotation:0, y:0.1 },
  { gx:19.3, gz:2, type:'park', name:'patchGrass', rotation:Math.PI/3 },
  { gx:16.5, gz:4.5, type:'park', name:'grassLarge', rotation:Math.PI/4 },
  { gx:19, gz:4.8, type:'park', name:'grass', rotation:-Math.PI/6 },
  // Campfire area
  { gx:17, gz:6, type:'park', name:'campfirePit', rotation:0 },
  { gx:16.2, gz:5.8, type:'park', name:'treeLog', rotation:Math.PI/4 },
  { gx:17.8, gz:5.6, type:'park', name:'treeLogSmall', rotation:-Math.PI/3 },
  { gx:16.5, gz:6.8, type:'park', name:'treeLogSmall', rotation:Math.PI/2 },
  { gx:17.5, gz:6.5, type:'park', name:'bucket', rotation:0 },
  // Scattered trees
  { gx:16.3, gz:1.2, type:'park', name:'tree', rotation:Math.PI/5 },
  { gx:18.7, gz:1, type:'park', name:'treeAutumn', rotation:-Math.PI/4 },
  { gx:19.2, gz:5.5, type:'park', name:'tree', rotation:Math.PI/3 },
  { gx:16, gz:4.8, type:'park', name:'treeTall', rotation:0 },
  // Park entrance
  { gx:17.5, gz:7.5, type:'park', name:'signpost', rotation:Math.PI },
  { gx:16, gz:7.3, type:'park', name:'grass', rotation:0 },
  { gx:19, gz:7.2, type:'park', name:'patchGrass', rotation:Math.PI/6 },
  // Extra
  { gx:18.3, gz:0.8, type:'park', name:'rockB', rotation:Math.PI/5 },
  { gx:15.5, gz:2.5, type:'park', name:'grass', rotation:0 },
  { gx:19.5, gz:6, type:'park', name:'barrel', rotation:Math.PI/4 },
  { gx:16.8, gz:3.2, type:'park', name:'patchGrass', rotation:Math.PI/2 },
  // Small garden A (X=6-7, Z=6-7)
  { gx:5.8, gz:5.8, type:'park', name:'tree', rotation:0 },
  { gx:7.1, gz:6.1, type:'park', name:'patchGrassLarge', rotation:Math.PI/4, y:0.1 },
  { gx:6.2, gz:7.0, type:'park', name:'rockFlatGrass', rotation:0 },
  { gx:6.7, gz:6.9, type:'park', name:'rockFlatGrass', rotation:36 },
  // Small garden B (X=0-1, Z=15-16)
  { gx:0.3, gz:15.3, type:'park', name:'treeTall', rotation:Math.PI/6 },
  { gx:1, gz:15.5, type:'park', name:'patchGrass', rotation:0, y:0.1 },
  { gx:0.5, gz:16, type:'park', name:'rockA', rotation:Math.PI/2 },
  { gx:1, gz:16.1, type:'park', name:'grass', rotation:-Math.PI/4, y:0.2 },
  { gx:1.2, gz:16.3, type:'park', name:'grass', rotation:-Math.PI/3, y:0.2 },
  { gx:1.2, gz:16.1, type:'park', name:'grass', rotation:-Math.PI, y:0.2 },
  { gx:1, gz:16.2, type:'park', name:'grass', rotation:-Math.PI/5, y:0.2 },
  { gx:1, gz:16.4, type:'park', name:'grass', rotation:-Math.PI/6, y:0.2 },
  { gx:1, gz:16.1, type:'park', name:'grass', rotation:-Math.PI/7, y:0.2 },
  { gx:0.8, gz:15.8, type:'park', name:'signpostSingle', rotation:Math.PI },
  // Small garden C (X=17-20, Z=18-19)
  { gx:17.5, gz:18.3, type:'park', name:'treeAutumn', rotation:0 },
  { gx:19, gz:18.5, type:'park', name:'tree', rotation:Math.PI/3 },
  { gx:20, gz:18.2, type:'park', name:'treeTall', rotation:-Math.PI/4 },
  { gx:18, gz:18.8, type:'park', name:'patchGrassLarge', rotation:Math.PI/6, y:0.1 },
  { gx:19.5, gz:19, type:'park', name:'rockB', rotation:0 },
  { gx:17.3, gz:19, type:'park', name:'grass', rotation:Math.PI/2 },
  { gx:20, gz:19.2, type:'park', name:'treeAutumnTall', rotation:Math.PI/5 },
  // Metal panels along park edges
  ...[14.6,15.1,15.6,16.1,16.6,17.1,17.6,18.1,18.6,19.1,19.35].map(x => ({ gx:x, gz:8.4, type:'park', name:'metalPanel', rotation:0 })),
  ...[14.6,15.1,15.6,16.1,16.6,17.1,17.6,18.1,18.6,19.1,19.35].map(x => ({ gx:x, gz:13.6, type:'park', name:'metalPanel', rotation:0 })),
  ...[8.65,9.15,9.65,10.15,10.65,11.15,11.65,12.15,12.65,13.15,13.40].map(z => ({ gx:14.4, gz:z, type:'park', name:'metalPanel', rotation:Math.PI/2 })),
  ...[8.65,9.15,9.65,10.15,10.65,11.15,11.65,12.15,12.65,13.15,13.40].map(z => ({ gx:19.6, gz:z, type:'park', name:'metalPanel', rotation:Math.PI/2 })),
  // Rocks
  { gx:15.3, gz:9.5, type:'park', name:'rockC', rotation:Math.PI/3 },
  { gx:14.8, gz:8.7, type:'park', name:'rockC', rotation:0 },
  { gx:14.8, gz:9, type:'park', name:'rockC', rotation:Math.PI/7 },
  { gx:14.8, gz:9.3, type:'park', name:'rockC', rotation:Math.PI/2 },
  { gx:15.3, gz:8.8, type:'park', name:'rockC', rotation:Math.PI/4 },
  // Floor old
  ...[12.1,12.4,12.7,13,13.3].map(z => ({ gx:14.7, gz:z, type:'park', name:'floorOld', rotation:0 })),
  ...[12.1,12.4,12.7,13,13.3].map(z => ({ gx:15.1, gz:z, type:'park', name:'floorOld', rotation:0 })),
  // Barrels
  { gx:14.6, gz:12.9, type:'park', name:'barrel', rotation:0 },
  { gx:14.6, gz:13.15, type:'park', name:'barrel', rotation:0 },
  { gx:14.6, gz:13.4, type:'park', name:'barrel', rotation:0 },
  // Grass patches
  { gx:17, gz:12, type:'park', name:'patchGrassLarge', rotation:0, y:0.05 },
  { gx:17, gz:11, type:'park', name:'patchGrassLarge', rotation:Math.PI/2, y:0.05 },
  { gx:17.5, gz:11, type:'park', name:'patchGrassLarge', rotation:Math.PI, y:0.05 },
  { gx:17.6, gz:11.5, type:'park', name:'patchGrassLarge', rotation:Math.PI/3, y:0.05 },
  // Tree logs
  { gx:16.2, gz:13.1, type:'park', name:'treeLog', rotation:Math.PI/2, y:0.05 },
  { gx:16.1, gz:13.3, type:'park', name:'treeLog', rotation:Math.PI/2, y:0.05 },
  { gx:16.2, gz:13.5, type:'park', name:'treeLog', rotation:Math.PI/2, y:0.05 },
  { gx:16.15,gz:13.2, type:'park', name:'treeLog', rotation:Math.PI/2, y:0.25 },
  { gx:16.2, gz:13.4, type:'park', name:'treeLog', rotation:Math.PI/2, y:0.25 },
  // Boxes
  { gx:19.15, gz:8.77, type:'park', name:'boxLarge', rotation:0, y:0.05 },
  { gx:19.12, gz:8.8, type:'park', name:'boxLarge', rotation:0, y:0.05 },
  { gx:19.23, gz:9.1, type:'park', name:'boxLarge', rotation:0, y:0.05 },
  { gx:19.11, gz:8.88, type:'park', name:'boxLarge', rotation:0, y:0.3 },
  { gx:19.284,gz:9.04, type:'park', name:'boxLarge', rotation:0, y:0.25 },
  { gx:19.35, gz:8.7, type:'park', name:'boxLarge', rotation:0, y:0.05 },
  { gx:19.45, gz:8.9, type:'park', name:'boxLarge', rotation:0, y:0.05 },
  { gx:19.45, gz:9.1, type:'park', name:'boxLarge', rotation:0, y:0.05 },
  { gx:19.40, gz:8.8, type:'park', name:'boxLarge', rotation:0, y:0.25 },
  { gx:19.45, gz:9, type:'park', name:'boxLarge', rotation:0, y:0.25 },
];

// ==================== Road & Ground Tile Parsing ====================

function parseCellCode(cell: string): { base: string; rotationIndex: number } {
  const match = cell.match(/^(.+?)([1-4])?$/);
  if (!match) return { base: cell, rotationIndex: 1 };
  return { base: match[1], rotationIndex: match[2] ? parseInt(match[2]) : 1 };
}

function rotationIndexToRadians(index: number): number {
  return (index - 1) * (Math.PI / 2);
}

const ROAD_MAP: Record<string, { name: string; baseRotation: number }> = {
  R: { name: 'straight', baseRotation: 0 },
  H: { name: 'straight', baseRotation: Math.PI / 2 },
  '+': { name: 'crossroad', baseRotation: 0 },
  T: { name: 'intersection', baseRotation: 0 },
  L: { name: 'bend', baseRotation: 0 },
  E: { name: 'end', baseRotation: 0 },
};

export function getRoads(): PlacedItem[] {
  const roads: PlacedItem[] = [];
  for (let gz = 0; gz < CITY.DEPTH; gz++) {
    for (let gx = 0; gx < CITY.WIDTH; gx++) {
      const { base, rotationIndex } = parseCellCode(CITY_GRID[gz][gx]);
      const cfg = ROAD_MAP[base];
      if (cfg) {
        roads.push({
          gx, gz, type: 'road', name: cfg.name,
          rotation: cfg.baseRotation + rotationIndexToRadians(rotationIndex),
        });
      }
    }
  }
  return roads;
}

const GROUND_TILE_MAP: Record<string, { type: string; name: string; isGround?: boolean }> = {
  B: { type: 'tile', name: 'low' },
  '.': { type: 'tile', name: 'low' },
  P: { type: 'minigolf', name: 'open', isGround: true },
  G: { type: 'minigolf', name: 'open', isGround: true },
  M: { type: 'market', name: 'floor', isGround: true },
  C: { type: 'minigolf', name: 'corner', isGround: true },
  S: { type: 'minigolf', name: 'side', isGround: true },
  PS: { type: 'suburban', name: 'pathStonesShort', isGround: true },
  PL: { type: 'suburban', name: 'pathStonesLong', isGround: true },
  PM: { type: 'suburban', name: 'pathStonesMessy', isGround: true },
};

export function getGroundTiles(): PlacedItem[] {
  const tiles: PlacedItem[] = [];
  for (let gz = 0; gz < CITY.DEPTH; gz++) {
    for (let gx = 0; gx < CITY.WIDTH; gx++) {
      const { base, rotationIndex } = parseCellCode(CITY_GRID[gz][gx]);
      const cfg = GROUND_TILE_MAP[base];
      if (cfg) {
        tiles.push({
          gx, gz, type: cfg.type, name: cfg.name,
          rotation: rotationIndexToRadians(rotationIndex),
          isGround: cfg.isGround ?? false,
        });
      }
    }
  }
  return tiles;
}

// ==================== Walkable Map (for pathfinding) ====================

const WALKABLE_BASES = new Set(['R','H','+','T','L','E','P','G','M','C','S','PS','PL','PM']);

export function generateWalkableMap(): { grid: number[][]; width: number; height: number } {
  const grid: number[][] = [];
  for (let gz = 0; gz < CITY.DEPTH; gz++) {
    const row: number[] = [];
    for (let gx = 0; gx < CITY.WIDTH; gx++) {
      const { base } = parseCellCode(CITY_GRID[gz][gx]);
      row.push(WALKABLE_BASES.has(base) ? 1 : 0);
    }
    grid.push(row);
  }
  return { grid, width: CITY.WIDTH, height: CITY.DEPTH };
}
