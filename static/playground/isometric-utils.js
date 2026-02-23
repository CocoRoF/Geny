/**
 * Isometric Coordinate Utilities for Three.js
 * Kenney Isometric Miniature format (256x128 tiles)
 */
(function() {
    'use strict';

    // Tile dimensions (Kenney isometric miniature format)
    const TILE_W = 256;
    const TILE_H = 128;

    // Room dimensions in tiles
    const ROOM_WIDTH = 8;
    const ROOM_HEIGHT = 6;

    // World scale factor (can be adjusted for Three.js scene sizing)
    const WORLD_SCALE = 1;

    /**
     * Convert grid coordinates to screen (2D isometric) coordinates
     * @param {number} gx - Grid X position
     * @param {number} gy - Grid Y position
     * @returns {{x: number, y: number}} Screen coordinates
     */
    function gridToScreen(gx, gy) {
        return {
            x: (gx - gy) * (TILE_W / 2),
            y: (gx + gy) * (TILE_H / 2)
        };
    }

    /**
     * Convert screen (2D isometric) coordinates to grid coordinates
     * @param {number} sx - Screen X position
     * @param {number} sy - Screen Y position
     * @returns {{x: number, y: number}} Grid coordinates
     */
    function screenToGrid(sx, sy) {
        // Inverse of gridToScreen:
        // sx = (gx - gy) * (TILE_W / 2)  =>  gx - gy = sx / (TILE_W / 2)
        // sy = (gx + gy) * (TILE_H / 2)  =>  gx + gy = sy / (TILE_H / 2)
        // Adding: 2*gx = sx/(TILE_W/2) + sy/(TILE_H/2)
        // Subtracting: 2*gy = sy/(TILE_H/2) - sx/(TILE_W/2)
        const gx = (sx / (TILE_W / 2) + sy / (TILE_H / 2)) / 2;
        const gy = (sy / (TILE_H / 2) - sx / (TILE_W / 2)) / 2;
        return { x: gx, y: gy };
    }

    /**
     * Convert grid coordinates to Three.js world coordinates
     * In Three.js: X is right, Y is up, Z is towards camera
     * @param {number} gx - Grid X position
     * @param {number} gy - Grid Y position
     * @returns {{x: number, y: number, z: number}} World coordinates
     */
    function gridToWorld(gx, gy) {
        return {
            x: (gx - gy) * 0.5 * WORLD_SCALE,
            y: 0, // Ground level
            z: (gx + gy) * 0.25 * WORLD_SCALE
        };
    }

    /**
     * Calculate depth key for sprite sorting (painter's algorithm)
     * Higher values should be rendered later (in front)
     * @param {number} gx - Grid X position
     * @param {number} gy - Grid Y position
     * @param {number} [layer=0] - Layer offset for objects at same position
     * @returns {number} Depth key for sorting
     */
    function depthKey(gx, gy, layer = 0) {
        return (gx + gy) * 100 + layer;
    }

    /**
     * Calculate direction string based on grid movement delta
     * @param {number} dx - Delta X (movement in grid X direction)
     * @param {number} dy - Delta Y (movement in grid Y direction)
     * @returns {string} Direction: 'N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'
     */
    function calculateDirection(dx, dy) {
        // Normalize to unit direction
        const len = Math.sqrt(dx * dx + dy * dy);
        if (len === 0) return 'S'; // Default direction when stationary

        const nx = dx / len;
        const ny = dy / len;

        // Calculate angle in radians, then convert to 8 directions
        // atan2 returns angle from -PI to PI, with 0 pointing right (+X)
        const angle = Math.atan2(ny, nx);
        
        // Convert to degrees and normalize to 0-360
        let degrees = angle * (180 / Math.PI);
        if (degrees < 0) degrees += 360;

        // Map to 8 directions (each direction covers 45 degrees)
        // In isometric grid: +X is SE, +Y is SW, -X is NW, -Y is NE
        if (degrees >= 337.5 || degrees < 22.5) return 'SE';   // +X direction
        if (degrees >= 22.5 && degrees < 67.5) return 'S';     // +X +Y
        if (degrees >= 67.5 && degrees < 112.5) return 'SW';   // +Y direction
        if (degrees >= 112.5 && degrees < 157.5) return 'W';   // -X +Y
        if (degrees >= 157.5 && degrees < 202.5) return 'NW';  // -X direction
        if (degrees >= 202.5 && degrees < 247.5) return 'N';   // -X -Y
        if (degrees >= 247.5 && degrees < 292.5) return 'NE';  // -Y direction
        if (degrees >= 292.5 && degrees < 337.5) return 'E';   // +X -Y

        return 'S'; // Fallback
    }

    // Export to global scope
    window.IsometricUtils = {
        // Constants
        TILE_W: TILE_W,
        TILE_H: TILE_H,
        ROOM_WIDTH: ROOM_WIDTH,
        ROOM_HEIGHT: ROOM_HEIGHT,
        WORLD_SCALE: WORLD_SCALE,

        // Functions
        gridToScreen: gridToScreen,
        screenToGrid: screenToGrid,
        gridToWorld: gridToWorld,
        depthKey: depthKey,
        calculateDirection: calculateDirection
    };

})();
