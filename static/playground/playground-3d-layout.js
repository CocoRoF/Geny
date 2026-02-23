/**
 * City 3D Layout
 * Defines a city grid with buildings, roads, and nature
 *
 * Coordinate System:
 * - X: Left to Right
 * - Y: Up (height)
 * - Z: Back to Front
 *
 * Grid: Each cell is 1x1 unit (roads and buildings occupy cells)
 */
(function() {
    'use strict';

    window.Playground = window.Playground || {};

    // ==================== City Configuration ====================
    const CITY = {
        WIDTH: 21,   // X axis (tiles) - more breathing room
        DEPTH: 21,   // Z axis (tiles) - more breathing room
        TILE_SIZE: 1
    };

    // ==================== City Grid Definition ====================
    // Legend:
    //
    // === ROTATION SYSTEM ===
    // All tiles support rotation suffix: 1=0°, 2=90°, 3=180°, 4=270°
    // If no suffix, defaults to 1 (0° rotation)
    // Example: 'PS' = 'PS1' = 0°, 'PS2' = 90°, 'PS3' = 180°, 'PS4' = 270°
    //
    // === Roads ===
    // 'R' = Road straight (vertical, Z-axis direction)
    // 'H' = Road straight (horizontal, X-axis direction)
    // '+' = Crossroad (4-way intersection)
    // 'T' = T-intersection (T1-T4 for rotation)
    // 'L' = L-Bend/Corner (L1-L4 for rotation)
    // 'E' = Road end/dead-end (E1-E4 for rotation)
    //
    // === Ground Tiles ===
    // 'B' = Building slot (concrete)
    // '.' = Empty ground tile (concrete)
    // 'P' = Park/nature area (minigolf grass)
    // 'G' = Green space / small garden (minigolf grass)
    // 'M' = Market floor tile (checkered)
    // 'C' = Minigolf corner tile (C1-C4 for rotation)
    // 'S' = Minigolf side tile (S1-S4 for rotation)
    //
    // === Path Stones (from suburban kit) ===
    // 'PS' = Path stones short (PS1-PS4 for rotation)
    // 'PL' = Path stones long (PL1-PL4 for rotation)
    // 'PM' = Path stones messy (PM1-PM4 for rotation)

    const CITY_GRID = [
        // Z=0 (back row)
        ['B', 'B', 'E4', 'B', 'B', 'E4', 'B', 'B', 'E4', 'B', 'B', 'E4', 'B', 'B', 'E4', 'C3', 'S2', 'S2', 'S2', 'S2', 'C2'],
        // Z=1
        ['B', 'B', 'H', 'B', 'B', 'H', 'B', 'B', 'H', 'B', 'B', 'H', 'B', 'B', 'H', 'S3', 'P', 'P', 'P', 'P', 'S1'],
        // Z=2 (road row)
        ['E', 'R', '+', 'R', 'R', '+', 'R', 'R', '+', 'R', 'R', '+', 'R', 'R', 'T4', 'S3', 'P', 'P', 'P', 'P', 'S1'],
        // Z=3
        ['B', 'B', 'H', 'B', 'B', 'H', 'B', 'B', 'H', 'B', 'B', 'H', 'B', 'B', 'H', 'S3', 'P', 'P', 'P', 'P', 'S1'],
        // Z=4
        ['B', 'B', 'H', 'B', 'B', 'H', 'B', 'B', 'H', 'B', 'B', 'H', 'B', 'B', 'H', 'S3', 'P', 'P', 'P', 'P', 'S1'],
        // Z=5 (road row)
        ['E', 'R', '+', 'R', 'R', '+', 'R', 'R', '+', 'R', 'R', '+', 'R', 'R', 'T4', 'S3', 'P', 'P', 'P', 'P', 'S1'],
        // Z=6
        ['B', 'B', 'H', 'B', 'B', 'H', 'C3', 'C2', 'H', 'B', 'B', 'H', 'B', 'B', 'H', 'S3', 'P', 'P', 'P', 'P', 'S1'],
        // Z=7
        ['B', 'B', 'H', 'B', 'B', 'H', 'C4', 'C1', 'H', 'B', 'B', 'H', 'B', 'B', 'H', 'C4', 'S4', 'S4', 'S4', 'S4', 'C1'],
        // Z=8 (road row)
        ['E', 'R', '+', 'R', 'R', '+', 'R', 'R', '+', 'R', 'R', '+', 'R', 'R', '+', 'R', 'R', 'R', 'R', 'R', 'L'],
        // Z=9
        ['B', 'B', 'H', 'B', 'B', 'H', 'B', 'B', 'H', 'B', 'B', 'H', 'B', 'B', 'H', 'B', 'B', 'B', 'B', 'B', 'H'],
        // Z=10
        ['B', 'B', 'H', 'B', 'B', 'H', 'B', 'B', 'H', 'B', 'B', 'H', 'B', 'B', 'H', 'B', 'B', 'B', 'B', 'B', 'H'],
        // Z=11 (road row)
        ['E', 'R', '+', 'R', 'R', 'T3', 'R', 'R', 'T3', 'R', 'R', '+', 'R', 'R', 'T4', 'B', 'B', 'B', 'B', 'B', 'H'],
        // Z=12
        ['B', 'B', 'H', 'M', 'M', 'M', 'M', 'M', 'M', 'M', 'M', 'H', 'B', 'B', 'H', 'B', 'B', 'B', 'B', 'B', 'H'],
        // Z=13
        ['B', 'B', 'H', 'M', 'M', 'M', 'M', 'M', 'M', 'M', 'M', 'H', 'B', 'B', 'H', 'B', 'B', 'B', 'B', 'B', 'H'],
        // Z=14 (road row)
        ['E', 'R', 'T4', 'M', 'M', 'M', 'M', 'M', 'M', 'M', 'M', 'T2', 'R', 'R', '+', 'R', 'R', 'R', 'R', 'R', 'L4'],
        // Z=15
        ['C3', 'C2', 'H', 'M', 'M', 'M', 'M', 'M', 'M', 'M', 'M', 'H', 'M', 'M', 'H', 'C3', 'S2', 'S2', 'S2', 'S2', 'C2'],
        // Z=16
        ['C4', 'C1', 'H', 'M', 'M', 'M', 'M', 'M', 'M', 'M', 'M', 'H', 'M', 'M', 'H', 'C4', 'S4', 'S4', 'S4', 'S4', 'C1'],
        // Z=17 (road row)
        ['E', 'R', 'T4', 'M', 'M', 'M', 'M', 'M', 'L2', 'R', 'R', '+', 'R', 'R', '+', 'R', 'R', 'R', 'R', 'R', 'E3'],
        // Z=18
        ['B', 'B', 'H', 'M', 'M', 'M', 'M', 'M', 'H', 'B', 'B', 'H', 'B', 'B', 'H', 'C3', 'S2', 'S2', 'S2', 'S2', 'C2'],
        // Z=19
        ['B', 'B', 'H', 'M', 'M', 'M', 'M', 'M', 'H', 'B', 'B', 'H', 'B', 'B', 'H', 'C4', 'S4', 'S4', 'S4', 'S4', 'C1'],
        // Z=20 (front row)
        ['E', 'R', 'T3', 'R', 'R', 'R', 'R', 'R', 'T3', 'R', 'R', 'T3', 'R', 'R', 'T3', 'R', 'R', 'R', 'R', 'R', 'E3']
    ];

    // ==================== Building Definitions ====================
    // Define which building goes where - Spacious city with proper breathing room
    const BUILDINGS = [
        // ===== Zone A: Back-left blocks (Z=0-1, X=0-1 and Z=3-4, X=0-1) =====
        { gx: 0, gz: 0, type: 'building', name: 'skyscraperA', rotation: 0 },
        { gx: 1, gz: 0, type: 'building', name: 'a', rotation: 0 },
        { gx: 0, gz: 1, type: 'building', name: 'b', rotation: 0 },
        { gx: 1, gz: 1, type: 'building', name: 'c', rotation: 0 },
        { gx: 0, gz: 3, type: 'building', name: 'd', rotation: 0 },
        { gx: 1, gz: 3, type: 'building', name: 'e', rotation: 0 },
        { gx: 0, gz: 4, type: 'building', name: 'f', rotation: 0 },
        { gx: 1, gz: 4, type: 'building', name: 'g', rotation: 0 },

        // ===== Zone B: Second column (X=3-4) =====
        { gx: 3, gz: 0, type: 'building', name: 'i', rotation: Math.PI / 2 },
        { gx: 4, gz: 0, type: 'building', name: 'h', rotation: Math.PI / 2 },
        { gx: 3, gz: 1, type: 'building', name: 'a', rotation: Math.PI / 2 },
        { gx: 4, gz: 1, type: 'building', name: 'b', rotation: Math.PI / 2 },
        { gx: 3, gz: 3, type: 'building', name: 'c', rotation: Math.PI / 2 },
        { gx: 4, gz: 3, type: 'building', name: 'd', rotation: Math.PI / 2 },
        { gx: 3, gz: 4, type: 'building', name: 'e', rotation: Math.PI / 2 },
        { gx: 4, gz: 4, type: 'building', name: 'skyscraperA', rotation: Math.PI / 2 },

        // ===== Zone C: Third column (X=6-7) =====
        { gx: 6, gz: 0, type: 'building', name: 'f', rotation: 0 },
        { gx: 7, gz: 0, type: 'building', name: 'g', rotation: 0 },
        { gx: 6, gz: 1, type: 'building', name: 'h', rotation: 0 },
        { gx: 7, gz: 1, type: 'building', name: 'j', rotation: 0 },
        { gx: 6, gz: 3, type: 'building', name: 'a', rotation: 0 },
        { gx: 7, gz: 3, type: 'building', name: 'b', rotation: 0 },
        { gx: 6, gz: 4, type: 'building', name: 'c', rotation: 0 },
        { gx: 7, gz: 4, type: 'building', name: 'd', rotation: 0 },

        // ===== Zone D: Fourth column (X=9-10) =====
        { gx: 9, gz: 0, type: 'building', name: 'skyscraperA', rotation: Math.PI },
        { gx: 10, gz: 0, type: 'building', name: 'e', rotation: Math.PI },
        { gx: 9, gz: 1, type: 'building', name: 'f', rotation: Math.PI },
        { gx: 10, gz: 1, type: 'building', name: 'g', rotation: Math.PI },
        { gx: 9, gz: 3, type: 'building', name: 'h', rotation: Math.PI },
        { gx: 10, gz: 3, type: 'building', name: 'a', rotation: Math.PI },
        { gx: 9, gz: 4, type: 'building', name: 'b', rotation: Math.PI },
        { gx: 10, gz: 4, type: 'building', name: 'k', rotation: Math.PI },

        // ===== Zone E: Fifth column (X=12-13) =====
        { gx: 12, gz: 0, type: 'building', name: 'c', rotation: -Math.PI / 2 },
        { gx: 13, gz: 0, type: 'building', name: 'd', rotation: -Math.PI / 2 },
        { gx: 12, gz: 1, type: 'building', name: 'e', rotation: -Math.PI / 2 },
        { gx: 13, gz: 1, type: 'building', name: 'f', rotation: -Math.PI / 2 },
        { gx: 12, gz: 3, type: 'building', name: 'g', rotation: -Math.PI / 2 },
        { gx: 13, gz: 3, type: 'building', name: 'h', rotation: -Math.PI / 2 },
        { gx: 12, gz: 4, type: 'building', name: 'a', rotation: -Math.PI / 2 },
        { gx: 13, gz: 4, type: 'building', name: 'skyscraperA', rotation: -Math.PI / 2 },

        // ===== Central blocks (Z=6-7, X=0-4 and Z=9-10, X=0-4) - skipping small garden =====
        { gx: 0, gz: 6, type: 'building', name: 'b', rotation: 0 },
        { gx: 1, gz: 6, type: 'building', name: 'c', rotation: 0 },
        { gx: 0, gz: 7, type: 'building', name: 'd', rotation: 0 },
        { gx: 1, gz: 7, type: 'building', name: 'e', rotation: 0 },
        { gx: 3, gz: 6, type: 'building', name: 'f', rotation: Math.PI / 2 },
        { gx: 4, gz: 6, type: 'building', name: 'l', rotation: Math.PI / 2 },
        { gx: 3, gz: 7, type: 'building', name: 'g', rotation: Math.PI / 2 },
        { gx: 4, gz: 7, type: 'building', name: 'h', rotation: Math.PI / 2 },
        // Garden at gx=6-7, gz=6-7

        { gx: 9, gz: 6, type: 'building', name: 'a', rotation: Math.PI },
        { gx: 10, gz: 6, type: 'building', name: 'b', rotation: Math.PI },
        { gx: 9, gz: 7, type: 'building', name: 'c', rotation: Math.PI },
        { gx: 10, gz: 7, type: 'building', name: 'd', rotation: Math.PI },
        { gx: 12, gz: 6, type: 'building', name: 'e', rotation: -Math.PI / 2 },
        { gx: 13, gz: 6, type: 'building', name: 'skyscraperA', rotation: -Math.PI / 2 },
        { gx: 12, gz: 7, type: 'building', name: 'f', rotation: -Math.PI / 2 },
        { gx: 13, gz: 7, type: 'building', name: 'g', rotation: -Math.PI / 2 },

        // ===== Zone F: Lower section (Z=9-10, Z=12-13) =====
        { gx: 0, gz: 9, type: 'building', name: 'skyscraperA', rotation: 0 },
        { gx: 1, gz: 9, type: 'building', name: 'h', rotation: 0 },
        { gx: 0, gz: 10, type: 'building', name: 'a', rotation: 0 },
        { gx: 1, gz: 10, type: 'building', name: 'b', rotation: 0 },
        { gx: 3, gz: 9, type: 'building', name: 'c', rotation: Math.PI / 2 },
        { gx: 4, gz: 9, type: 'building', name: 'd', rotation: Math.PI / 2 },
        { gx: 3, gz: 10, type: 'building', name: 'e', rotation: Math.PI / 2 },
        { gx: 4, gz: 10, type: 'building', name: 'f', rotation: Math.PI / 2 },
        { gx: 6, gz: 9, type: 'building', name: 'g', rotation: 0 },
        { gx: 7, gz: 9, type: 'building', name: 'skyscraperA', rotation: 0 },
        { gx: 6, gz: 10, type: 'building', name: 'h', rotation: 0 },
        { gx: 7, gz: 10, type: 'building', name: 'a', rotation: 0 },
        { gx: 9, gz: 9, type: 'building', name: 'b', rotation: Math.PI },
        { gx: 10, gz: 9, type: 'building', name: 'c', rotation: Math.PI },
        { gx: 9, gz: 10, type: 'building', name: 'd', rotation: Math.PI },
        { gx: 10, gz: 10, type: 'building', name: 'skyscraperA', rotation: Math.PI },
        { gx: 12, gz: 9, type: 'building', name: 'e', rotation: -Math.PI / 2 },
        { gx: 13, gz: 9, type: 'building', name: 'f', rotation: -Math.PI / 2 },
        { gx: 12, gz: 10, type: 'building', name: 'g', rotation: -Math.PI / 2 },
        { gx: 13, gz: 10, type: 'building', name: 'h', rotation: -Math.PI / 2 },

        // Bottom rows continuing
        // { gx: 0, gz: 12, type: 'building', name: 'a', rotation: 0 },
        // { gx: 1, gz: 12, type: 'building', name: 'skyscraperA', rotation: 0 },
        // { gx: 0, gz: 13, type: 'building', name: 'b', rotation: 0 },
        // { gx: 1, gz: 13, type: 'building', name: 'c', rotation: 0 },
        // { gx: 3, gz: 12, type: 'building', name: 'd', rotation: Math.PI / 2 },
        // { gx: 4, gz: 12, type: 'building', name: 'e', rotation: Math.PI / 2 },
        // { gx: 3, gz: 13, type: 'building', name: 'f', rotation: Math.PI / 2 },
        { gx: 3, gz: 12, type: 'building', name: 'skyscraperB', rotation: Math.PI / 2 },
        { gx: 3, gz: 13, type: 'building', name: 'skyscraperB', rotation: Math.PI / 2 },
        { gx: 4, gz: 12, type: 'building', name: 'skyscraperB', rotation: Math.PI / 2 },
        { gx: 4, gz: 13, type: 'building', name: 'skyscraperB', rotation: Math.PI / 2 },
        { gx: 3, gz: 15, type: 'building', name: 'skyscraperB', rotation: Math.PI / 2 },
        { gx: 3, gz: 16, type: 'building', name: 'skyscraperB', rotation: Math.PI / 2 },
        { gx: 4, gz: 15, type: 'building', name: 'skyscraperB', rotation: Math.PI / 2 },
        { gx: 4, gz: 16, type: 'building', name: 'skyscraperB', rotation: Math.PI / 2 },
        // { gx: 6, gz: 12, type: 'building', name: 'g', rotation: 0 },
        // { gx: 7, gz: 12, type: 'building', name: 'h', rotation: 0 },
        // { gx: 6, gz: 13, type: 'building', name: 'a', rotation: 0 },
        // { gx: 7, gz: 13, type: 'building', name: 'b', rotation: 0 },
        // { gx: 9, gz: 12, type: 'building', name: 'c', rotation: Math.PI },
        // { gx: 10, gz: 12, type: 'building', name: 'd', rotation: Math.PI },
        // { gx: 9, gz: 13, type: 'building', name: 'e', rotation: Math.PI },
        // { gx: 10, gz: 13, type: 'building', name: 'skyscraperA', rotation: Math.PI },
        { gx: 12, gz: 12, type: 'building', name: 'f', rotation: -Math.PI / 2 },
        { gx: 13, gz: 12, type: 'building', name: 'g', rotation: -Math.PI / 2 },
        { gx: 12, gz: 13, type: 'building', name: 'h', rotation: -Math.PI / 2 },
        { gx: 13, gz: 13, type: 'building', name: 'a', rotation: -Math.PI / 2 },

        // ===== Rows with garden at front-left (Z=15-16, skipping X=0-1) =====
        { gx: 12, gz: 15, type: 'building', name: 'd', rotation: -Math.PI / 2 },
        { gx: 13, gz: 15, type: 'building', name: 'e', rotation: -Math.PI / 2 },
        { gx: 12, gz: 16, type: 'building', name: 'f', rotation: -Math.PI / 2 },
        { gx: 13, gz: 16, type: 'building', name: 'g', rotation: -Math.PI / 2 },

        // ===== Bottom rows (Z=18-19) =====
        { gx: 0, gz: 18, type: 'building', name: 'g', rotation: 0 },
        { gx: 1, gz: 18, type: 'building', name: 'h', rotation: 0 },
        { gx: 0, gz: 19, type: 'building', name: 'skyscraperA', rotation: 0 },
        { gx: 1, gz: 19, type: 'building', name: 'a', rotation: 0 },
        { gx: 3, gz: 18, type: 'building', name: 'b', rotation: Math.PI / 2 },
        { gx: 4, gz: 18, type: 'building', name: 'c', rotation: Math.PI / 2 },
        { gx: 3, gz: 19, type: 'building', name: 'd', rotation: Math.PI / 2 },
        { gx: 4, gz: 19, type: 'building', name: 'e', rotation: Math.PI / 2 },
        { gx: 9, gz: 18, type: 'building', name: 'a', rotation: Math.PI },
        { gx: 10, gz: 18, type: 'building', name: 'b', rotation: Math.PI },
        { gx: 9, gz: 19, type: 'building', name: 'c', rotation: Math.PI },
        { gx: 10, gz: 19, type: 'building', name: 'skyscraperA', rotation: Math.PI },
        { gx: 12, gz: 18, type: 'building', name: 'd', rotation: -Math.PI / 2 },
        { gx: 13, gz: 18, type: 'building', name: 'e', rotation: -Math.PI / 2 },
        { gx: 12, gz: 19, type: 'building', name: 'f', rotation: -Math.PI / 2 },
        { gx: 13, gz: 19, type: 'building', name: 'g', rotation: -Math.PI / 2 },

        // Right side buildings (X=15-16, various Z not in park)
        // { gx: 15, gz: 9, type: 'building', name: 'h', rotation: -Math.PI / 2 },
        // { gx: 16, gz: 9, type: 'building', name: 'skyscraperB', rotation: -Math.PI / 2 },
        // { gx: 17, gz: 9, type: 'building', name: 'a', rotation: -Math.PI / 2 },
        // { gx: 18, gz: 9, type: 'building', name: 'b', rotation: -Math.PI / 2 },
        // { gx: 19, gz: 9, type: 'building', name: 'c', rotation: -Math.PI / 2 },
        // { gx: 20, gz: 9, type: 'building', name: 'd', rotation: -Math.PI / 2 },
        // { gx: 15, gz: 10, type: 'building', name: 'e', rotation: -Math.PI / 2 },
        // { gx: 16, gz: 10, type: 'building', name: 'f', rotation: -Math.PI / 2 },
        // { gx: 17, gz: 10, type: 'building', name: 'skyscraperA', rotation: -Math.PI / 2 },
        // { gx: 18, gz: 10, type: 'building', name: 'g', rotation: -Math.PI / 2 },
        // { gx: 19, gz: 10, type: 'building', name: 'h', rotation: -Math.PI / 2 },
        // { gx: 20, gz: 10, type: 'building', name: 'a', rotation: -Math.PI / 2 },

        // { gx: 15, gz: 12, type: 'building', name: 'b', rotation: -Math.PI / 2 },
        // { gx: 16, gz: 12, type: 'building', name: 'c', rotation: -Math.PI / 2 },
        // { gx: 17, gz: 12, type: 'building', name: 'd', rotation: -Math.PI / 2 },
        // { gx: 18, gz: 12, type: 'building', name: 'skyscraperB', rotation: -Math.PI / 2 },
        // { gx: 19, gz: 12, type: 'building', name: 'e', rotation: -Math.PI / 2 },
        // { gx: 20, gz: 12, type: 'building', name: 'f', rotation: -Math.PI / 2 },
        // { gx: 15, gz: 13, type: 'building', name: 'g', rotation: -Math.PI / 2 },
        // { gx: 16, gz: 13, type: 'building', name: 'h', rotation: -Math.PI / 2 },
        // { gx: 17, gz: 13, type: 'building', name: 'a', rotation: -Math.PI / 2 },
        // { gx: 18, gz: 13, type: 'building', name: 'b', rotation: -Math.PI / 2 },
        // { gx: 19, gz: 13, type: 'building', name: 'skyscraperA', rotation: -Math.PI / 2 },
        // { gx: 20, gz: 13, type: 'building', name: 'c', rotation: -Math.PI / 2 },

        { gx: 15, gz: 15, type: 'building', name: 'd', rotation: -Math.PI / 2 },
        { gx: 16, gz: 15, type: 'building', name: 'e', rotation: -Math.PI / 2 },
        { gx: 15, gz: 16, type: 'building', name: 'f', rotation: -Math.PI / 2 },
        { gx: 16, gz: 16, type: 'building', name: 'h', rotation: -Math.PI / 2 },

        { gx: 15, gz: 18, type: 'building', name: 'g', rotation: -Math.PI / 2 },
        { gx: 16, gz: 18, type: 'building', name: 'h', rotation: -Math.PI / 2 }
        // Bottom-right corner is garden (X=17-20, Z=18-19)
    ];

    // ==================== Road Definitions ====================
    // Road type mapping: base code -> { name, baseRotation }
    // baseRotation is added to the rotation from suffix (1-4)
    const ROAD_MAP = {
        'R': { name: 'straight', baseRotation: 0 },
        'H': { name: 'straight', baseRotation: Math.PI / 2 },
        '+': { name: 'crossroad', baseRotation: 0 },
        'T': { name: 'intersection', baseRotation: 0 },
        'L': { name: 'bend', baseRotation: 0 },
        'E': { name: 'end', baseRotation: 0 },
    };

    function getRoads() {
        const roads = [];

        for (let gz = 0; gz < CITY.DEPTH; gz++) {
            for (let gx = 0; gx < CITY.WIDTH; gx++) {
                const cell = CITY_GRID[gz][gx];
                const { base, rotationIndex } = parseCellCode(cell);

                const roadConfig = ROAD_MAP[base];
                if (roadConfig) {
                    roads.push({
                        gx,
                        gz,
                        type: 'road',
                        name: roadConfig.name,
                        rotation: roadConfig.baseRotation + rotationIndexToRadians(rotationIndex)
                    });
                }
            }
        }

        return roads;
    }

    // ==================== Nature/Park Definitions ====================
    // Main Park at X=15-20, Z=0-7 - A well-designed natural park with survival kit assets
    const NATURE = [
        // =============== MAIN PARK (X=15-20, Z=0-7) ===============

        // === Perimeter Trees - Northern Edge (Z=0) ===
        { gx: 15, gz: 0, type: 'park', name: 'treeTall', rotation: 0, scale: 1.2 },
        { gx: 16.5, gz: 0.3, type: 'park', name: 'tree', rotation: Math.PI / 6 },
        { gx: 18, gz: 0, type: 'park', name: 'treeAutumnTall', rotation: Math.PI / 3 },
        { gx: 19.5, gz: 0.2, type: 'park', name: 'treeTall', rotation: Math.PI / 2 },

        // === Perimeter Trees - Eastern Edge (X=20) ===
        { gx: 20, gz: 1, type: 'park', name: 'tree', rotation: -Math.PI / 4 },
        { gx: 20, gz: 3, type: 'park', name: 'treeAutumn', rotation: 0 },
        { gx: 20, gz: 5, type: 'park', name: 'treeTall', rotation: Math.PI / 5 },
        { gx: 20, gz: 7, type: 'park', name: 'tree', rotation: Math.PI / 3 },

        // === Perimeter Trees - Western Edge (X=15) ===
        { gx: 15, gz: 1.5, type: 'park', name: 'treeAutumn', rotation: Math.PI / 4 },
        { gx: 15, gz: 3.5, type: 'park', name: 'tree', rotation: -Math.PI / 6 },
        { gx: 15, gz: 5.5, type: 'park', name: 'treeTall', rotation: Math.PI / 2 },
        { gx: 15, gz: 7, type: 'park', name: 'treeAutumnTall', rotation: 0 },

        // === Central Pond Area with Rocks (X=17-19, Z=2-4) ===
        { gx: 17.5, gz: 3, type: 'park', name: 'rockFlatGrass', rotation: 0, scale: 1.5 },
        { gx: 17, gz: 2.5, type: 'park', name: 'rockA', rotation: Math.PI / 4 },
        { gx: 18.5, gz: 2.3, type: 'park', name: 'rockB', rotation: Math.PI / 2 },
        { gx: 19, gz: 3.5, type: 'park', name: 'rockC', rotation: -Math.PI / 3 },
        { gx: 17.2, gz: 4, type: 'park', name: 'rockFlat', rotation: Math.PI },
        { gx: 18.8, gz: 4.2, type: 'park', name: 'rockA', rotation: 0 },

        // === Grass Patches around pond ===
        { gx: 16.2, gz: 2, type: 'park', name: 'patchGrassLarge', rotation: 0, y: 0.1 },
        { gx: 19.3, gz: 2, type: 'park', name: 'patchGrass', rotation: Math.PI / 3 },
        { gx: 16.5, gz: 4.5, type: 'park', name: 'grassLarge', rotation: Math.PI / 4 },
        { gx: 19, gz: 4.8, type: 'park', name: 'grass', rotation: -Math.PI / 6 },

        // === Campfire Gathering Area (X=16-18, Z=5.5-7) ===
        { gx: 17, gz: 6, type: 'park', name: 'campfirePit', rotation: 0 },
        { gx: 16.2, gz: 5.8, type: 'park', name: 'treeLog', rotation: Math.PI / 4 },
        { gx: 17.8, gz: 5.6, type: 'park', name: 'treeLogSmall', rotation: -Math.PI / 3 },
        { gx: 16.5, gz: 6.8, type: 'park', name: 'treeLogSmall', rotation: Math.PI / 2 },
        { gx: 17.5, gz: 6.5, type: 'park', name: 'bucket', rotation: 0 },

        // === Scattered Interior Trees ===
        { gx: 16.3, gz: 1.2, type: 'park', name: 'tree', rotation: Math.PI / 5 },
        { gx: 18.7, gz: 1, type: 'park', name: 'treeAutumn', rotation: -Math.PI / 4 },
        { gx: 19.2, gz: 5.5, type: 'park', name: 'tree', rotation: Math.PI / 3 },
        { gx: 16, gz: 4.8, type: 'park', name: 'treeTall', rotation: 0 },

        // === Park Entrance & Signage (near road at Z=8) ===
        { gx: 17.5, gz: 7.5, type: 'park', name: 'signpost', rotation: Math.PI },
        { gx: 16, gz: 7.3, type: 'park', name: 'grass', rotation: 0 },
        { gx: 19, gz: 7.2, type: 'park', name: 'patchGrass', rotation: Math.PI / 6 },

        // === Additional Decoration ===
        { gx: 18.3, gz: 0.8, type: 'park', name: 'rockB', rotation: Math.PI / 5 },
        { gx: 15.5, gz: 2.5, type: 'park', name: 'grass', rotation: 0 },
        { gx: 19.5, gz: 6, type: 'park', name: 'barrel', rotation: Math.PI / 4 },
        { gx: 16.8, gz: 3.2, type: 'park', name: 'patchGrass', rotation: Math.PI / 2 },

        // =============== SMALL GARDEN A (X=6-7, Z=6-7) ===============
        { gx: 5.8, gz: 5.8, type: 'park', name: 'tree', rotation: 0 },
        { gx: 7.1, gz: 6.1, type: 'park', name: 'patchGrassLarge', rotation: Math.PI / 4, y: 0.1 },
        { gx: 6.2, gz: 7.0, type: 'park', name: 'rockFlatGrass', rotation: 0 },
        { gx: 6.7, gz: 6.9, type: 'park', name: 'rockFlatGrass', rotation: 36},

        // =============== SMALL GARDEN B (X=0-1, Z=15-16) ===============
        { gx: 0.3, gz: 15.3, type: 'park', name: 'treeTall', rotation: Math.PI / 6 },
        { gx: 1, gz: 15.5, type: 'park', name: 'patchGrass', rotation: 0, y: 0.1 },
        { gx: 0.5, gz: 16, type: 'park', name: 'rockA', rotation: Math.PI / 2 },
        { gx: 1, gz: 16.1, type: 'park', name: 'grass', rotation: -Math.PI / 4, y: 0.2 },
        { gx: 1.2, gz: 16.3, type: 'park', name: 'grass', rotation: -Math.PI / 3, y: 0.2 },
        { gx: 1.2, gz: 16.1, type: 'park', name: 'grass', rotation: -Math.PI / 1, y: 0.2 },
        { gx: 1, gz: 16.2, type: 'park', name: 'grass', rotation: -Math.PI / 5, y: 0.2 },
        { gx: 1, gz: 16.4, type: 'park', name: 'grass', rotation: -Math.PI / 6, y: 0.2 },
        { gx: 1, gz: 16.1, type: 'park', name: 'grass', rotation: -Math.PI / 7, y: 0.2 },
        { gx: 0.8, gz: 15.8, type: 'park', name: 'signpostSingle', rotation: Math.PI },

        // =============== SMALL GARDEN C (X=17-20, Z=18-19) ===============
        { gx: 17.5, gz: 18.3, type: 'park', name: 'treeAutumn', rotation: 0 },
        { gx: 19, gz: 18.5, type: 'park', name: 'tree', rotation: Math.PI / 3 },
        { gx: 20, gz: 18.2, type: 'park', name: 'treeTall', rotation: -Math.PI / 4 },
        { gx: 18, gz: 18.8, type: 'park', name: 'patchGrassLarge', rotation: Math.PI / 6, y: 0.1 },
        { gx: 19.5, gz: 19, type: 'park', name: 'rockB', rotation: 0 },
        { gx: 17.3, gz: 19, type: 'park', name: 'grass', rotation: Math.PI / 2 },
        { gx: 20, gz: 19.2, type: 'park', name: 'treeAutumnTall', rotation: Math.PI / 5 },

        // ===== Metal Panels along park edges (X=14.5-19.5, Z=8.4 and Z=13.6) =====
        { gx:14.6, gz:8.4, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:15.1, gz:8.4, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:15.6, gz:8.4, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:16.1, gz:8.4, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:16.6, gz:8.4, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:17.1, gz:8.4, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:17.6, gz:8.4, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:18.1, gz:8.4, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:18.6, gz:8.4, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:19.1, gz:8.4, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:19.35, gz:8.4, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:14.6, gz:13.6, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:15.1, gz:13.6, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:15.6, gz:13.6, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:16.1, gz:13.6, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:16.6, gz:13.6, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:17.1, gz:13.6, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:17.6, gz:13.6, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:18.1, gz:13.6, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:18.6, gz:13.6, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:19.1, gz:13.6, type: 'park', name: 'metalPanel', rotation: 0 },
        { gx:19.35, gz:13.6, type: 'park', name: 'metalPanel', rotation: 0 },

        { gx:14.4, gz:8.65, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:14.4, gz:9.15, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:14.4, gz:9.65, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:14.4, gz:10.15, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:14.4, gz:10.65, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:14.4, gz:11.15, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:14.4, gz:11.65, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:14.4, gz:12.15, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:14.4, gz:12.65, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:14.4, gz:13.15, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:14.4, gz:13.40, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:19.6, gz:8.65, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:19.6, gz:9.15, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:19.6, gz:9.65, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:19.6, gz:10.15, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:19.6, gz:10.65, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:19.6, gz:11.15, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:19.6, gz:11.65, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:19.6, gz:12.15, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:19.6, gz:12.65, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:19.6, gz:13.15, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },
        { gx:19.6, gz:13.40, type: 'park', name: 'metalPanel', rotation: Math.PI / 2 },

        { gx:15.3, gz:9.5, type: 'park', name: 'rockC', rotation: Math.PI / 3 },
        { gx:14.8, gz:8.7, type: 'park', name: 'rockC', rotation: 0 },
        { gx:14.8, gz:9, type: 'park', name: 'rockC', rotation: Math.PI / 7 },
        { gx:14.8, gz:9.3, type: 'park', name: 'rockC', rotation: Math.PI / 2 },
        { gx:15.3, gz:8.8, type: 'park', name: 'rockC', rotation: Math.PI / 4 },

        { gx:14.7, gz:12.1, type: 'park', name: 'floorOld', rotation: 0 },
        { gx:14.7, gz:12.4, type: 'park', name: 'floorOld', rotation: 0 },
        { gx:14.7, gz:12.7, type: 'park', name: 'floorOld', rotation: 0 },
        { gx:14.7, gz:13, type: 'park', name: 'floorOld', rotation: 0 },
        { gx:14.7, gz:13.3, type: 'park', name: 'floorOld', rotation: 0 },
        { gx:15.1, gz:12.1, type: 'park', name: 'floorOld', rotation: 0 },
        { gx:15.1, gz:12.4, type: 'park', name: 'floorOld', rotation: 0 },
        { gx:15.1, gz:12.7, type: 'park', name: 'floorOld', rotation: 0 },
        { gx:15.1, gz:13, type: 'park', name: 'floorOld', rotation: 0 },
        { gx:15.1, gz:13.3, type: 'park', name: 'floorOld', rotation: 0 },

        { gx:14.6, gz:12.9, type: 'park', name: 'barrel', rotation: 0 },
        { gx:14.6, gz:13.15, type: 'park', name: 'barrel', rotation: 0 },
        { gx:14.6, gz:13.4, type: 'park', name: 'barrel', rotation: 0 },


        { gx:17, gz:12, type: 'park', name: 'patchGrassLarge', rotation: 0, y: 0.05 },
        { gx:17, gz:11, type: 'park', name: 'patchGrassLarge', rotation: Math.PI / 2, y: 0.05 },
        { gx:17.5, gz:11, type: 'park', name: 'patchGrassLarge', rotation: Math.PI, y: 0.05 },
        { gx:17.6, gz:11.5, type: 'park', name: 'patchGrassLarge', rotation: Math.PI / 3, y: 0.05 },

        { gx: 16.2, gz: 13.1, type: 'park', name: 'treeLog', rotation: 0, rotation: Math.PI / 2, y: 0.05 },
        { gx: 16.1, gz: 13.3, type: 'park', name: 'treeLog', rotation: 0, rotation: Math.PI / 2, y: 0.05 },
        { gx: 16.2, gz: 13.5, type: 'park', name: 'treeLog', rotation: 0, rotation: Math.PI / 2, y: 0.05 },
        { gx: 16.15, gz: 13.2, type: 'park', name: 'treeLog', rotation: 0, rotation: Math.PI / 2, y: 0.25 },
        { gx: 16.2, gz: 13.4, type: 'park', name: 'treeLog', rotation: 0, rotation: Math.PI / 2, y: 0.25 },

        { gx: 19.15, gz: 8.77, type: 'park', name: 'boxLarge', rotation: 0, rotation: 0, y: 0.05 },
        { gx: 19.12, gz: 8.8, type: 'park', name: 'boxLarge', rotation: 0, rotation: 0, y: 0.05 },
        { gx: 19.23, gz: 9.1, type: 'park', name: 'boxLarge', rotation: 0, rotation: 0, y: 0.05 },
        { gx: 19.11, gz: 8.88, type: 'park', name: 'boxLarge', rotation: 0, rotation: 0, y: 0.3 },
        { gx: 19.284, gz: 9.04, type: 'park', name: 'boxLarge', rotation: 0, rotation: 0, y: 0.25 },
        { gx: 19.35, gz: 8.7, type: 'park', name: 'boxLarge', rotation: 0, rotation: 0, y: 0.05 },
        { gx: 19.45, gz: 8.9, type: 'park', name: 'boxLarge', rotation: 0, rotation: 0, y: 0.05 },
        { gx: 19.45, gz: 9.1, type: 'park', name: 'boxLarge', rotation: 0, rotation: 0, y: 0.05 },
        { gx: 19.40, gz: 8.8, type: 'park', name: 'boxLarge', rotation: 0, rotation: 0, y: 0.25 },
        { gx: 19.45, gz: 9, type: 'park', name: 'boxLarge', rotation: 0, rotation: 0, y: 0.25 },

    ];

    // ==================== Work Positions (Buildings) ====================
    // Characters "work" inside buildings - these are the building positions
    const WORK_POSITIONS = BUILDINGS.map((building, index) => ({
        gx: building.gx,
        gz: building.gz,
        buildingIndex: index,
        buildingName: building.name
    }));

    // ==================== Entrance Position ====================
    const ENTRANCE = {
        gx: 10,
        gz: 20,  // Front road (center of 21x21 city)
        direction: 'N'
    };

    // ==================== Pathfinding Grid ====================
    // Parse cell code: extract base type and rotation (1-4 suffix means 0°, 90°, 180°, 270°)
    function parseCellCode(cell) {
        // Match pattern: base code + optional rotation number (1-4)
        const match = cell.match(/^(.+?)([1-4])?$/);
        if (!match) return { base: cell, rotationIndex: 1 };

        const base = match[1];
        const rotationIndex = match[2] ? parseInt(match[2]) : 1;
        return { base, rotationIndex };
    }

    // Convert rotation index (1-4) to radians
    function rotationIndexToRadians(index) {
        // 1 = 0°, 2 = 90°, 3 = 180°, 4 = 270°
        return (index - 1) * (Math.PI / 2);
    }

    // Walkable tile base types (without rotation suffix)
    const WALKABLE_BASES = ['R', 'H', '+', 'T', 'L', 'E', 'P', 'G', 'M', 'C', 'S', 'PS', 'PL', 'PM'];

    function generateWalkableMap() {
        const grid = [];

        for (let gz = 0; gz < CITY.DEPTH; gz++) {
            const row = [];
            for (let gx = 0; gx < CITY.WIDTH; gx++) {
                const cell = CITY_GRID[gz][gx];
                const { base } = parseCellCode(cell);
                // Roads, parks and gardens are walkable
                const walkable = WALKABLE_BASES.includes(base);
                row.push(walkable ? 1 : 0);
            }
            grid.push(row);
        }

        return {
            grid: grid,
            width: CITY.WIDTH,
            height: CITY.DEPTH
        };
    }

    // ==================== Ground Tile Mapping ====================
    // Maps base cell code to tile configuration
    const GROUND_TILE_MAP = {
        'B': { type: 'tile', name: 'low' },
        '.': { type: 'tile', name: 'low' },
        'P': { type: 'minigolf', name: 'open', isGround: true },
        'G': { type: 'minigolf', name: 'open', isGround: true },
        'M': { type: 'market', name: 'floor', isGround: true },
        'C': { type: 'minigolf', name: 'corner', isGround: true },
        'S': { type: 'minigolf', name: 'side', isGround: true },
        'PS': { type: 'suburban', name: 'pathStonesShort', isGround: true },
        'PL': { type: 'suburban', name: 'pathStonesLong', isGround: true },
        'PM': { type: 'suburban', name: 'pathStonesMessy', isGround: true },
    };

    // ==================== Get Ground Tiles ====================
    function getGroundTiles() {
        const tiles = [];

        for (let gz = 0; gz < CITY.DEPTH; gz++) {
            for (let gx = 0; gx < CITY.WIDTH; gx++) {
                const cell = CITY_GRID[gz][gx];
                const { base, rotationIndex } = parseCellCode(cell);

                const tileConfig = GROUND_TILE_MAP[base];
                if (tileConfig) {
                    tiles.push({
                        gx,
                        gz,
                        type: tileConfig.type,
                        name: tileConfig.name,
                        rotation: rotationIndexToRadians(rotationIndex),
                        isGround: tileConfig.isGround || false
                    });
                }
            }
        }

        return tiles;
    }

    // ==================== Direction Helpers ====================
    const DIRECTION_TO_ROTATION = {
        'N': Math.PI,
        'NE': Math.PI * 0.75,
        'E': Math.PI * 0.5,
        'SE': Math.PI * 0.25,
        'S': 0,
        'SW': -Math.PI * 0.25,
        'W': -Math.PI * 0.5,
        'NW': -Math.PI * 0.75
    };

    function directionToRotation(direction) {
        return DIRECTION_TO_ROTATION[direction] || 0;
    }

    // ==================== Export ====================
    window.Playground.Layout3D = {
        CITY,
        CITY_GRID,
        BUILDINGS,
        NATURE,
        WORK_POSITIONS,
        ENTRANCE,
        getRoads,
        getGroundTiles,
        generateWalkableMap,
        directionToRotation,
        DIRECTION_TO_ROTATION
    };

    console.log('[City3DLayout] Module loaded');

})();
