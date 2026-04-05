# Obsidian Knowledge Graph — 심층 분석 및 고도화 계획서

> **작성 목적**: Geny Opsidian 시스템 내 Knowledge Graph 시각화를 심층 분석하고, `github-ai-network` 라이브러리의 설계 패턴을 참조하여 구체적인 개선 로드맵을 수립한다.

---

## 0. 범위 정의: Workflow Graph ≠ Knowledge Graph

Geny에는 **완전히 별개의 두 가지 그래프 시스템**이 존재한다. 본 보고서는 **Knowledge Graph만**을 다룬다.

### Workflow Graph (본 보고서 범위 밖)

LangGraph 기반 에이전트 워크플로우를 시각화하는 시스템이다. Start → Classify → Review → Answer 등의 **실행 흐름 노드**를 ReactFlow로 렌더링한다.

| 파일 | 역할 |
|------|------|
| `components/workflow/WorkflowCanvas.tsx` | ReactFlow 기반 워크플로우 캔버스 렌더러 |
| `components/workflow/CustomNodes.tsx` | 워크플로우 노드 타입 (StartNode, EndNode 등) |
| `components/workflow/PropertyPanel.tsx` | 선택 노드의 속성 편집 패널 |
| `components/workflow/NodePalette.tsx` | 드래그 앤 드롭 노드 팔레트 |
| `components/tabs/GraphTab.tsx` | "그래프" 탭 — 현재 세션의 워크플로우를 읽기 전용으로 표시 |
| `components/tabs/WorkflowTab.tsx` | "워크플로우" 탭 — 워크플로우 편집기 |
| `store/useWorkflowStore.ts` | 워크플로우 노드/엣지 상태 관리 |

> **이 시스템은 에이전트의 실행 로직 흐름을 편집/조회하는 것이다. 노트 간 지식 연결과는 아무 관계가 없다.**

### Knowledge Graph (본 보고서 범위)

Opsidian 시스템 내 **노트들의 연결 관계**를 시각화하는 그래프이다. `[[wikilink]]`와 태그로 연결된 **지식 노드**를 보여준다. `OpsidianHub`의 세 가지 모드(user, curator, sessions)에 각각 존재한다.

| OpsidianHub 모드 | 뷰 컴포넌트 | 그래프 컴포넌트 | 위치 |
|-------------------|------------|-----------------|------|
| `sessions` | `ObsidianView.tsx` | `GraphView.tsx` (독립 파일) | `components/obsidian/` |
| `user` | `UserOpsidianView.tsx` | `GraphViewer` (인라인 함수, ~L896) | `components/user-opsidian/` |
| `curator` | `CuratedKnowledgeView.tsx` | `CuratedGraphViewer` (인라인 함수, ~L908) | `components/curated-knowledge/` |

---

## 1. 현재 Knowledge Graph 구현 분석

### 1.1 세 가지 Knowledge Graph의 차이

동일한 OpsidianHub 안에 있으면서 **각각 완전히 다른 렌더링 방식**을 사용하고 있다.

| 항목 | Sessions (`GraphView.tsx`) | User Opsidian (`GraphViewer`) | Curated (`CuratedGraphViewer`) |
|------|---------------------------|-------------------------------|--------------------------------|
| **렌더링 엔진** | ReactFlow (`@xyflow/react`) | Raw SVG | Raw SVG |
| **레이아웃** | 커스텀 Force (120회 반복) | 카테고리별 원형 클러스터 (정적) | 카테고리별 원형 클러스터 (정적) |
| **캔버스 크기** | 반응형 (부모 100%) | **800×600 고정** | **800×600 고정** |
| **Zoom/Pan** | ✅ (ReactFlow 내장) | ❌ | ❌ |
| **노드 드래그** | ✅ | ❌ | ❌ |
| **MiniMap** | ✅ | ❌ | ❌ |
| **호버 툴팁** | 제목만 | ❌ | ❌ |
| **노드 크기** | 중요도별 (40~80px) | **모두 동일** (r=8) | **모두 동일** (r=8) |
| **노드 레이블** | 원 안에 overflow:hidden → 읽기 불가 | 20자 잘림 | 20자 잘림 |
| **엣지 색상** | `var(--text-muted)` 회색 | `var(--obs-purple)` 보라 | `var(--obs-purple)` 보라 |
| **엣지 두께/투명도** | 1px / 0.4 | 1px / **0.3** | 1px / **0.3** |
| **화살표** | ArrowClosed 12×12 | ❌ | ❌ |
| **코드 위치** | 독립 파일 (~230줄) | 인라인 함수 (~80줄) | 인라인 함수 (~80줄) |

### 1.2 데이터 흐름

세 컨텍스트 모두 동일한 패턴의 데이터 흐름을 사용한다:

```
컴포넌트 mount → API call (getGraph) → store.setGraphData(nodes, edges) → 렌더링
```

| 컨텍스트 | API 엔드포인트 | 스토어 |
|----------|---------------|--------|
| Sessions | `GET /api/agents/{sid}/memory/graph` | `useObsidianStore` |
| User | `GET /api/opsidian/graph` | `useUserOpsidianStore` |
| Curator | `GET /api/curated/graph` | `useCuratedKnowledgeStore` |

### 1.3 데이터 모델

**노드 (`MemoryGraphNode`)**:
```typescript
interface MemoryGraphNode {
  id: string;          // 파일 경로 (e.g. "topics/python-async.md")
  label: string;       // frontmatter title || 파일명
  category: string;    // daily | topics | entities | projects | insights | root
  importance: string;  // critical | high | medium | low
}
```

**엣지 (`MemoryGraphEdge`)**:
```typescript
interface MemoryGraphEdge {
  source: string;      // 소스 파일 경로
  target: string;      // 타겟 파일 경로
}
```

> **문제**: 엣지에 `type`, `weight`, `label` 같은 메타데이터가 전혀 없다. 모든 연결이 동일하게 보인다.

---

## 2. 문제점 상세 분석

### 2.1 렌더링 엔진 분열 (Critical)

동일한 OpsidianHub 안에서 3개의 탭(sessions/user/curator)이 완전히 다른 렌더링 방식을 사용한다. 이는 유지보수를 어렵게 하고, user/curator 뷰에서 극도로 낮은 시각화 품질을 야기한다.

**User Opsidian / Curated Knowledge의 인라인 SVG 구현**:
```typescript
// 800×600 고정 캔버스에 카테고리별 원형 배치
const width = 800;
const height = 600;

// 엣지 — opacity 0.3, 1px, 사실상 보이지 않음
<line x1={from.x} y1={from.y} x2={to.x} y2={to.y}
  stroke="var(--obs-purple)" strokeWidth={1} opacity={0.3} />

// 노드 — 모두 동일 크기 r=8, 레이블 20자 잘림
<circle cx={pos.x} cy={pos.y} r={8} fill={color} opacity={0.8} />
<text x={pos.x} y={pos.y + 20} textAnchor="middle" fontSize={10}>
  {n.label.length > 20 ? n.label.slice(0, 20) + '…' : n.label}
</text>
```

### 2.2 레이아웃 알고리즘 문제

#### Sessions (GraphView.tsx) — 커스텀 Force Layout
```javascript
// O(n²) 복잡도, Main Thread 동기 실행, 120회 고정 반복
for (let iter = 0; iter < 120; iter++) {
  for (let i = 0; i < len; i++) {
    for (let j = i + 1; j < len; j++) {
      // 반발력 계산
    }
  }
}
```

| 문제 | 설명 |
|------|------|
| O(n²) 복잡도 | 50노드 → 120 × 1,225 = 147,000 연산 |
| Main Thread 차단 | 노드 많으면 UI freeze |
| 수렴 검사 없음 | 이미 안정되어도 120회 전부 실행 |
| 애니메이션 없음 | 사전 계산 후 정적 렌더링 |
| 감쇠 결함 | `damping = 0.8 - iter * 0.004` — 설계상 200회 이후 음수 가능 |

#### User / Curator — 정적 원형 클러스터
```javascript
// 카테고리별 원에 배치 — 엣지 관계를 전혀 반영하지 않음
catGroups[cat].forEach((id, ni) => {
  positions[id] = {
    x: cx + Math.cos(subAngle) * (40 + catGroups[cat].length * 8),
    y: cy + Math.sin(subAngle) * (40 + catGroups[cat].length * 8),
  };
});
```

| 문제 | 설명 |
|------|------|
| Force simulation 부재 | 엣지 기반 인력 없음 — 연결된 노드가 멀리 배치될 수 있음 |
| 노드 겹침 | 같은 카테고리 노드가 많으면 서브원 반지름 부족 |
| 고정 캔버스 | 800×600px, 반응형 대응 불가 |
| Zoom/Pan 불가 | 노드가 빽빽해져도 확대 불가 |

### 2.3 노드 가독성 문제

| 컨텍스트 | 처리 방식 | 문제 |
|-----------|----------|------|
| Sessions | 원형 div 안에 전체 텍스트, `overflow: hidden`, font 8~13px | 40~80px 원 안에서 잘려 거의 읽을 수 없음 |
| User / Curator | `label.slice(0, 20) + '…'`, font 10px | 20자 잘림, 맥락 부족 |
| 모두 | `info.title \|\| filename` 폴백 | 제목 없으면 `"topics/python-async.md"` 같은 원시 경로 표시 |

### 2.4 엣지 가시성 문제

| 항목 | Sessions (ReactFlow) | User / Curator (SVG) |
|------|---------------------|----------------------|
| 색상 | `var(--text-muted)` 흐린 회색 | `var(--obs-purple)` |
| 두께 | 1px | 1px |
| 투명도 | 0.4 | **0.3** |
| 시각적 결과 | 흐리지만 인지 가능 | **사실상 보이지 않음** |
| 화살표 | 있음 | 없음 |
| 타입 구분 | 없음 | 없음 |

### 2.5 백엔드 링크 해석 문제

#### Wikilink 추출 (frontmatter.py)
```python
_WIKILINK_RE = re.compile(r"\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]")
```
- `[[target]]`, `[[target|alias]]` 지원
- 본문에서만 추출 (frontmatter의 links_to와 별개)

#### 링크 해석 (`_resolve_link` in index.py)
```python
def _resolve_link(self, link_target, idx):
    slug = link_target.lower().strip()
    # 1단계: 정확한 stem 매칭
    for filename in idx.files:
        stem = Path(filename).stem.lower()
        if stem == slug: return filename
    # 2단계: 부분 매칭 (문제의 원인)
    for filename in idx.files:
        stem = Path(filename).stem.lower()
        if slug in stem: return filename
    return None
```

| 문제 | 설명 |
|------|------|
| 부분 매칭 오류 | `[[python]]`이 `python-async.md` 매칭 → 의도하지 않은 엣지 |
| 순서 의존 | dict 순회 순서에 따라 매칭 결과 변동 |
| 태그 기반 연결 없음 | 동일 태그를 공유하는 노트 간 연결 미생성 |

#### 그래프 데이터 생성 (user_opsidian.py / curated_knowledge.py)
```python
def get_graph(self):
    for fn, info in files_map.items():
        nodes.append({
            "id": fn, "label": info.get("title", fn),
            "category": info.get("category", "root"),
            "importance": info.get("importance", "medium"),
        })
        for target in info.get("links_to", []):
            if target in files_map:
                edges.append({"source": fn, "target": target})
```

| 문제 | 설명 |
|------|------|
| 엣지 메타데이터 없음 | type, weight, label 필드 미존재 |
| 노드 메타데이터 부족 | tags, connectionCount, summary 미전달 |
| 태그 기반 엣지 미생성 | wikilink만으로 엣지 구성 |
| Session의 `get_memory_graph()`는 타겟 필터링 없음 | dangling edge 가능 |

### 2.6 누락된 기능 종합

| 기능 | Obsidian | github-ai-network | Geny Sessions | Geny User/Curator |
|------|----------|-------------------|---------------|-------------------|
| Real-time Force Sim | ✅ | ✅ (d3-force-3d) | ❌ (정적 사전계산) | ❌ (없음) |
| Zoom + Pan | ✅ | ✅ | ✅ (ReactFlow) | ❌ |
| 노드 드래그 | ✅ | ✅ | ✅ | ❌ |
| 노드 검색/필터 | ✅ | ✅ | ❌ | ❌ |
| Hover 프리뷰 | ✅ | ✅ (상세 모달) | 제목만 | ❌ |
| N-hop 하이라이트 | ✅ | ✅ (3-hop BFS) | ❌ | ❌ |
| 태그 기반 엣지 | Dataview | ✅ (has_topic) | ❌ | ❌ |
| 엣지 타입 구분 | ❌ | ✅ (5가지 색상) | ❌ | ❌ |
| 반응형 캔버스 | ✅ | ✅ | ✅ | ❌ (800×600 고정) |
| MiniMap | ✅ | ❌ | ✅ | ❌ |
| 고아 노드 표시 | ✅ | N/A | ❌ | ❌ |
| 노드 크기 차별화 | ✅ | ✅ (val 기반) | ✅ (importance) | ❌ (모두 r=8) |

---

## 3. github-ai-network 참조 분석

### 3.1 아키텍처 핵심

```
┌─ 2 Draw Calls ──────────────────────────────────────┐
│  InstancedMesh (모든 노드 → 1 draw call)             │
│  LineSegments  (모든 엣지 → 1 draw call)             │
│  ← Web Worker (d3-force-3d) → Transferable Buffer    │
└──────────────────────────────────────────────────────┘
```

- **Three.js + InstancedMesh**: 단 1개 draw call로 모든 노드 렌더링
- **Web Worker**: Force simulation이 메인 스레드 차단 없음
- **적응형 파라미터**: 노드 수에 따라 force 강도, geometry 디테일 자동 조절

### 3.2 Geny Knowledge Graph에 적용할 패턴

Geny는 노트 시스템(수십~수백 노드)이므로 대규모 최적화(50,000+)는 불필요. **핵심만 차용**:

| github-ai-network 패턴 | Knowledge Graph 적용 방법 |
|-------------------------|--------------------------|
| **N-hop Highlight (BFS)** | 노드 클릭 시 1~3 hop 이웃을 밝기 차등 하이라이트 |
| **엣지 타입별 색상** | wikilink / tag-shared / backlink를 색상으로 구분 |
| **적응형 레이블** | 줌 레벨 + 노드 중요도에 따라 레이블 표시/숨김 |
| **Hover 상세 정보** | 노드 호버 시 제목, 카테고리, 태그, 연결 수, 요약 표시 |
| **검색+필터** | 카테고리, 태그, 중요도 기반 필터링 |
| **Force layout 개선** | d3-force 라이브러리 채택 (Barnes-Hut O(n log n)) |

### 3.3 Geny에 불필요한 것

| 기능 | 제외 이유 |
|------|-----------|
| Three.js 3D | 2D 노트 그래프에 과도함 |
| Custom GLSL 셰이더 | Obsidian 스타일과 부조화 |
| 별 배경 / Bloom | 지식 관리 UX와 무관 |
| InstancedMesh | 수백 노드 규모에서 불필요 |
| 항공기 모드 (W/A/S/D) | 2D에 해당 없음 |

---

## 4. 통합 그래프 엔진 설계

### 4.1 설계 원칙

1. **하나의 엔진**: OpsidianHub의 3개 모드(sessions/user/curator) 모두 동일한 컴포넌트 사용
2. **ReactFlow 유지**: 이미 sessions에서 사용 중이고, 검증된 2D 그래프 라이브러리
3. **d3-force 레이아웃**: Obsidian과 동일한 기반, O(n log n) Barnes-Hut 근사
4. **점진적 교체**: 기존 기능을 깨지 않으면서 단계별 교체

### 4.2 컴포넌트 구조

```
components/knowledge-graph/          ← Workflow 그래프의 components/workflow/와 명확히 분리
├── UnifiedGraphView.tsx             ← 통합 Knowledge Graph 뷰
├── GraphControls.tsx                ← 필터, 검색, 레이아웃 컨트롤
├── GraphLegend.tsx                  ← 범례 (카테고리 색상 + 엣지 타입)
├── GraphTooltip.tsx                 ← 호버 시 노드 상세 정보
├── graphLayout.ts                   ← d3-force 기반 레이아웃 유틸리티
├── graphHighlight.ts                ← N-hop BFS 하이라이트 로직
├── graphTypes.ts                    ← 확장된 타입 정의
└── graphConstants.ts                ← 색상, 크기, 스타일 상수
```

> **`components/knowledge-graph/`** 디렉토리는 `components/workflow/`와 완전히 분리된다. 파일도, 스토어도, API도, 데이터 모델도 공유하지 않는다.

### 4.3 확장된 데이터 모델

```typescript
// graphTypes.ts

type EdgeType = 'wikilink' | 'tag' | 'backlink';

interface EnhancedGraphNode {
  id: string;
  label: string;
  category: string;
  importance: string;
  tags: string[];
  connectionCount: number;    // 연결 수 → 노드 크기에 반영
  summary?: string;           // 첫 200자 요약 → 호버 프리뷰
  charCount: number;          // 문서 길이
}

interface EnhancedGraphEdge {
  source: string;
  target: string;
  type: EdgeType;             // 연결 유형 → 색상/스타일 결정
  weight: number;             // 연결 강도 (1.0=wikilink, 0.5=tag)
  label?: string;             // tag 이름 등
}

interface GraphFilterState {
  categories: Set<string>;
  importance: Set<string>;
  searchQuery: string;
  showOrphans: boolean;
  edgeTypes: Set<EdgeType>;
  selectedNodeId?: string;     // N-hop 하이라이트 기준
  highlightDepth: number;      // 1~3
}
```

### 4.4 백엔드 확장

현재 백엔드는 wikilink 엣지만 생성한다. **태그 기반 엣지와 노드 메타데이터를 확장**해야 한다:

```python
# 확장된 get_graph() — user_opsidian.py, curated_knowledge.py, manager.py 모두 적용
def get_graph(self) -> Dict[str, Any]:
    idx = self.get_index()
    files_map = idx.get("files", {})

    nodes = []
    edges = []
    edge_set = set()
    tag_to_files: Dict[str, List[str]] = {}

    for fn, info in files_map.items():
        links_to = info.get("links_to", [])
        linked_from = info.get("linked_from", [])

        nodes.append({
            "id": fn,
            "label": info.get("title", fn),
            "category": info.get("category", "root"),
            "importance": info.get("importance", "medium"),
            "tags": info.get("tags", []),
            "connectionCount": len(links_to) + len(linked_from),
            "summary": info.get("summary", ""),
            "charCount": info.get("char_count", 0),
        })

        # Wikilink 엣지
        for target in links_to:
            if target in files_map:
                key = (fn, target)
                if key not in edge_set:
                    edge_set.add(key)
                    edges.append({
                        "source": fn, "target": target,
                        "type": "wikilink", "weight": 1.0,
                    })

        # 태그 맵 구축
        for tag in info.get("tags", []):
            tag_to_files.setdefault(tag, []).append(fn)

    # 태그 기반 엣지
    for tag, fns in tag_to_files.items():
        if len(fns) < 2:
            continue
        for i in range(len(fns)):
            for j in range(i + 1, len(fns)):
                a, b = fns[i], fns[j]
                if (a, b) not in edge_set and (b, a) not in edge_set:
                    edge_set.add((a, b))
                    edges.append({
                        "source": a, "target": b,
                        "type": "tag", "weight": 0.5, "label": tag,
                    })

    return {"nodes": nodes, "edges": edges}
```

### 4.5 링크 해석 개선 (`_resolve_link`)

```python
def _resolve_link(self, link_target: str, idx: MemoryIndex) -> Optional[str]:
    slug = link_target.lower().strip()

    # 1. 정확한 경로 매칭 (e.g. "topics/python-async")
    for filename in idx.files:
        if filename.rsplit(".", 1)[0].lower() == slug:
            return filename

    # 2. 정확한 stem 매칭
    for filename in idx.files:
        if Path(filename).stem.lower() == slug:
            return filename

    # 3. 엄격한 부분 매칭: slug ≥ 3자이고 stem의 50% 이상 차지, 유일할 때만
    if len(slug) >= 3:
        candidates = []
        for filename in idx.files:
            stem = Path(filename).stem.lower()
            if slug in stem and len(slug) / len(stem) >= 0.5:
                candidates.append(filename)
        if len(candidates) == 1:
            return candidates[0]

    return None
```

---

## 5. 통합 그래프 뷰 상세 설계

### 5.1 커스텀 노드 디자인

현재 Sessions의 노드는 텍스트가 원 안에 잘리고, User/Curator는 r=8 동일 크기다. 개선 방향:

```
디자인:
  ┌───┐
  │ ● │ ← 카테고리 색상 원 (크기: 중요도 + 연결 수 기반)
  └───┘
  title  ← 원 아래 작은 텍스트 레이블 (배경 blur)
```

**노드 크기**:
```typescript
const BASE_SIZE = { critical: 28, high: 22, medium: 16, low: 12 };
const finalSize = BASE_SIZE[importance] + Math.log2(1 + connectionCount) * 3;
```

**레이블 표시 규칙** (줌 레벨 기반):
- zoom > 0.6: 모든 레이블 표시
- zoom 0.3~0.6: high 이상만 표시
- zoom < 0.3: critical만 표시
- 선택된 노드 + N-hop 이웃: 항상 표시

### 5.2 커스텀 엣지 스타일

```typescript
const EDGE_STYLES: Record<EdgeType, { color: string; width: number; dash?: string }> = {
  wikilink: { color: '#58a6ff', width: 2 },               // 파란색 실선
  backlink: { color: '#8b949e', width: 1.5 },              // 회색 실선
  tag:      { color: '#d29922', width: 1, dash: '4 2' },   // 주황 점선
};
```

### 5.3 N-hop 하이라이트

```typescript
function getHighlightSet(
  selectedId: string,
  edges: EnhancedGraphEdge[],
  maxDepth: number = 2
): Map<string, number> {  // nodeId → hop distance
  const result = new Map<string, number>();
  result.set(selectedId, 0);

  let frontier = new Set([selectedId]);
  for (let depth = 1; depth <= maxDepth; depth++) {
    const next = new Set<string>();
    for (const nodeId of frontier) {
      for (const edge of edges) {
        const neighbor = edge.source === nodeId ? edge.target
                       : edge.target === nodeId ? edge.source
                       : null;
        if (neighbor && !result.has(neighbor)) {
          result.set(neighbor, depth);
          next.add(neighbor);
        }
      }
    }
    frontier = next;
  }
  return result;
}
```

| Hop | 노드 | 엣지 |
|-----|------|------|
| 0 (선택) | 선택 링 + glow shadow | — |
| 1 | opacity 1.0 | strokeWidth ×2, opacity 0.8 |
| 2 | opacity 0.8 | strokeWidth ×1.2, opacity 0.5 |
| 미포함 | opacity 0.15 | opacity 0.05 |

### 5.4 Force Layout (d3-force)

```typescript
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from 'd3-force';

function computeLayout(nodes: EnhancedGraphNode[], edges: EnhancedGraphEdge[]) {
  const sim = forceSimulation(nodes)
    .force('charge', forceManyBody()
      .strength(d => -150 - d.connectionCount * 10)
      .distanceMax(500))
    .force('link', forceLink(edges)
      .id(d => d.id)
      .distance(d => d.type === 'wikilink' ? 100 : 200)
      .strength(d => d.weight || 0.5))
    .force('center', forceCenter())
    .force('collide', forceCollide()
      .radius(d => BASE_SIZE[d.importance] / 2 + 10)
      .strength(0.7))
    .alphaDecay(0.02)
    .velocityDecay(0.4);

  sim.tick(300);
  return nodes.map(n => ({ id: n.id, x: n.x, y: n.y }));
}
```

**d3-force 선택 이유**:
- Obsidian 자체가 d3-force 기반
- `forceLink().distance(fn)` — 엣지 타입별 거리
- `forceCollide()` — 노드 겹침 방지
- Barnes-Hut 근사 O(n log n) vs 현재 O(n²)

### 5.5 호버 툴팁

```
┌────────────────────────────────────┐
│ 📄 Python 비동기 프로그래밍         │
│ ────────────────────────────────── │
│ 카테고리: Topics  ●                │
│ 중요도: ★★★☆ High                  │
│ 태그: python, async, concurrency   │
│ 연결: 5개 (→3 ←2)                  │
│ ────────────────────────────────── │
│ asyncio를 활용한 비동기 패턴을 정리 │
│ 하고 실무에서 자주 사용하는 패턴... │
└────────────────────────────────────┘
```

### 5.6 필터 컨트롤

```
─── GraphControls ─────────────────────────
🔍 [노드 검색...]

카테고리: ☑ Daily ☑ Topics ☑ Entities ☑ Projects ☑ Insights ☐ Root
중요도:   ☑ Critical ☑ High ☑ Medium ☐ Low
엣지:     ☑ Wikilink ☑ Tag
☐ 고아 노드 숨김  │  깊이: [2 ▾]
────────────────────────────────────────────
```

---

## 6. 구현 단계

### Phase 1: 통합 Knowledge Graph 엔진

**목표**: 3개의 서로 다른 그래프를 하나의 고품질 `UnifiedGraphView`로 통합

| 작업 | 파일 | 설명 |
|------|------|------|
| 1-1 | `knowledge-graph/graphTypes.ts` | Enhanced 타입 정의 |
| 1-2 | `knowledge-graph/graphConstants.ts` | 색상, 크기, 엣지 스타일 상수 |
| 1-3 | `knowledge-graph/graphLayout.ts` | d3-force 레이아웃 유틸리티 |
| 1-4 | `knowledge-graph/UnifiedGraphView.tsx` | ReactFlow 기반 통합 뷰 |
| 1-5 | `UserOpsidianView.tsx` | 인라인 `GraphViewer` 제거 → `UnifiedGraphView` 사용 |
| 1-6 | `CuratedKnowledgeView.tsx` | 인라인 `CuratedGraphViewer` 제거 → `UnifiedGraphView` 사용 |
| 1-7 | `ObsidianView.tsx` | `GraphView.tsx` 대신 `UnifiedGraphView` 사용 |

**변경 범위**: 새 파일 4개 + 기존 파일 3개 수정

### Phase 2: 백엔드 데이터 확장

**목표**: 태그 기반 엣지 + 엣지 타입 + 노드 메타데이터 확장

| 작업 | 파일 | 설명 |
|------|------|------|
| 2-1 | `user_opsidian.py` | `get_graph()` 확장 |
| 2-2 | `curated_knowledge.py` | 동일 |
| 2-3 | `manager.py` | `get_memory_graph()` 확장 |
| 2-4 | `index.py` | `_resolve_link` 부분 매칭 수정 |
| 2-5 | `types/index.ts` | 프론트엔드 타입 확장 |

### Phase 3: 인터랙션 강화

**목표**: N-hop 하이라이트, 호버 프리뷰, 검색/필터

| 작업 | 파일 | 설명 |
|------|------|------|
| 3-1 | `knowledge-graph/graphHighlight.ts` | BFS N-hop 하이라이트 로직 |
| 3-2 | `knowledge-graph/GraphTooltip.tsx` | 호버 상세정보 오버레이 |
| 3-3 | `knowledge-graph/GraphControls.tsx` | 필터 + 검색 UI |
| 3-4 | `knowledge-graph/GraphLegend.tsx` | 범례 |
| 3-5 | CSS 업데이트 | Knowledge Graph 전용 스타일 |

### Phase 4: 폴리싱

| 작업 | 설명 |
|------|------|
| 4-1 | 노드 크기 연결 수 + 문서 크기 가변화 |
| 4-2 | 고아 노드 표시/숨김 토글 |
| 4-3 | 반응형 캔버스 (ResizeObserver) |
| 4-4 | 키보드 단축키 (Escape, /, Home) |

---

## 7. 의존성 변경

```json
{
  "d3-force": "^3.0.0",
  "@types/d3-force": "^3.0.0"
}
```

> ReactFlow(`@xyflow/react`)는 이미 설치되어 있으므로 그대로 사용.
> d3-force는 d3 생태계의 일부로 번들 증가 최소.

---

## 8. 성능 고려사항

### 예상 노드 규모

| 컨텍스트 | 예상 노드 | 예상 엣지 |
|-----------|----------|----------|
| Sessions | 10~50 | 5~30 |
| User Opsidian | 20~200 | 10~100 |
| Curated Knowledge | 50~500 | 30~300 |

### 최적화 전략

| 노드 수 | 전략 |
|---------|------|
| < 100 | d3-force 동기 300 tick, 모든 레이블, 모든 효과 |
| 100~500 | d3-force 동기 200 tick, 줌 기반 레이블, N-hop 활성 |
| > 500 | requestAnimationFrame 비동기, 레이블 Top-50, 태그 엣지 비활성 |

---

## 9. 마이그레이션 전략

### 안전한 교체 순서

1. `components/knowledge-graph/` 디렉토리에 새 컴포넌트 작성 (기존 코드 미수정)
2. **User Opsidian 먼저 교체** — 가장 자주 사용하는 뷰
3. **Curated Knowledge 교체** — User Opsidian과 동일 구조
4. **Sessions 마지막 교체** — 기존 GraphView.tsx 기능을 포함했는지 확인 후
5. 레거시 코드 제거 (인라인 `GraphViewer`, `CuratedGraphViewer`, 구 `GraphView.tsx`)

### 롤백

- 각 Phase 독립 배포 가능
- 기존 컴포넌트 즉시 삭제 아닌 import만 교체 → 빠른 롤백

---

## 10. 요약

### 현재 상태

| 항목 | 평가 |
|------|------|
| Workflow ↔ Knowledge 분리 | ✅ 물리적으로 별개 시스템 (코드, 스토어, API 모두 분리) |
| Knowledge Graph 렌더링 일관성 | ❌ 3개 모드가 서로 다른 엔진 (ReactFlow vs SVG ×2) |
| 레이아웃 품질 | ❌ Sessions만 force layout, User/Curator는 정적 배치 |
| 엣지 가시성 | ❌ 모든 뷰에서 엣지 희미 (User/Curator에서는 사실상 안 보임) |
| 노드 가독성 | ❌ 원 안 텍스트 잘림 또는 20자 제한 |
| 인터랙션 | ❌ User/Curator는 click만 가능 |
| 데이터 풍부도 | ❌ 엣지 타입 없음, 태그 기반 연결 없음 |

### 목표 상태

| 항목 | 목표 |
|------|------|
| 렌더링 일관성 | ✅ 단일 `UnifiedGraphView` — 3개 모드 공통 |
| 레이아웃 | ✅ d3-force + forceCollide |
| 엣지 | ✅ 타입별 색상+굵기, 적절한 opacity |
| 노드 | ✅ 외부 레이블 + 줌 기반 표시 |
| 인터랙션 | ✅ N-hop highlight, hover tooltip, 검색/필터 |
| 데이터 | ✅ wikilink + tag 엣지, weight 기반 시각화 |
