(function() {
    'use strict';

    // Constants for movement costs
    const CARDINAL_COST = 1.0;
    const DIAGONAL_COST = 1.414;

    // 8-directional movement offsets
    const DIRECTIONS = {
        N:  { dx: 0,  dy: -1, cost: CARDINAL_COST },
        E:  { dx: 1,  dy: 0,  cost: CARDINAL_COST },
        S:  { dx: 0,  dy: 1,  cost: CARDINAL_COST },
        W:  { dx: -1, dy: 0,  cost: CARDINAL_COST },
        NE: { dx: 1,  dy: -1, cost: DIAGONAL_COST, requires: ['N', 'E'] },
        SE: { dx: 1,  dy: 1,  cost: DIAGONAL_COST, requires: ['S', 'E'] },
        SW: { dx: -1, dy: 1,  cost: DIAGONAL_COST, requires: ['S', 'W'] },
        NW: { dx: -1, dy: -1, cost: DIAGONAL_COST, requires: ['N', 'W'] }
    };

    /**
     * Helper function to round a value to the nearest 0.5 for half-grid precision
     * @param {number} value - The value to round
     * @returns {number} The value rounded to nearest 0.5
     */
    function roundToGrid(value) {
        return Math.round(value * 2) / 2;
    }

    /**
     * Helper function to calculate Manhattan distance between two points
     * @param {number} x1 - Start X coordinate
     * @param {number} y1 - Start Y coordinate
     * @param {number} x2 - End X coordinate
     * @param {number} y2 - End Y coordinate
     * @returns {number} Manhattan distance
     */
    function manhattanDistance(x1, y1, x2, y2) {
        return Math.abs(x2 - x1) + Math.abs(y2 - y1);
    }

    /**
     * Octile heuristic for A* pathfinding
     * @param {number} dx - Absolute difference in X
     * @param {number} dy - Absolute difference in Y
     * @returns {number} Estimated cost to goal
     */
    function octileHeuristic(dx, dy) {
        const absDx = Math.abs(dx);
        const absDy = Math.abs(dy);
        return Math.max(absDx, absDy) + 0.414 * Math.min(absDx, absDy);
    }

    /**
     * Grid class representing a 2D walkable grid
     */
    class Grid {
        /**
         * Create a new grid
         * @param {number} width - Grid width
         * @param {number} height - Grid height
         * @param {Array<Array<number>>} [initialGrid] - Optional initial walkability grid (1=walkable, 0=blocked)
         */
        constructor(width, height, initialGrid = null) {
            this.width = width;
            this.height = height;
            this.walkable = [];

            // Initialize walkable array
            for (let y = 0; y < height; y++) {
                this.walkable[y] = [];
                for (let x = 0; x < width; x++) {
                    if (initialGrid && initialGrid[y] && initialGrid[y][x] !== undefined) {
                        // Use initial grid value (1 = walkable, 0 = blocked)
                        this.walkable[y][x] = initialGrid[y][x] === 1;
                    } else {
                        // Default to walkable if no initial grid
                        this.walkable[y][x] = true;
                    }
                }
            }
        }

        /**
         * Set whether a tile is walkable
         * @param {number} x - X coordinate
         * @param {number} y - Y coordinate
         * @param {boolean} value - Whether the tile is walkable
         */
        setWalkable(x, y, value) {
            if (this.isInBounds(x, y)) {
                this.walkable[y][x] = value;
            }
        }

        /**
         * Check if coordinates are within grid bounds
         * @param {number} x - X coordinate
         * @param {number} y - Y coordinate
         * @returns {boolean} True if within bounds
         */
        isInBounds(x, y) {
            return x >= 0 && x < this.width && y >= 0 && y < this.height;
        }

        /**
         * Check if a tile is walkable (also checks bounds)
         * @param {number} x - X coordinate
         * @param {number} y - Y coordinate
         * @returns {boolean} True if tile is walkable and within bounds
         */
        isWalkable(x, y) {
            if (!this.isInBounds(x, y)) {
                return false;
            }
            return this.walkable[y][x] === true;
        }

        /**
         * Get all walkable neighbors of a tile
         * @param {number} x - X coordinate
         * @param {number} y - Y coordinate
         * @returns {Array<{x: number, y: number, cost: number}>} Array of neighbor tiles with movement cost
         */
        getNeighbors(x, y) {
            const neighbors = [];

            // Check each direction
            for (const [dirName, dir] of Object.entries(DIRECTIONS)) {
                const nx = x + dir.dx;
                const ny = y + dir.dy;

                // Skip if neighbor is not walkable
                if (!this.isWalkable(nx, ny)) {
                    continue;
                }

                // For diagonal movement, check if both adjacent cardinal tiles are walkable
                if (dir.requires) {
                    const [req1, req2] = dir.requires;
                    const dir1 = DIRECTIONS[req1];
                    const dir2 = DIRECTIONS[req2];

                    const adj1Walkable = this.isWalkable(x + dir1.dx, y + dir1.dy);
                    const adj2Walkable = this.isWalkable(x + dir2.dx, y + dir2.dy);

                    // Diagonal movement only allowed if both adjacent cardinals are walkable
                    if (!adj1Walkable || !adj2Walkable) {
                        continue;
                    }
                }

                neighbors.push({
                    x: nx,
                    y: ny,
                    cost: dir.cost
                });
            }

            return neighbors;
        }
    }

    /**
     * A* Pathfinder class
     */
    class Pathfinder {
        /**
         * Create a new pathfinder
         * @param {Grid} grid - The grid to pathfind on
         */
        constructor(grid) {
            this.grid = grid;
        }

        /**
         * Create a unique key for a grid position
         * @param {number} x - X coordinate
         * @param {number} y - Y coordinate
         * @returns {string} Unique position key
         */
        positionKey(x, y) {
            return `${x},${y}`;
        }

        /**
         * Find a path from start to end using A* algorithm
         * @param {number} startX - Start X coordinate
         * @param {number} startY - Start Y coordinate
         * @param {number} endX - End X coordinate
         * @param {number} endY - End Y coordinate
         * @returns {Array<{x: number, y: number}>} Array of path nodes, or empty array if no path found
         */
        findPath(startX, startY, endX, endY) {
            // Store original float destination
            const floatEndX = endX;
            const floatEndY = endY;

            // Round to nearest integer for grid-based pathfinding
            const gridStartX = Math.round(startX);
            const gridStartY = Math.round(startY);
            const gridEndX = Math.round(endX);
            const gridEndY = Math.round(endY);

            // Check if start and end are valid
            if (!this.grid.isWalkable(gridStartX, gridStartY)) {
                return [];
            }

            if (!this.grid.isWalkable(gridEndX, gridEndY)) {
                return [];
            }

            // If start equals end, return just the destination
            if (gridStartX === gridEndX && gridStartY === gridEndY) {
                return [{ x: floatEndX, y: floatEndY }];
            }

            // Priority queue (sorted array for simplicity)
            // Each node: { x, y, g, f, parent }
            const openList = [];
            const closedSet = new Set();
            const gScores = new Map();
            const parents = new Map();

            const startKey = this.positionKey(gridStartX, gridStartY);
            gScores.set(startKey, 0);

            const startH = octileHeuristic(gridEndX - gridStartX, gridEndY - gridStartY);
            openList.push({
                x: gridStartX,
                y: gridStartY,
                g: 0,
                f: startH
            });

            while (openList.length > 0) {
                // Sort by f-score (lowest first)
                openList.sort((a, b) => a.f - b.f);

                // Get node with lowest f-score
                const current = openList.shift();
                const currentKey = this.positionKey(current.x, current.y);

                // Check if we reached the goal
                if (current.x === gridEndX && current.y === gridEndY) {
                    return this.reconstructPath(parents, current.x, current.y, floatEndX, floatEndY);
                }

                // Add to closed set
                closedSet.add(currentKey);

                // Explore neighbors
                const neighbors = this.grid.getNeighbors(current.x, current.y);

                for (const neighbor of neighbors) {
                    const neighborKey = this.positionKey(neighbor.x, neighbor.y);

                    // Skip if already visited
                    if (closedSet.has(neighborKey)) {
                        continue;
                    }

                    // Calculate tentative g-score
                    const tentativeG = current.g + neighbor.cost;

                    // Check if this path is better
                    const existingG = gScores.get(neighborKey);
                    if (existingG !== undefined && tentativeG >= existingG) {
                        continue;
                    }

                    // This path is better, record it
                    gScores.set(neighborKey, tentativeG);
                    parents.set(neighborKey, { x: current.x, y: current.y });

                    const h = octileHeuristic(gridEndX - neighbor.x, gridEndY - neighbor.y);
                    const f = tentativeG + h;

                    // Check if neighbor is already in open list
                    const existingIndex = openList.findIndex(n => n.x === neighbor.x && n.y === neighbor.y);
                    if (existingIndex !== -1) {
                        // Update existing node
                        openList[existingIndex].g = tentativeG;
                        openList[existingIndex].f = f;
                    } else {
                        // Add new node to open list
                        openList.push({
                            x: neighbor.x,
                            y: neighbor.y,
                            g: tentativeG,
                            f: f
                        });
                    }
                }
            }

            // No path found
            return [];
        }

        /**
         * Reconstruct the path from parents map
         * @param {Map} parents - Map of node keys to parent positions
         * @param {number} endX - End X coordinate (grid)
         * @param {number} endY - End Y coordinate (grid)
         * @param {number} floatEndX - Original float end X
         * @param {number} floatEndY - Original float end Y
         * @returns {Array<{x: number, y: number}>} Reconstructed path
         */
        reconstructPath(parents, endX, endY, floatEndX, floatEndY) {
            const path = [];
            let currentX = endX;
            let currentY = endY;
            let currentKey = this.positionKey(currentX, currentY);

            // Build path backwards
            const pathNodes = [];
            while (parents.has(currentKey)) {
                pathNodes.unshift({ x: currentX, y: currentY });
                const parent = parents.get(currentKey);
                currentX = parent.x;
                currentY = parent.y;
                currentKey = this.positionKey(currentX, currentY);
            }

            // Path includes all nodes except start (which is current position)
            // Replace the last node with the float destination
            if (pathNodes.length > 0) {
                pathNodes[pathNodes.length - 1] = { x: floatEndX, y: floatEndY };
            } else {
                pathNodes.push({ x: floatEndX, y: floatEndY });
            }

            return pathNodes;
        }

        /**
         * Find the nearest walkable tile using BFS
         * @param {number} x - Start X coordinate
         * @param {number} y - Start Y coordinate
         * @returns {{x: number, y: number}|null} Nearest walkable tile, or null if none found
         */
        findNearestWalkable(x, y) {
            const gridX = Math.round(x);
            const gridY = Math.round(y);

            // If current position is walkable, return it
            if (this.grid.isWalkable(gridX, gridY)) {
                return { x: gridX, y: gridY };
            }

            // BFS to find nearest walkable
            const visited = new Set();
            const queue = [{ x: gridX, y: gridY }];
            visited.add(this.positionKey(gridX, gridY));

            // All 8 directions for BFS
            const allDirections = [
                { dx: 0, dy: -1 },  // N
                { dx: 1, dy: 0 },   // E
                { dx: 0, dy: 1 },   // S
                { dx: -1, dy: 0 },  // W
                { dx: 1, dy: -1 },  // NE
                { dx: 1, dy: 1 },   // SE
                { dx: -1, dy: 1 },  // SW
                { dx: -1, dy: -1 }  // NW
            ];

            while (queue.length > 0) {
                const current = queue.shift();

                for (const dir of allDirections) {
                    const nx = current.x + dir.dx;
                    const ny = current.y + dir.dy;
                    const key = this.positionKey(nx, ny);

                    if (visited.has(key)) {
                        continue;
                    }

                    visited.add(key);

                    // Check bounds
                    if (!this.grid.isInBounds(nx, ny)) {
                        continue;
                    }

                    // If walkable, return it
                    if (this.grid.isWalkable(nx, ny)) {
                        return { x: nx, y: ny };
                    }

                    // Add to queue for further exploration
                    queue.push({ x: nx, y: ny });
                }
            }

            // No walkable tile found
            return null;
        }
    }

    // Ensure Playground namespace exists
    window.Playground = window.Playground || {};

    // Export to Playground namespace
    window.Playground.Pathfinding = {
        Grid,
        Pathfinder,
        roundToGrid,
        manhattanDistance
    };

})();
