/**
 * Playground Layout - Kenney Isometric Miniature 기반
 * dungeon + library 에셋 조합으로 고풍스러운 스터디 룸 구현
 */
(function() {
    'use strict';

    window.Playground = window.Playground || {};

    // ==================== Room Dimensions ====================
    const ROOM = {
        WIDTH: 8,   // tiles (gx 방향)
        HEIGHT: 6,  // tiles (gy 방향)
    };

    // ==================== Floor Configuration ====================
    // 바닥 타일 타입 정의
    const FLOOR_MAP = {
        // 기본: 돌 바닥 (dungeon stone)
        default: 'stone',
        // 카펫 영역 (중앙)
        carpet: [
            { x: 3, y: 2 },
            { x: 4, y: 2 },
            { x: 3, y: 3 },
            { x: 4, y: 3 },
        ],
    };

    // ==================== Wall Configuration ====================
    // 벽 스타일: 'stone' (dungeon) 사용
    const WALLS = {
        style: 'stone',
        // 후면 벽 (gy=0, gx방향)
        back: [
            { gx: 1, type: 'straight', direction: 'S' },
            { gx: 2, type: 'window', direction: 'S' },
            { gx: 3, type: 'straight', direction: 'S' },
            { gx: 4, type: 'window', direction: 'S' },
            { gx: 5, type: 'straight', direction: 'S' },
            { gx: 6, type: 'window', direction: 'S' },
            { gx: 7, type: 'straight', direction: 'S' },
        ],
        // 좌측 벽 (gx=0, gy방향)
        left: [
            { gy: 0, type: 'corner', direction: 'S' },
            { gy: 1, type: 'window', direction: 'E' },
            { gy: 2, type: 'straight', direction: 'E' },
            { gy: 3, type: 'archway', direction: 'E' }, // 입구
            { gy: 4, type: 'straight', direction: 'E' },
            { gy: 5, type: 'straight', direction: 'E' },
        ],
    };

    // ==================== Furniture Definitions ====================
    // type: 가구 종류, asset: 에셋 키, gridX/Y: 그리드 위치
    const FURNITURE = [
        // === 후면 벽 책장 (gy=0 벽면) - 유지 ===
        { type: 'bookcase', asset: 'glass_S', gridX: 0.2, gridY: 0 },
        { type: 'bookcase', asset: 'glass_S', gridX: 0.75, gridY: 0 },
        { type: 'bookcase', asset: 'glass_S', gridX: 1.30, gridY: 0 },
        { type: 'bookcase', asset: 'wide_S', gridX: 3, gridY: 0 },
        { type: 'bookcase', asset: 'wide_S', gridX: 5, gridY: 0 },
        { type: 'bookcase', asset: 'booksLadder_S', gridX: 5.8, gridY: 0 },
        { type: 'bookcase', asset: 'booksLadder_S', gridX: 6.35, gridY: 0 },

        // === 좌측 벽 책장 (gx=0 벽면) - 유지 ===
        { type: 'bookcase', asset: 'half_E', gridX: 0, gridY: 1.5 },
        { type: 'bookcase', asset: 'glass_E', gridX: 0, gridY: 2.05 },

        // === 중앙 작업 공간 (밀집 배치) ===
        { type: 'table', asset: 'longDecoratedChairsBooks_S', gridX: 2.6, gridY: 2.5 },
        { type: 'table', asset: 'longDecoratedChairs_S', gridX: 3.3, gridY: 2.5 },
        { type: 'table', asset: 'longDecoratedChairsBooks_S', gridX: 4.0, gridY: 2.5 },
        { type: 'table', asset: 'longDecoratedChairs_S', gridX: 4.7, gridY: 2.5 },
        { type: 'table', asset: 'longDecoratedChairs_S', gridX: 2.6, gridY: 1.5 },
        { type: 'table', asset: 'longDecoratedChairsBooks_S', gridX: 3.3, gridY: 1.5 },
        { type: 'table', asset: 'longDecoratedChairs_S', gridX: 4.0, gridY: 1.5 },
        { type: 'table', asset: 'longDecoratedChairsBooks_S', gridX: 4.7, gridY: 1.5 },

        // === 회의실 구역 (좌측 벽면, gy=4~5) ===
        { type: 'table', asset: 'roundChairs_E', gridX: 0.7, gridY: 3.85 },
        { type: 'table', asset: 'roundChairs_E', gridX: 0.7, gridY: 4.85 },
        { type: 'table', asset: 'roundChairs_E', gridX: 1.7, gridY: 3.85 },
        { type: 'table', asset: 'roundChairs_E', gridX: 1.7, gridY: 4.85 },
        { type: 'chair', asset: 'library_E', gridX: 0, gridY: 5 },
        { type: 'chair', asset: 'library_E', gridX: 0, gridY: 5.25 },
        { type: 'decor', asset: 'displayCaseBooks_E', gridX: 3, gridY: 4.12 },
        { type: 'decor', asset: 'displayCaseBooks_E', gridX: 3, gridY: 4.90 },

        // === 우측 하단 책장 ===
        { type: 'bookcase', asset: 'wideDesk_E', gridX: 6, gridY: 3.7 },
        { type: 'bookcase', asset: 'wideDesk_E', gridX: 6, gridY: 4.7 },
    ];

    // ==================== Seat Positions ====================
    // 아바타가 앉을 수 있는 위치
    // facing: 'SE'=gx++, 'SW'=gy++, 'NW'=gx--, 'NE'=gy--
    const SEAT_POSITIONS = [
        // === 중앙 작업 공간 - 뒷줄 테이블 (gridY: 1.5) ===
        // 북쪽 의자 (테이블 위쪽, 남쪽을 바라봄)
        { gridX: 2.6, gridY: 1.2, seatId: 'work1', facing: 'SW' },
        { gridX: 3.3, gridY: 1.2, seatId: 'work2', facing: 'SW' },
        { gridX: 4.0, gridY: 1.2, seatId: 'work3', facing: 'SW' },
        { gridX: 4.7, gridY: 1.2, seatId: 'work4', facing: 'SW' },
        // 남쪽 의자 (테이블 아래쪽, 북쪽을 바라봄)
        { gridX: 2.6, gridY: 1.8, seatId: 'work5', facing: 'NE' },
        { gridX: 3.3, gridY: 1.8, seatId: 'work6', facing: 'NE' },
        { gridX: 4.0, gridY: 1.8, seatId: 'work7', facing: 'NE' },
        { gridX: 4.7, gridY: 1.8, seatId: 'work8', facing: 'NE' },

        // === 중앙 작업 공간 - 앞줄 테이블 (gridY: 2.5) ===
        // 북쪽 의자 (테이블 위쪽, 남쪽을 바라봄)
        { gridX: 2.6, gridY: 2.2, seatId: 'work9', facing: 'SW' },
        { gridX: 3.3, gridY: 2.2, seatId: 'work10', facing: 'SW' },
        { gridX: 4.0, gridY: 2.2, seatId: 'work11', facing: 'SW' },
        { gridX: 4.7, gridY: 2.2, seatId: 'work12', facing: 'SW' },
        // 남쪽 의자 (테이블 아래쪽, 북쪽을 바라봄)
        { gridX: 2.6, gridY: 2.8, seatId: 'work13', facing: 'NE' },
        { gridX: 3.3, gridY: 2.8, seatId: 'work14', facing: 'NE' },
        { gridX: 4.0, gridY: 2.8, seatId: 'work15', facing: 'NE' },
        { gridX: 4.7, gridY: 2.8, seatId: 'work16', facing: 'NE' },

        // === 회의실 좌석 - 원형 테이블 주변 ===
        // 테이블 (0.7, 3.85)
        { gridX: 0.7, gridY: 3.85, seatId: 'meet1', facing: 'SW' },
        // 테이블 (1.7, 3.85)
        { gridX: 1.7, gridY: 3.85, seatId: 'meet2', facing: 'SW' },
        // 테이블 (0.7, 4.85)
        { gridX: 0.7, gridY: 4.85, seatId: 'meet3', facing: 'SW' },
        // 테이블 (1.7, 4.85)
        { gridX: 1.7, gridY: 4.85, seatId: 'meet4', facing: 'SW' },
    ];

    // ==================== Idle Positions ====================
    // 대기 중인 아바타 위치
    const IDLE_POSITIONS = [
        { gridX: 2, gridY: 3, label: 'browsing' },
        { gridX: 5.5, gridY: 4.5, label: 'walking' },
        { gridX: 3, gridY: 5, label: 'entrance' },
    ];

    // ==================== Entrance Position ====================
    const ENTRANCE = { gridX: 4, gridY: 5 };

    // ==================== Walkability Map Generator ====================
    function generateWalkableMap() {
        const map = [];
        for (let y = 0; y < ROOM.HEIGHT; y++) {
            map[y] = [];
            for (let x = 0; x < ROOM.WIDTH; x++) {
                // 벽 영역(y=0, x=0)과 가구 영역 제외하고 이동 가능
                map[y][x] = (y >= 1 && x >= 1);
            }
        }

        // 가구 영역 차단
        for (const f of FURNITURE) {
            const gx = Math.floor(f.gridX);
            const gy = Math.floor(f.gridY);
            if (gx >= 0 && gx < ROOM.WIDTH && gy >= 0 && gy < ROOM.HEIGHT) {
                map[gy][gx] = false;
            }
        }

        return map;
    }

    // ==================== Export ====================
    window.Playground.Layout = {
        ROOM,
        FLOOR_MAP,
        WALLS,
        FURNITURE,
        SEAT_POSITIONS,
        IDLE_POSITIONS,
        ENTRANCE,
        generateWalkableMap,
    };

})();
