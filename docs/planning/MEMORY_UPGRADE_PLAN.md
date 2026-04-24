# Memory 시스템 고도화 구현 기획서

> **⚠️ Historical — superseded.**
> 본 문서는 2026-03-29 작성된 **초기 자체 설계안**이며, 이후
> `geny-executor>=0.20.0` 의 `MemoryProvider` DSL 이 상위 아키텍처로
> 채택되면서 실제 구현은 [`dev_docs/20260419/plan/03_memory_migration.md`](../dev_docs/20260419/plan/03_memory_migration.md)
> 과 [`dev_docs/20260419/plan/06_rollout_and_verification.md`](../dev_docs/20260419/plan/06_rollout_and_verification.md)
> 의 롤아웃을 따랐다. 구현 내역은
> [`dev_docs/20260419/progress/index.md`](../dev_docs/20260419/progress/index.md) 의 Phase 2 / Phase 4 /
> Phase 5 / Phase 7 섹션을 참조.
>
> 히스토리컬 기록으로 보존된다 — 현재 시스템의 동작 기준이 아니다.

---

> **작성일**: 2026-03-29
> **대상 프로젝트**: Geny (AI Agent Orchestration Platform)
> **목표**: 현재 단순 MD 파일 기반의 메모리 시스템을 Obsidian 수준의 지식 관리 체계로 고도화

---

## 목차

1. [현재 시스템 분석](#1-현재-시스템-분석)
2. [문제점 및 한계](#2-문제점-및-한계)
3. [고도화 목표](#3-고도화-목표)
4. [Phase 1 — 메모리 저장 로직 고도화 (Obsidian-like)](#phase-1--메모리-저장-로직-고도화-obsidian-like)
5. [Phase 2 — Memory 전용 API 계층 구축](#phase-2--memory-전용-api-계층-구축)
6. [Phase 3 — Frontend Memory 탭 구현](#phase-3--frontend-memory-탭-구현)
7. [Phase 4 — Agent Memory 도구 (Built-in Tool)](#phase-4--agent-memory-도구-built-in-tool)
8. [Phase 5 — 기존 노드/워크플로우 통합 개선](#phase-5--기존-노드워크플로우-통합-개선)
9. [Phase 6 — 크로스 세션 메모리 및 글로벌 지식](#phase-6--크로스-세션-메모리-및-글로벌-지식)
10. [DB 스키마 변경사항](#db-스키마-변경사항)
11. [파일 변경 매트릭스](#파일-변경-매트릭스)
12. [구현 우선순위 및 의존관계](#구현-우선순위-및-의존관계)

---

## 1. 현재 시스템 분석

### 1.1 아키텍처 개요

현재 메모리 시스템은 3계층 구조로 구성되어 있다:

```
SessionMemoryManager (통합 Facade)
├── LongTermMemory      → memory/*.md 파일 기반
├── ShortTermMemory     → transcripts/session.jsonl 기반
└── VectorMemoryManager → FAISS IndexFlatIP 기반
```

> **근거**: [backend/service/memory/manager.py](../backend/service/memory/manager.py) — `SessionMemoryManager` 클래스

### 1.2 Long-Term Memory (LTM) — 현재 구조

```
{storage_path}/memory/
├── MEMORY.md              ← append-only, 타임스탬프 기반 추가
├── 2026-03-21.md          ← 날짜별 실행 기록
├── 2026-03-20.md
└── topics/
    ├── python-basics.md   ← 토픽별 파일 (slugified)
    └── api-design.md
```

**저장 방식**:
- `append(text, heading)` → `MEMORY.md`에 KST 타임스탬프와 함께 추가
- `write_dated(text)` → `YYYY-MM-DD.md` 파일에 섹션 추가
- `write_topic(topic, text)` → `topics/<slug>.md` 파일에 섹션 추가

> **근거**: [backend/service/memory/long_term.py](../backend/service/memory/long_term.py) — `LongTermMemory` 클래스

### 1.3 Short-Term Memory (STM) — 현재 구조

```
{storage_path}/transcripts/
├── session.jsonl     ← JSONL 형식, 최대 2000 엔트리
└── summary.md        ← 세션 요약
```

**JSONL 형식**:
```json
{"type": "message", "role": "user", "content": "...", "ts": "2026-03-21T15:30:00"}
{"type": "event", "event": "tool_call", "data": {"name": "...", "args": {}}, "ts": "..."}
```

> **근거**: [backend/service/memory/short_term.py](../backend/service/memory/short_term.py) — `ShortTermMemory` 클래스

### 1.4 Vector Memory — 현재 구조

```
{storage_path}/vectordb/
├── index.faiss       ← FAISS IndexFlatIP (코사인 유사도)
└── metadata.json     ← 청크 메타데이터
```

- 임베딩 프로바이더: OpenAI / Google / Voyage AI
- 청킹: 문단 → 문장 → 줄 기반 스마트 분할 (chunk_size=1024, overlap=256)
- 검색: top_k=6, score_threshold=0.35

> **근거**: [backend/service/memory/vector_store.py](../backend/service/memory/vector_store.py), [backend/service/memory/vector_memory.py](../backend/service/memory/vector_memory.py)

### 1.5 DB 스키마 — 현재 구조

**테이블**: `session_memory_entries`

| 컬럼 | 타입 | 설명 |
|------|------|------|
| entry_id | TEXT UNIQUE | UUID |
| session_id | TEXT | 세션 ID |
| source | TEXT | 'long_term' \| 'short_term' |
| entry_type | TEXT | 'text' \| 'message' \| 'event' \| 'dated' \| 'topic' \| 'summary' |
| content | TEXT | 본문 |
| filename | TEXT | 파일명 (e.g. "memory/MEMORY.md") |
| heading | TEXT | 마크다운 헤딩 |
| topic | TEXT | 토픽 슬러그 |
| role | TEXT | user \| assistant \| system |
| event_name | TEXT | tool_call, state_change 등 |
| metadata_json | TEXT | 추가 필드 JSON |
| entry_timestamp | TEXT | ISO 타임스탬프 |

> **근거**: [backend/service/database/models/session_memory_entry.py](../backend/service/database/models/session_memory_entry.py)

### 1.6 워크플로우 통합 — 현재 동작

```
그래프 시작 → MemoryInjectNode (LLM 게이트 판단)
  ├─ memory_context (XML 포맷) → 상태에 주입
  ├─ memory_refs (메타데이터 리스트) → 상태에 주입
  └─ 모델 호출 시 컨텍스트로 활용

실행 완료 → record_execution()
  ├─ memory/YYYY-MM-DD.md에 구조화된 실행 기록
  └─ FAISS 인덱싱 (벡터 메모리 활성화 시)
```

> **근거**: [backend/service/workflow/nodes/memory/memory_inject_node.py](../backend/service/workflow/nodes/memory/memory_inject_node.py), [backend/service/executor/agent_session.py](../backend/service/executor/agent_session.py)

### 1.7 Frontend — 현재 상태

- **Memory 전용 탭 없음** — 세션 탭은 `command`, `graph`, `storage`, `sessionTools`, `logs` 5개
- 메모리 파일은 `StorageTab`의 파일 트리에서 간접적으로만 확인 가능
- 메모리 검색/편집/관리 UI 없음
- **Memory 관련 API 엔드포인트 없음** — 모든 메모리 접근은 서비스 레이어 내부에서만

> **근거**: [frontend/src/components/TabNavigation.tsx](../frontend/src/components/TabNavigation.tsx) (SESSION_TAB_DEFS), [frontend/src/components/TabContent.tsx](../frontend/src/components/TabContent.tsx) (TAB_MAP), [frontend/src/lib/api.ts](../frontend/src/lib/api.ts)

---

## 2. 문제점 및 한계

### 2.1 저장 로직의 한계

| 문제 | 현재 상태 | 영향 |
|------|-----------|------|
| **단순 append-only** | MEMORY.md에 무한 추가만 가능 | 256KB 제한 도달 시 정보 손실, 중복 적재 |
| **구조화 부재** | 플랫 텍스트, 인라인 태그 없음 | 관련 정보끼리 연결 불가 |
| **Backlink 없음** | 파일 간 참조 없음 | 지식 그래프 구성 불가 |
| **태그/분류 없음** | 토픽 폴더만 존재 | 교차 분류 불가 (하나의 지식이 여러 토픽에 속할 수 없음) |
| **메타데이터 빈약** | 타임스탬프만 기록 | 중요도, 출처, 신뢰도 등 추적 불가 |
| **자동 정리 없음** | 쌓이기만 함 | 토큰 낭비, 노이즈 증가 |
| **Agent 직접 제어 불가** | 노드 내부에서만 호출 | Agent가 능동적으로 메모리를 쓰거나 검색할 수 없음 |

### 2.2 검색의 한계

| 문제 | 현재 상태 |
|------|-----------|
| **키워드만 의존** | `keyword_density * 0.7 + recency * 0.3` 단순 스코어링 |
| **벡터 검색 선택적** | LTM config에서 별도 활성화 필요 (기본값 disabled) |
| **크로스 세션 검색 없음** | 세션 간 지식 공유 불가 |
| **의미 기반 연결 없음** | Obsidian의 Graph View 같은 관계 파악 불가 |

### 2.3 Frontend UX 한계

| 문제 | 현재 상태 |
|------|-----------|
| **전용 UI 없음** | StorageTab에서 raw 파일만 조회 가능 |
| **검색 불가** | 메모리 내용 검색 UI 없음 |
| **편집 불가** | 읽기 전용 파일 뷰어만 존재 |
| **시각화 없음** | 지식 구조를 파악할 수 없음 |

---

## 3. 고도화 목표

### 3.1 Obsidian-like 지식 관리 (저장 로직 고도화)

- **YAML Frontmatter 메타데이터**: 모든 메모리 파일에 태그, 별칭, 생성일, 수정일, 중요도, 출처 등 포함
- **Wikilink `[[]]` 기반 Backlink**: 메모리 간 상호 참조
- **다중 태그 시스템**: 하나의 지식이 여러 카테고리에 속할 수 있음
- **자동 정리/압축 (Compaction)**: 오래된/중복 정보를 요약하여 통합
- **계층적 구조**: `daily/`, `topics/`, `entities/`, `projects/` 등 체계적 분류

### 3.2 Memory 탭 (Frontend)

- 세션 선택 시 **Memory 탭** 추가 (스크린샷 2번 참조)
- 파일 트리 + MD 렌더링 (Obsidian Vault 뷰어와 유사)
- 메모리 검색, 태그 필터링, Graph View
- 메모리 편집 기능 (CRUD)

### 3.3 Agent Memory Tool

- Agent가 **직접** 메모리를 읽고, 쓰고, 검색할 수 있는 Built-in Tool
- 워크플로우 노드와 독립적으로 작동
- 메모리의 구조화된 조작 (태그 추가, 링크 생성, 검색 등)

---

## Phase 1 — 메모리 저장 로직 고도화 (Obsidian-like)

### 1.1 새로운 디렉토리 구조

```
{storage_path}/memory/
├── _index.json                    ← 전체 인덱스 (파일 메타데이터 캐시)
├── MEMORY.md                      ← 핵심 지식 (기존 유지, 포맷 강화)
│
├── daily/                         ← 날짜별 기록 (기존 dated 파일 이관)
│   ├── 2026-03-29.md
│   └── 2026-03-28.md
│
├── topics/                        ← 토픽별 지식 (기존 유지, 포맷 강화)
│   ├── python-async.md
│   └── api-design.md
│
├── entities/                      ← ★ 신규: 엔티티(개체) 지식
│   ├── fastapi.md                 ← 프레임워크/라이브러리
│   ├── postgresql.md              ← 기술 스택
│   └── user-preference.md         ← 사용자 선호도
│
├── projects/                      ← ★ 신규: 프로젝트별 지식
│   └── geny-optimization.md
│
├── insights/                      ← ★ 신규: 패턴/인사이트/교훈
│   ├── error-patterns.md
│   └── performance-tips.md
│
└── _attachments/                  ← ★ 신규: 코드 스니펫, 구조화된 데이터
    └── code-snippet-001.py
```

### 1.2 YAML Frontmatter 표준 포맷

모든 메모리 MD 파일에 YAML frontmatter를 추가:

```markdown
---
title: FastAPI 비동기 패턴
aliases: [fastapi-async, fast-api-patterns]
tags: [python, fastapi, async, backend]
category: topics              # daily | topics | entities | projects | insights
importance: high              # low | medium | high | critical
created: 2026-03-29T15:30:00+09:00
modified: 2026-03-29T16:45:00+09:00
source: execution             # execution | user | agent | system | import
session_id: abc-123           # 생성된 세션 ID
linked_from: []               # 이 문서를 참조하는 다른 문서들 (자동 갱신)
links_to: []                  # 이 문서가 참조하는 다른 문서들 (자동 갱신)
---

# FastAPI 비동기 패턴

## 핵심 내용
- `async def` 엔드포인트는 이벤트 루프에서 실행
- CPU-bound 작업은 `run_in_executor` 사용 필요

## 관련 지식
- [[python-async]] — Python async/await 기본 개념
- [[api-design]] — REST API 설계 원칙

## 기록 이력
- 2026-03-29: Execution #3에서 학습 (세션 abc-123)
```

### 1.3 핵심 구현: `StructuredMemoryWriter` 클래스

**신규 파일**: `backend/service/memory/structured_writer.py`

기존 `LongTermMemory`를 확장하되, 호환성을 유지하면서 구조화된 쓰기를 지원:

```python
class StructuredMemoryWriter:
    """Obsidian-like structured memory writing with frontmatter, tags, and backlinks."""

    def __init__(self, storage_path: str, long_term: LongTermMemory):
        self.storage_path = storage_path
        self.memory_dir = os.path.join(storage_path, "memory")
        self.ltm = long_term
        self._index: MemoryIndex = None

    # ── 구조화된 쓰기 ──
    def write_note(self, title: str, content: str,
                   category: str = "topics",
                   tags: List[str] = None,
                   importance: str = "medium",
                   links: List[str] = None,
                   source: str = "agent") -> str:
        """Frontmatter 포함한 구조화된 노트 작성. 파일명 반환."""
        ...

    def update_note(self, filename: str, content: str = None,
                    tags: List[str] = None,
                    importance: str = None,
                    append: bool = False) -> bool:
        """기존 노트 업데이트 (frontmatter + content)"""
        ...

    def link_notes(self, source_file: str, target_file: str) -> bool:
        """두 노트 간 양방향 링크 생성"""
        ...

    # ── 인덱스 관리 ──
    def rebuild_index(self) -> MemoryIndex:
        """전체 파일을 스캔하여 _index.json 재구성"""
        ...

    def get_index(self) -> MemoryIndex:
        """캐시된 인덱스 반환 (없으면 빌드)"""
        ...

    # ── 자동 정리 ──
    def compact_daily(self, older_than_days: int = 30) -> int:
        """오래된 daily 노트를 요약·병합"""
        ...

    def deduplicate(self) -> int:
        """유사 내용 감지 및 병합 제안"""
        ...
```

> **수정 대상**: [backend/service/memory/long_term.py](../backend/service/memory/long_term.py) — 기존 `append()`, `write_dated()`, `write_topic()` 메서드를 frontmatter 지원 버전으로 확장

### 1.4 `MemoryIndex` — 전체 인덱스 구조

**신규 파일**: `backend/service/memory/index.py`

```python
@dataclass
class MemoryFileInfo:
    filename: str           # 상대 경로 (e.g. "topics/python-async.md")
    title: str
    category: str
    tags: List[str]
    importance: str
    created: str            # ISO 타임스탬프
    modified: str
    source: str
    char_count: int
    links_to: List[str]     # [[wikilink]] 대상
    linked_from: List[str]  # 역참조
    summary: Optional[str]  # 자동 생성 요약 (첫 200자)

@dataclass
class MemoryIndex:
    files: Dict[str, MemoryFileInfo]   # filename → info
    tag_map: Dict[str, List[str]]      # tag → [filename, ...]
    link_graph: Dict[str, List[str]]   # filename → [linked filenames]
    last_rebuilt: str                   # ISO 타임스탬프
    total_chars: int
    total_files: int
```

`_index.json`으로 디스크에 캐시하며, 파일 변경 시 incremental 업데이트:

```python
def _update_index_for_file(self, filename: str):
    """단일 파일 변경 시 인덱스 부분 업데이트"""
    # 1. 파일 읽어서 frontmatter 파싱
    # 2. MemoryFileInfo 생성
    # 3. tag_map, link_graph 갱신
    # 4. backlink (linked_from) 역방향 갱신
    # 5. _index.json 저장
```

### 1.5 `record_execution()` 강화

기존 `record_execution` 출력을 구조화:

**현재** (단순 append):
```markdown
### [✅] Execution #3 — hard path
> **Task:** 사용자 인증 시스템 구현
...
```

**개선 후** (frontmatter + wikilink):
```markdown
---
title: "Execution #3 — 사용자 인증 시스템 구현"
tags: [execution, authentication, hard-path, success]
category: daily
importance: medium
created: 2026-03-29T15:30:00+09:00
source: execution
session_id: abc-123
execution_number: 3
difficulty: hard
success: true
duration_ms: 45230
---

# Execution #3 — 사용자 인증 시스템 구현

## 결과
✅ 성공 | 45.2초 | 5/10 반복

## 학습된 지식
- JWT 토큰 갱신 시 [[fastapi]] 미들웨어 활용
- [[postgresql]] 인덱스 전략이 인증 쿼리 성능에 핵심

## TODO 결과
- ✅ JWT 발급 로직 구현
- ✅ Refresh token 관리
- ✅ 미들웨어 통합

## 원본 출력
(truncated preview...)
```

> **수정 대상**: [backend/service/memory/manager.py](../backend/service/memory/manager.py) `record_execution()` 메서드

### 1.6 YAML Frontmatter 파서

**신규 파일**: `backend/service/memory/frontmatter.py`

```python
def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """YAML frontmatter와 본문을 분리하여 반환"""
    ...

def render_frontmatter(metadata: Dict[str, Any], body: str) -> str:
    """메타데이터와 본문을 MD 파일로 결합"""
    ...

def extract_wikilinks(content: str) -> List[str]:
    """[[wikilink]] 패턴을 모두 추출"""
    ...

def resolve_wikilink(link: str, memory_dir: str) -> Optional[str]:
    """wikilink를 실제 파일 경로로 해석"""
    ...
```

### 1.7 기존 데이터 마이그레이션

기존 메모리 파일은 하위 호환성 유지하며 점진적 마이그레이션:

```python
class MemoryMigrator:
    """기존 플랫 MD 파일을 구조화된 형식으로 마이그레이션"""

    def migrate_session(self, storage_path: str) -> MigrationReport:
        """
        1. memory/*.md 스캔
        2. frontmatter 없는 파일 감지
        3. 날짜별 파일 → daily/ 이동 + frontmatter 추가
        4. 토픽 파일 → frontmatter 추가
        5. MEMORY.md → frontmatter 추가 (내용 유지)
        6. _index.json 생성
        """
        ...
```

> **수정 대상**: [backend/service/memory/manager.py](../backend/service/memory/manager.py) `initialize()` 메서드에 자동 마이그레이션 호출 추가

---

## Phase 2 — Memory 전용 API 계층 구축

### 2.1 신규 Controller: `memory_controller.py`

**신규 파일**: `backend/controller/memory_controller.py`

현재 Memory 관련 REST API가 전혀 없으므로, 전용 컨트롤러를 신규 생성:

```python
router = APIRouter(prefix="/api/agents/{session_id}/memory", tags=["memory"])
```

### 2.2 API 엔드포인트 설계

#### 파일 목록 및 인덱스

| Method | Endpoint | 설명 |
|--------|----------|------|
| `GET` | `/api/agents/{sid}/memory` | 메모리 인덱스 반환 (전체 파일 목록 + 메타데이터) |
| `GET` | `/api/agents/{sid}/memory/stats` | 통계 (파일 수, 총 크기, 태그 분포 등) |
| `GET` | `/api/agents/{sid}/memory/tags` | 전체 태그 목록 + 파일 수 |
| `GET` | `/api/agents/{sid}/memory/graph` | 링크 그래프 (노드/엣지) — Graph View용 |

#### 파일 CRUD

| Method | Endpoint | 설명 |
|--------|----------|------|
| `GET` | `/api/agents/{sid}/memory/files/{path:path}` | 단일 파일 읽기 (frontmatter 파싱 포함) |
| `POST` | `/api/agents/{sid}/memory/files` | 새 노트 생성 |
| `PUT` | `/api/agents/{sid}/memory/files/{path:path}` | 노트 수정 (메타데이터 + 본문) |
| `DELETE` | `/api/agents/{sid}/memory/files/{path:path}` | 노트 삭제 (인덱스 자동 갱신) |

#### 검색

| Method | Endpoint | 설명 |
|--------|----------|------|
| `GET` | `/api/agents/{sid}/memory/search?q={query}` | 통합 검색 (키워드 + 벡터 + 태그) |
| `GET` | `/api/agents/{sid}/memory/search?tag={tag}` | 태그 기반 필터링 |
| `GET` | `/api/agents/{sid}/memory/search?category={cat}` | 카테고리 필터링 |

#### 관리

| Method | Endpoint | 설명 |
|--------|----------|------|
| `POST` | `/api/agents/{sid}/memory/compact` | 자동 정리/압축 실행 |
| `POST` | `/api/agents/{sid}/memory/reindex` | 인덱스 재구성 |
| `POST` | `/api/agents/{sid}/memory/migrate` | 기존 형식 → 구조화 형식 마이그레이션 |

### 2.3 API 응답 모델

```python
# ── 인덱스 응답 ──
class MemoryIndexResponse(BaseModel):
    total_files: int
    total_chars: int
    categories: Dict[str, int]          # category → file count
    files: List[MemoryFileResponse]

class MemoryFileResponse(BaseModel):
    filename: str
    title: str
    category: str
    tags: List[str]
    importance: str
    created: str
    modified: str
    char_count: int
    summary: Optional[str]              # 첫 200자

# ── 파일 상세 응답 ──
class MemoryFileDetailResponse(BaseModel):
    filename: str
    title: str
    metadata: Dict[str, Any]            # frontmatter 전체
    content: str                        # 본문 (frontmatter 제외)
    raw: str                            # 전체 원문 (frontmatter 포함)
    links_to: List[str]
    linked_from: List[str]

# ── 검색 응답 ──
class MemorySearchResponse(BaseModel):
    query: str
    results: List[MemorySearchResultResponse]
    total: int

class MemorySearchResultResponse(BaseModel):
    filename: str
    title: str
    score: float
    snippet: str
    match_type: str                     # keyword | vector | tag
    tags: List[str]

# ── 그래프 응답 ──
class MemoryGraphResponse(BaseModel):
    nodes: List[MemoryGraphNode]
    edges: List[MemoryGraphEdge]

class MemoryGraphNode(BaseModel):
    id: str                             # filename
    label: str                          # title
    category: str
    importance: str
    size: int                           # char_count 기반

class MemoryGraphEdge(BaseModel):
    source: str
    target: str
    type: str                           # "wikilink" | "tag_overlap" | "semantic"
```

> **등록 위치**: [backend/main.py](../backend/main.py) — 라우터 등록 (`app.include_router(memory_router)`)

---

## Phase 3 — Frontend Memory 탭 구현

### 3.1 탭 등록

**수정 파일 1**: [frontend/src/components/TabNavigation.tsx](../frontend/src/components/TabNavigation.tsx)

```typescript
// 기존
const SESSION_TAB_DEFS = [
  { id: 'command', accent: true },
  { id: 'graph' },
  { id: 'storage' },
  { id: 'sessionTools' },
  { id: 'logs' },
] as const;

// 변경 후
const SESSION_TAB_DEFS = [
  { id: 'command', accent: true },
  { id: 'memory' },          // ★ 추가
  { id: 'graph' },
  { id: 'storage' },
  { id: 'sessionTools' },
  { id: 'logs' },
] as const;
```

**수정 파일 2**: [frontend/src/store/useAppStore.ts](../frontend/src/store/useAppStore.ts)

```typescript
// 기존
const SESSION_TAB_IDS = new Set(['command', 'logs', 'storage', 'graph', 'info', 'sessionTools']);

// 변경 후
const SESSION_TAB_IDS = new Set(['command', 'memory', 'logs', 'storage', 'graph', 'info', 'sessionTools']);
```

**수정 파일 3**: [frontend/src/components/TabContent.tsx](../frontend/src/components/TabContent.tsx)

```typescript
const MemoryTab = dynamic(() => import('@/components/tabs/MemoryTab'));

const TAB_MAP: Record<string, React.ComponentType> = {
  // ... 기존 유지
  memory: MemoryTab,      // ★ 추가
};
```

**수정 파일 4**: 국제화

[frontend/src/lib/i18n/ko.ts](../frontend/src/lib/i18n/ko.ts):
```typescript
tabs: {
  // ... 기존 유지
  memory: '메모리',        // ★ 추가
},
```

[frontend/src/lib/i18n/en.ts](../frontend/src/lib/i18n/en.ts):
```typescript
tabs: {
  // ... 기존 유지
  memory: 'Memory',        // ★ 추가
},
```

### 3.2 MemoryTab 컴포넌트 설계

**신규 파일**: `frontend/src/components/tabs/MemoryTab.tsx`

3-패널 레이아웃 (Obsidian과 유사):

```
┌───────────────────────────────────────────────────────────────┐
│ [검색바]  [태그 필터▼]  [카테고리 필터▼]  [+ 새 노트]  [정리] │
├──────────────┬────────────────────────────────────────────────┤
│              │                                                │
│  파일 트리    │  MD 렌더러 / 에디터                             │
│  (Sidebar)   │                                                │
│              │  ┌──────────────────────────────────────────┐  │
│  📁 daily    │  │  ---                                     │  │
│  📁 topics   │  │  title: FastAPI 비동기 패턴               │  │
│  📁 entities │  │  tags: [python, fastapi]                 │  │
│  📁 projects │  │  ---                                     │  │
│  📁 insights │  │                                          │  │
│  📄 MEMORY   │  │  # FastAPI 비동기 패턴                    │  │
│              │  │  ## 핵심 내용                              │  │
│  ─── 태그 ── │  │  - async def 엔드포인트는...              │  │
│  #python (5) │  │                                          │  │
│  #fastapi(3) │  │  ## 관련 지식                             │  │
│  #async  (4) │  │  - [[python-async]]                      │  │
│              │  │  - [[api-design]]                        │  │
│              │  └──────────────────────────────────────────┘  │
│              │                                                │
│              │  ┌── 메타데이터 패널 (하단 접이식) ──────────┐  │
│              │  │ 생성: 2026-03-29  수정: 2026-03-29       │  │
│              │  │ 중요도: ⬛⬛⬛⬜ high  출처: execution    │  │
│              │  │ 역참조: api-design.md, auth-patterns.md  │  │
│              │  └──────────────────────────────────────────┘  │
├──────────────┴────────────────────────────────────────────────┤
│ 총 15개 노트 | 12,345자 | 마지막 업데이트: 5분 전               │
└───────────────────────────────────────────────────────────────┘
```

### 3.3 서브 컴포넌트 구조

```
frontend/src/components/tabs/MemoryTab.tsx          ← 메인 탭
frontend/src/components/memory/
├── MemoryFileTree.tsx       ← 좌측 파일 트리 (카테고리별 폴더)
├── MemoryViewer.tsx         ← MD 렌더러 (읽기 모드, wikilink 해석)
├── MemoryEditor.tsx         ← MD 에디터 (편집 모드, frontmatter 폼)
├── MemorySearchBar.tsx      ← 통합 검색 (키워드 + 태그 + 카테고리)
├── MemoryTagCloud.tsx       ← 태그 클라우드/필터
├── MemoryMetaPanel.tsx      ← 메타데이터 패널 (하단 접이식)
├── MemoryGraphView.tsx      ← ★ 선택적: 지식 그래프 시각화 (D3/Force)
├── MemoryCreateModal.tsx    ← 새 노트 생성 모달
└── MemoryStatsBar.tsx       ← 하단 상태바 (파일 수, 크기 등)
```

### 3.4 API 클라이언트 확장

**수정 파일**: [frontend/src/lib/api.ts](../frontend/src/lib/api.ts)

```typescript
// ── Memory API ── ★ 신규 추가
export const memoryApi = {
  /** GET /api/agents/{sid}/memory — 인덱스 */
  getIndex: (sid: string) =>
    apiCall<MemoryIndexResponse>(`/api/agents/${sid}/memory`),

  /** GET /api/agents/{sid}/memory/stats — 통계 */
  getStats: (sid: string) =>
    apiCall<MemoryStatsResponse>(`/api/agents/${sid}/memory/stats`),

  /** GET /api/agents/{sid}/memory/tags — 태그 목록 */
  getTags: (sid: string) =>
    apiCall<MemoryTagsResponse>(`/api/agents/${sid}/memory/tags`),

  /** GET /api/agents/{sid}/memory/graph — 지식 그래프 */
  getGraph: (sid: string) =>
    apiCall<MemoryGraphResponse>(`/api/agents/${sid}/memory/graph`),

  /** GET /api/agents/{sid}/memory/files/{path} — 파일 읽기 */
  getFile: (sid: string, path: string) =>
    apiCall<MemoryFileDetailResponse>(`/api/agents/${sid}/memory/files/${encodeURIComponent(path)}`),

  /** POST /api/agents/{sid}/memory/files — 새 노트 */
  createFile: (sid: string, data: CreateMemoryNoteRequest) =>
    apiCall<MemoryFileResponse>(`/api/agents/${sid}/memory/files`, {
      method: 'POST', body: JSON.stringify(data),
    }),

  /** PUT /api/agents/{sid}/memory/files/{path} — 수정 */
  updateFile: (sid: string, path: string, data: UpdateMemoryNoteRequest) =>
    apiCall<MemoryFileResponse>(`/api/agents/${sid}/memory/files/${encodeURIComponent(path)}`, {
      method: 'PUT', body: JSON.stringify(data),
    }),

  /** DELETE /api/agents/{sid}/memory/files/{path} — 삭제 */
  deleteFile: (sid: string, path: string) =>
    apiCall<{ success: boolean }>(`/api/agents/${sid}/memory/files/${encodeURIComponent(path)}`, {
      method: 'DELETE',
    }),

  /** GET /api/agents/{sid}/memory/search — 검색 */
  search: (sid: string, params: MemorySearchParams) =>
    apiCall<MemorySearchResponse>(
      `/api/agents/${sid}/memory/search?${new URLSearchParams(params as Record<string, string>).toString()}`
    ),

  /** POST /api/agents/{sid}/memory/compact — 정리 */
  compact: (sid: string) =>
    apiCall<{ compacted: number }>(`/api/agents/${sid}/memory/compact`, { method: 'POST' }),

  /** POST /api/agents/{sid}/memory/reindex — 재인덱싱 */
  reindex: (sid: string) =>
    apiCall<{ indexed: number }>(`/api/agents/${sid}/memory/reindex`, { method: 'POST' }),
};
```

### 3.5 TypeScript 타입 정의

**수정 파일**: [frontend/src/types/index.ts](../frontend/src/types/index.ts)

```typescript
// ── Memory Types ── ★ 신규 추가

export interface MemoryFileInfo {
  filename: string;
  title: string;
  category: string;
  tags: string[];
  importance: 'low' | 'medium' | 'high' | 'critical';
  created: string;
  modified: string;
  char_count: number;
  summary: string | null;
}

export interface MemoryIndexResponse {
  total_files: number;
  total_chars: number;
  categories: Record<string, number>;
  files: MemoryFileInfo[];
}

export interface MemoryFileDetailResponse {
  filename: string;
  title: string;
  metadata: Record<string, unknown>;
  content: string;
  raw: string;
  links_to: string[];
  linked_from: string[];
}

export interface MemorySearchParams {
  q?: string;
  tag?: string;
  category?: string;
  importance?: string;
  limit?: string;
}

export interface MemorySearchResult {
  filename: string;
  title: string;
  score: number;
  snippet: string;
  match_type: string;
  tags: string[];
}

export interface MemorySearchResponse {
  query: string;
  results: MemorySearchResult[];
  total: number;
}

export interface MemoryGraphNode {
  id: string;
  label: string;
  category: string;
  importance: string;
  size: number;
}

export interface MemoryGraphEdge {
  source: string;
  target: string;
  type: string;
}

export interface MemoryGraphResponse {
  nodes: MemoryGraphNode[];
  edges: MemoryGraphEdge[];
}

export interface CreateMemoryNoteRequest {
  title: string;
  content: string;
  category?: string;
  tags?: string[];
  importance?: string;
}

export interface UpdateMemoryNoteRequest {
  title?: string;
  content?: string;
  tags?: string[];
  importance?: string;
}

export interface MemoryStatsResponse {
  total_files: number;
  total_chars: number;
  categories: Record<string, number>;
  tag_distribution: Record<string, number>;
  importance_distribution: Record<string, number>;
  recent_files: MemoryFileInfo[];
  oldest_file: string | null;
  newest_file: string | null;
}

export interface MemoryTagsResponse {
  tags: Array<{ name: string; count: number }>;
}
```

### 3.6 Wikilink 렌더링

기존 `MarkdownRenderer`를 확장하여 `[[wikilink]]` 구문을 클릭 가능한 링크로 변환:

> **근거/수정 대상**: [frontend/src/components/file-viewer/MarkdownRenderer.tsx](../frontend/src/components/file-viewer/MarkdownRenderer.tsx) — 현재 ReactMarkdown + remarkGfm만 사용

```typescript
// MemoryMarkdownRenderer.tsx — MarkdownRenderer 확장
import remarkWikiLink from 'remark-wiki-link';

// wikilink를 MemoryTab 내부 네비게이션으로 변환:
// [[python-async]] → <a onClick={() => openMemoryFile("topics/python-async.md")}>python-async</a>
```

---

## Phase 4 — Agent Memory 도구 (Built-in Tool)

### 4.1 개요

현재 메모리는 **워크플로우 노드** (`memory_inject_node`, `transcript_record_node`)를 통해서만 접근 가능하다. Agent가 실행 중에 **능동적으로** 메모리를 읽고/쓰고/검색할 수 있는 도구를 추가한다.

> **근거**: [backend/tools/built_in/geny_tools.py](../backend/tools/built_in/geny_tools.py) — 기존 빌트인 도구 패턴 참조

### 4.2 도구 목록

**신규 파일**: `backend/tools/built_in/memory_tools.py`

| 도구 이름 | 설명 | 주요 파라미터 |
|-----------|------|---------------|
| `memory_read` | 특정 메모리 노트 읽기 | `filename` |
| `memory_write` | 새 메모리 노트 작성 | `title`, `content`, `category`, `tags` |
| `memory_update` | 기존 노트 업데이트/추가 | `filename`, `content`, `append`, `tags` |
| `memory_search` | 메모리 통합 검색 | `query`, `tag`, `category`, `max_results` |
| `memory_list` | 메모리 파일 목록 조회 | `category`, `tag`, `importance` |
| `memory_delete` | 메모리 노트 삭제 | `filename` |
| `memory_link` | 두 노트 간 링크 생성 | `source`, `target` |

### 4.3 구현 패턴

기존 빌트인 도구(`geny_session_list` 등)와 동일한 패턴을 따르되, 세션 컨텍스트가 필요하므로 `session_id` 파라미터를 포함:

```python
from tools.base import BaseTool
import logging

logger = logging.getLogger(__name__)

def _get_memory_manager(session_id: str):
    """세션의 SessionMemoryManager 인스턴스를 가져온다."""
    from service.executor.agent_session_manager import AgentSessionManager
    manager = AgentSessionManager.get_instance()
    session = manager.get_session(session_id)
    if not session:
        return None
    return session.memory_manager


class MemoryWriteTool(BaseTool):
    name = "memory_write"
    description = (
        "Save important knowledge, insights, or learned information to long-term memory. "
        "This creates a structured note that persists across sessions. "
        "Use when you discover patterns, learn user preferences, or encounter reusable knowledge."
    )

    def run(self, title: str, content: str,
            session_id: str,
            category: str = "topics",
            tags: str = "",
            importance: str = "medium") -> str:
        """Write a new note to long-term memory.

        Args:
            title: Note title (concise, descriptive)
            content: Note body in markdown
            session_id: Current session ID
            category: One of: topics, entities, projects, insights, daily
            tags: Comma-separated tags (e.g. "python,fastapi,async")
            importance: One of: low, medium, high, critical

        Returns:
            Confirmation with created filename
        """
        mgr = _get_memory_manager(session_id)
        if not mgr:
            return f"Error: Session {session_id} not found"

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        filename = mgr.structured_writer.write_note(
            title=title, content=content,
            category=category, tags=tag_list,
            importance=importance, source="agent"
        )
        return f"✅ Memory saved: {filename}"


class MemorySearchTool(BaseTool):
    name = "memory_search"
    description = (
        "Search through long-term memory for relevant knowledge. "
        "Supports keyword search, tag filtering, and semantic search. "
        "Use when you need to recall past learnings, user preferences, or project context."
    )

    def run(self, query: str,
            session_id: str,
            tag: str = "",
            category: str = "",
            max_results: int = 5) -> str:
        """Search memory for relevant notes.

        Args:
            query: Search query (natural language)
            session_id: Current session ID
            tag: Filter by tag (optional)
            category: Filter by category (optional)
            max_results: Maximum results to return

        Returns:
            Formatted search results with snippets
        """
        mgr = _get_memory_manager(session_id)
        if not mgr:
            return f"Error: Session {session_id} not found"

        results = mgr.search(query, max_results=max_results)
        # 추가: 태그/카테고리 필터링
        if tag:
            results = [r for r in results if tag in (r.entry.metadata.get("tags") or [])]

        if not results:
            return "No matching memories found."

        lines = [f"Found {len(results)} memories:\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"### {i}. {r.entry.filename or 'untitled'} (score: {r.score:.2f})")
            lines.append(f"   {r.snippet[:200]}")
            lines.append("")
        return "\n".join(lines)


class MemoryReadTool(BaseTool):
    name = "memory_read"
    description = (
        "Read a specific memory note by filename. "
        "Returns the full content including metadata."
    )

    def run(self, filename: str, session_id: str) -> str:
        """Read a memory file.

        Args:
            filename: Relative path within memory/ (e.g. "topics/python-async.md")
            session_id: Current session ID

        Returns:
            Full note content
        """
        mgr = _get_memory_manager(session_id)
        if not mgr:
            return f"Error: Session {session_id} not found"

        filepath = os.path.join(mgr.ltm.memory_dir, filename)
        if not os.path.isfile(filepath):
            return f"Memory file not found: {filename}"

        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()


class MemoryListTool(BaseTool):
    name = "memory_list"
    description = (
        "List all memory notes with their metadata. "
        "Can filter by category, tag, or importance."
    )

    def run(self, session_id: str,
            category: str = "",
            tag: str = "",
            importance: str = "") -> str:
        """List memory files with metadata.

        Args:
            session_id: Current session ID
            category: Filter by category (optional)
            tag: Filter by tag (optional)
            importance: Filter by importance level (optional)

        Returns:
            Formatted file listing
        """
        ...


class MemoryUpdateTool(BaseTool):
    name = "memory_update"
    description = (
        "Update an existing memory note. Can append content or modify tags/metadata."
    )

    def run(self, filename: str, session_id: str,
            content: str = "",
            append: bool = True,
            tags: str = "",
            importance: str = "") -> str:
        """Update a memory note.

        Args:
            filename: File to update
            session_id: Current session ID
            content: New content (appended or replaced based on append flag)
            append: If true, append to existing content; if false, replace
            tags: Comma-separated tags to add (merged with existing)
            importance: New importance level (optional)

        Returns:
            Confirmation message
        """
        ...


class MemoryDeleteTool(BaseTool):
    name = "memory_delete"
    description = "Delete a memory note. Use with caution."

    def run(self, filename: str, session_id: str) -> str:
        """Delete a memory file.

        Args:
            filename: File to delete
            session_id: Current session ID

        Returns:
            Confirmation message
        """
        ...


# 도구 등록 (tool_loader.py가 자동 수집)
TOOLS = [
    MemoryWriteTool(),
    MemorySearchTool(),
    MemoryReadTool(),
    MemoryListTool(),
    MemoryUpdateTool(),
    MemoryDeleteTool(),
]
```

### 4.4 session_id 자동 주입

Agent가 `session_id`를 매번 직접 지정할 필요 없도록, MCP Proxy에서 자동 주입 필요:

> **근거**: [backend/tools/_proxy_mcp_server.py](../backend/tools/_proxy_mcp_server.py) — 현재 `session_id`는 환경변수 `GENY_SESSION_ID`로 설정됨

**수정 대상**: [backend/controller/internal_tool_controller.py](../backend/controller/internal_tool_controller.py)

```python
# 현재: 도구 실행 시 session_id를 인자에서 받음
# 개선: memory_* 도구의 경우 요청 헤더의 session_id를 자동 주입
@router.post("/internal/tools/execute")
async def execute_tool(req: ToolExecuteRequest):
    tool = tool_loader.get_tool(req.tool_name)
    args = req.arguments

    # memory 도구는 session_id 자동 주입
    if req.tool_name.startswith("memory_") and "session_id" not in args:
        args["session_id"] = req.session_id  # 프록시에서 전달

    result = tool.run(**args)
    return {"result": result}
```

### 4.5 도구 프롬프트 통합

Agent의 시스템 프롬프트에 메모리 도구 사용 가이드를 추가:

> **수정 대상**: [backend/service/prompt/sections.py](../backend/service/prompt/sections.py) — `SectionLibrary` 클래스

```python
@staticmethod
def memory_tools() -> PromptSection:
    return PromptSection(
        title="Memory Tools",
        content="""
## Memory Management
You have access to long-term memory tools:
- **memory_search**: Search for relevant past knowledge before starting complex tasks
- **memory_write**: Save important discoveries, patterns, and user preferences
- **memory_read**: Read specific notes for detailed context
- **memory_list**: Browse available knowledge by category/tag
- **memory_update**: Add to or modify existing notes

### When to Use Memory
- BEFORE complex tasks: Search for relevant past experience
- AFTER learning something new: Save patterns and insights
- When user mentions preferences: Save to entities/user-preference.md
- After solving hard problems: Document the approach in insights/
        """,
        priority=75,
        mode=PromptMode.FULL,
    )
```

---

## Phase 5 — 기존 노드/워크플로우 통합 개선

### 5.1 MemoryInjectNode 개선

> **수정 대상**: [backend/service/workflow/nodes/memory/memory_inject_node.py](../backend/service/workflow/nodes/memory/memory_inject_node.py)

현재 한계:
- 단순 텍스트 검색 + FAISS → 플랫 XML 태그로 주입
- frontmatter의 태그, 중요도, 링크 정보를 무시

**개선 사항**:

```python
# 1. 중요도 기반 가중치 추가
IMPORTANCE_BOOST = {
    "critical": 2.0,
    "high": 1.5,
    "medium": 1.0,
    "low": 0.5,
}

# 2. 전체 검색에서 frontmatter 태그 매칭 추가
def _search_with_tags(self, query: str, memory_mgr) -> List[MemorySearchResult]:
    # 기존 키워드 + 벡터 검색
    results = memory_mgr.search(query)

    # 태그 매칭 부스트: 쿼리에서 추출한 키워드가 태그에 있으면 점수 상승
    for result in results:
        metadata = result.entry.metadata
        importance = metadata.get("importance", "medium")
        result.score *= IMPORTANCE_BOOST.get(importance, 1.0)

        # 태그 매칭
        tags = metadata.get("tags", [])
        query_words = set(query.lower().split())
        tag_overlap = len(set(t.lower() for t in tags) & query_words)
        if tag_overlap:
            result.score *= (1.0 + 0.3 * tag_overlap)

    return sorted(results, key=lambda r: r.score, reverse=True)

# 3. Backlink context: 선택된 노트의 관련 노트도 포함
def _add_linked_context(self, selected_files, memory_mgr, budget_chars):
    """선택된 파일의 backlink 노트에서 추가 컨텍스트 수집"""
    ...
```

### 5.2 record_execution() 강화

> **수정 대상**: [backend/service/memory/manager.py](../backend/service/memory/manager.py) — `record_execution()` 메서드

```python
async def record_execution(self, input_text, result_state, duration_ms,
                           execution_number, success):
    """
    ★ 개선사항:
    1. daily/ 디렉토리에 frontmatter 포함 파일 저장
    2. 사용된 도구/토픽 자동 태그 추출
    3. 관련 entity 노트와 자동 링크
    4. FAISS 인덱싱 유지
    """
    # 자동 태그 추출
    tags = self._extract_tags_from_execution(input_text, result_state)

    # 구조화된 포맷으로 저장
    self.structured_writer.write_note(
        title=f"Execution #{execution_number} — {input_text[:60]}",
        content=self._format_execution_body(result_state, duration_ms, success),
        category="daily",
        tags=["execution", f"{'success' if success else 'failure'}"] + tags,
        importance="medium" if success else "high",
        source="execution",
    )
```

### 5.3 신규 노드: `MemoryReflectNode`

**신규 파일**: `backend/service/workflow/nodes/memory/memory_reflect_node.py`

실행 후 LLM으로 학습한 내용을 자동 추출하여 메모리에 저장:

```python
class MemoryReflectNode(BaseNode):
    """
    실행 결과를 분석하여 '무엇을 배웠는가?'를 추출하고
    적절한 카테고리/태그로 메모리에 저장.

    위치: 워크플로우 말단 (final_synthesis 이후)
    """
    node_type = "memory_reflect"
    category = "memory"

    REFLECT_PROMPT = """
    Analyze the following execution and extract any reusable knowledge:

    <input>{input}</input>
    <output>{output}</output>

    Return JSON:
    {{
        "learned": [
            {{
                "title": "concise title",
                "content": "what was learned (markdown)",
                "category": "topics|entities|insights",
                "tags": ["tag1", "tag2"],
                "importance": "low|medium|high",
                "related_to": ["existing note filename if applicable"]
            }}
        ],
        "should_save": true/false  // false if nothing meaningful learned
    }}
    """

    async def execute(self, state, context):
        """
        1. LLM에게 실행 결과 분석 요청
        2. 추출된 지식을 structured_writer로 저장
        3. 관련 노트와 자동 링크
        """
        ...
```

### 5.4 워크플로우 템플릿 업데이트

> **수정 대상**: [backend/service/workflow/templates.py](../backend/service/workflow/templates.py)

기존 Autonomous 워크플로우에 `memory_reflect` 노드를 말단에 추가:

```
현재: ... → final_synthesis → END
개선: ... → final_synthesis → memory_reflect → END
```

---

## Phase 6 — 크로스 세션 메모리 및 글로벌 지식

### 6.1 글로벌 메모리 저장소

여러 세션에서 공유하는 **글로벌 지식 저장소** 추가:

```
{STORAGE_ROOT}/_global_memory/
├── _index.json
├── topics/
│   └── shared-patterns.md
├── entities/
│   └── user-preference.md       ← 사용자 선호도 (모든 세션 공유)
└── insights/
    └── common-errors.md
```

### 6.2 구현

**신규 파일**: `backend/service/memory/global_memory.py`

```python
class GlobalMemoryManager:
    """
    크로스 세션 글로벌 메모리.
    SharedFolder와 유사한 방식으로 모든 세션에 접근 가능.
    """

    def __init__(self, global_path: str):
        self.memory_dir = os.path.join(global_path, "_global_memory")
        self.structured_writer = StructuredMemoryWriter(global_path, ...)
        self._index = None

    def promote(self, session_memory_mgr, filename: str):
        """세션 메모리에서 글로벌로 승격"""
        ...

    def search(self, query: str, max_results: int = 5):
        """글로벌 메모리 검색"""
        ...

    def inject_context(self, query: str, max_chars: int = 4000):
        """세션 시작 시 관련 글로벌 지식 주입"""
        ...
```

### 6.3 세션 메모리 → 글로벌 승격 로직

```python
# memory_reflect_node에서 자동 판단:
if learned_item["importance"] == "high" and learned_item["category"] in ("entities", "insights"):
    # 글로벌 메모리로 승격 제안
    global_mgr.promote(session_mgr, filename)
```

### 6.4 API 엔드포인트

```
GET  /api/memory/global               ← 글로벌 메모리 인덱스
GET  /api/memory/global/files/{path}   ← 글로벌 파일 읽기
POST /api/memory/global/files          ← 글로벌 노트 생성
GET  /api/memory/global/search         ← 글로벌 검색

POST /api/agents/{sid}/memory/promote  ← 세션 → 글로벌 승격
```

### 6.5 Frontend Memory 탭 확장

Memory 탭 상단에 **세션 메모리 / 글로벌 메모리** 토글:

```
[세션 메모리] [글로벌 메모리]
```

---

## DB 스키마 변경사항

### 기존 테이블 확장

`session_memory_entries` 테이블에 컬럼 추가:

```sql
-- ★ 신규 컬럼
ALTER TABLE session_memory_entries ADD COLUMN category TEXT DEFAULT 'topics';
ALTER TABLE session_memory_entries ADD COLUMN tags_json TEXT DEFAULT '[]';
ALTER TABLE session_memory_entries ADD COLUMN importance TEXT DEFAULT 'medium';
ALTER TABLE session_memory_entries ADD COLUMN links_to_json TEXT DEFAULT '[]';
ALTER TABLE session_memory_entries ADD COLUMN linked_from_json TEXT DEFAULT '[]';
ALTER TABLE session_memory_entries ADD COLUMN source_type TEXT DEFAULT 'system';  -- system|agent|user|execution
ALTER TABLE session_memory_entries ADD COLUMN summary TEXT;
ALTER TABLE session_memory_entries ADD COLUMN is_global BOOLEAN DEFAULT FALSE;

-- 인덱스 추가
CREATE INDEX idx_mem_entry_category ON session_memory_entries(category);
CREATE INDEX idx_mem_entry_importance ON session_memory_entries(importance);
CREATE INDEX idx_mem_entry_global ON session_memory_entries(is_global);
```

### 선택적: 글로벌 메모리 테이블

```sql
CREATE TABLE IF NOT EXISTS global_memory_entries (
    entry_id TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL DEFAULT 'topics',
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    tags_json TEXT DEFAULT '[]',
    importance TEXT DEFAULT 'medium',
    links_to_json TEXT DEFAULT '[]',
    linked_from_json TEXT DEFAULT '[]',
    source_session_id TEXT,              -- 원본 세션 (있을 경우)
    created_at TEXT NOT NULL,
    modified_at TEXT NOT NULL,
    metadata_json TEXT DEFAULT '{}'
);

CREATE INDEX idx_global_mem_category ON global_memory_entries(category);
CREATE INDEX idx_global_mem_importance ON global_memory_entries(importance);
```

> **수정 대상**: [backend/service/database/models/session_memory_entry.py](../backend/service/database/models/session_memory_entry.py), [backend/service/database/memory_db_helper.py](../backend/service/database/memory_db_helper.py)

---

## 파일 변경 매트릭스

### 신규 생성 파일

| 파일 | Phase | 설명 |
|------|-------|------|
| `backend/service/memory/structured_writer.py` | P1 | 구조화된 메모리 작성기 |
| `backend/service/memory/index.py` | P1 | 메모리 인덱스 관리자 |
| `backend/service/memory/frontmatter.py` | P1 | YAML frontmatter 파서 |
| `backend/service/memory/migrator.py` | P1 | 기존 데이터 마이그레이션 |
| `backend/controller/memory_controller.py` | P2 | Memory REST API |
| `frontend/src/components/tabs/MemoryTab.tsx` | P3 | Memory 탭 메인 컴포넌트 |
| `frontend/src/components/memory/MemoryFileTree.tsx` | P3 | 파일 트리 |
| `frontend/src/components/memory/MemoryViewer.tsx` | P3 | MD 렌더러 |
| `frontend/src/components/memory/MemoryEditor.tsx` | P3 | MD 에디터 |
| `frontend/src/components/memory/MemorySearchBar.tsx` | P3 | 검색 바 |
| `frontend/src/components/memory/MemoryTagCloud.tsx` | P3 | 태그 클라우드 |
| `frontend/src/components/memory/MemoryMetaPanel.tsx` | P3 | 메타데이터 패널 |
| `frontend/src/components/memory/MemoryStatsBar.tsx` | P3 | 상태바 |
| `frontend/src/components/memory/MemoryCreateModal.tsx` | P3 | 생성 모달 |
| `frontend/src/components/memory/MemoryGraphView.tsx` | P3 | 지식 그래프 (선택적) |
| `backend/tools/built_in/memory_tools.py` | P4 | Agent Memory 도구 |
| `backend/service/workflow/nodes/memory/memory_reflect_node.py` | P5 | 자동 학습 추출 노드 |
| `backend/service/memory/global_memory.py` | P6 | 글로벌 메모리 관리자 |
| `backend/service/database/models/global_memory_entry.py` | P6 | 글로벌 메모리 DB 모델 |

### 수정 파일

| 파일 | Phase | 변경 내용 |
|------|-------|-----------|
| `backend/service/memory/long_term.py` | P1 | frontmatter 지원 확장 |
| `backend/service/memory/manager.py` | P1,P5 | `StructuredMemoryWriter` 통합, `record_execution()` 강화 |
| `backend/service/memory/types.py` | P1 | `MemoryEntry`에 metadata 필드 확장 |
| `backend/service/database/models/session_memory_entry.py` | P1 | DB 스키마 확장 |
| `backend/service/database/memory_db_helper.py` | P1,P2 | 확장된 쿼리 함수 |
| `backend/main.py` | P2 | memory_controller 라우터 등록 |
| `frontend/src/components/TabNavigation.tsx` | P3 | Memory 탭 추가 |
| `frontend/src/components/TabContent.tsx` | P3 | MemoryTab 라우팅 |
| `frontend/src/store/useAppStore.ts` | P3 | SESSION_TAB_IDS에 'memory' 추가 |
| `frontend/src/lib/api.ts` | P3 | memoryApi 추가 |
| `frontend/src/lib/i18n/ko.ts` | P3 | Memory 관련 번역 |
| `frontend/src/lib/i18n/en.ts` | P3 | Memory 관련 번역 |
| `frontend/src/types/index.ts` | P3 | Memory 관련 타입 정의 |
| `frontend/src/components/file-viewer/MarkdownRenderer.tsx` | P3 | Wikilink 렌더링 |
| `backend/tools/_proxy_mcp_server.py` | P4 | memory_tools 스키마 등록 |
| `backend/controller/internal_tool_controller.py` | P4 | session_id 자동 주입 |
| `backend/service/prompt/sections.py` | P4 | memory_tools 프롬프트 섹션 |
| `backend/service/workflow/nodes/memory/memory_inject_node.py` | P5 | 중요도/태그 기반 검색 강화 |
| `backend/service/workflow/templates.py` | P5 | memory_reflect 노드 추가 |
| `backend/service/config/sub_config/general/ltm_config.py` | P5 | 신규 config 필드 |

---

## 구현 우선순위 및 의존관계

```
Phase 1 (메모리 저장 고도화)        ──────── 1주 ────────
  ├─ 1.6 frontmatter.py 파서                ★ 의존 없음
  ├─ 1.4 index.py 인덱스 관리               ★ 의존 없음
  ├─ 1.3 structured_writer.py               ← frontmatter.py, index.py 의존
  ├─ 1.2 long_term.py 확장                  ← structured_writer.py 의존
  ├─ 1.7 migrator.py                        ← 전체 P1 구현 후
  └─ 1.5 record_execution 강화              ← structured_writer.py 의존

Phase 2 (API 계층)                  ──────── 0.5주 ────────
  ├─ 2.1 memory_controller.py               ← Phase 1 완료 필요
  ├─ 2.2 라우터 등록 (main.py)                ← controller 필요
  └─ 2.3 응답 모델                           ← controller와 병행

Phase 3 (Frontend)                  ──────── 1.5주 ────────
  ├─ 3.1 탭 등록 (4개 파일)                   ← Phase 2 완료 필요
  ├─ 3.4 API 클라이언트 (api.ts)             ← Phase 2 완료 필요
  ├─ 3.5 TypeScript 타입                     ← 병행 가능
  ├─ 3.2 MemoryTab 메인 컴포넌트             ← API 클라이언트 필요
  ├─ 3.3 서브 컴포넌트들                      ← MemoryTab 필요
  └─ 3.6 Wikilink 렌더링                     ← 병행 가능

Phase 4 (Agent 도구)                ──────── 0.5주 ────────
  ├─ 4.2-4.3 memory_tools.py                ← Phase 1 완료 필요
  ├─ 4.4 session_id 자동 주입                ← 도구 구현 후
  └─ 4.5 프롬프트 통합                        ← 도구 구현 후

Phase 5 (워크플로우 통합)             ──────── 0.5주 ────────
  ├─ 5.1 memory_inject_node 개선             ← Phase 1 완료 필요
  ├─ 5.2 record_execution 강화              ← Phase 1 완료 필요
  ├─ 5.3 MemoryReflectNode                  ← Phase 1 완료 필요
  └─ 5.4 템플릿 업데이트                       ← MemoryReflectNode 필요

Phase 6 (글로벌 메모리)              ──────── 1주 ────────
  ├─ 6.1-6.2 global_memory.py               ← Phase 1, 4 완료 필요
  ├─ 6.3 승격 로직                            ← global_memory 필요
  ├─ 6.4 API 엔드포인트                       ← global_memory 필요
  └─ 6.5 Frontend 확장                       ← Phase 3, 6.4 완료 필요
```

### 의존관계 다이어그램

```
┌──────────┐
│ Phase 1  │ ← 모든 것의 기반
│ 저장 고도화 │
└────┬─────┘
     │
     ├─────────────────┬────────────────┐
     ▼                 ▼                ▼
┌──────────┐    ┌──────────┐    ┌──────────┐
│ Phase 2  │    │ Phase 4  │    │ Phase 5  │
│ API 계층  │    │ Agent 도구│    │ WF 통합  │
└────┬─────┘    └────┬─────┘    └──────────┘
     │               │
     ▼               │
┌──────────┐         │
│ Phase 3  │         │
│ Frontend │         │
└────┬─────┘         │
     │               │
     ├───────────────┘
     ▼
┌──────────┐
│ Phase 6  │
│ 글로벌    │
└──────────┘
```

### 핵심 원칙

1. **하위 호환성**: 기존 플랫 MD 파일은 그대로 읽을 수 있어야 함 (frontmatter 없는 파일도 처리)
2. **점진적 마이그레이션**: 자동 마이그레이션은 세션 초기화 시 한 번만 실행 (idempotent)
3. **Graceful Degradation**: 구조화된 기능이 실패해도 기본 메모리 동작은 유지
4. **Dual-Write 유지**: 파일 + DB 이중 저장 패턴을 그대로 유지
5. **Budget Management**: 프롬프트 주입 시 max_inject_chars 제한 유지
6. **Thread Safety**: FAISS + 인덱스 동시 접근 보호

---

## 부록 A — 주요 근거 파일 목록

| 근거 파일 | 역할 | 참조 위치 |
|-----------|------|-----------|
| [backend/service/memory/manager.py](../backend/service/memory/manager.py) | 메모리 통합 Facade | Phase 1, 5 |
| [backend/service/memory/long_term.py](../backend/service/memory/long_term.py) | LTM 구현체 | Phase 1 |
| [backend/service/memory/short_term.py](../backend/service/memory/short_term.py) | STM 구현체 | Phase 1 |
| [backend/service/memory/vector_store.py](../backend/service/memory/vector_store.py) | FAISS 저장소 | Phase 1, 5 |
| [backend/service/memory/vector_memory.py](../backend/service/memory/vector_memory.py) | 벡터 메모리 오케스트레이터 | Phase 1, 5 |
| [backend/service/memory/embedding.py](../backend/service/memory/embedding.py) | 임베딩 프로바이더 | Phase 1 |
| [backend/service/memory/types.py](../backend/service/memory/types.py) | 데이터 타입 | Phase 1 |
| [backend/service/database/models/session_memory_entry.py](../backend/service/database/models/session_memory_entry.py) | DB 스키마 | Phase 1, DB |
| [backend/service/database/memory_db_helper.py](../backend/service/database/memory_db_helper.py) | DB 헬퍼 함수 | Phase 1, 2 |
| [backend/service/workflow/nodes/memory/memory_inject_node.py](../backend/service/workflow/nodes/memory/memory_inject_node.py) | 메모리 주입 노드 | Phase 5 |
| [backend/service/workflow/nodes/memory/transcript_record_node.py](../backend/service/workflow/nodes/memory/transcript_record_node.py) | 트랜스크립트 기록 노드 | Phase 5 |
| [backend/service/executor/agent_session.py](../backend/service/executor/agent_session.py) | 세션 라이프사이클 | Phase 1, 4, 5 |
| [backend/service/executor/agent_session_manager.py](../backend/service/executor/agent_session_manager.py) | 세션 관리자 | Phase 1, 4 |
| [backend/tools/built_in/geny_tools.py](../backend/tools/built_in/geny_tools.py) | 빌트인 도구 패턴 | Phase 4 |
| [backend/tools/base.py](../backend/tools/base.py) | 도구 기반 클래스 | Phase 4 |
| [backend/tools/_proxy_mcp_server.py](../backend/tools/_proxy_mcp_server.py) | MCP 프록시 | Phase 4 |
| [backend/controller/internal_tool_controller.py](../backend/controller/internal_tool_controller.py) | 도구 실행 엔드포인트 | Phase 4 |
| [backend/service/tool_loader.py](../backend/service/tool_loader.py) | 도구 자동 수집 | Phase 4 |
| [backend/service/prompt/sections.py](../backend/service/prompt/sections.py) | 프롬프트 섹션 | Phase 4 |
| [backend/main.py](../backend/main.py) | 라우터 등록 | Phase 2 |
| [frontend/src/components/TabNavigation.tsx](../frontend/src/components/TabNavigation.tsx) | 탭 네비게이션 | Phase 3 |
| [frontend/src/components/TabContent.tsx](../frontend/src/components/TabContent.tsx) | 탭 라우팅 | Phase 3 |
| [frontend/src/store/useAppStore.ts](../frontend/src/store/useAppStore.ts) | 상태 관리 | Phase 3 |
| [frontend/src/lib/api.ts](../frontend/src/lib/api.ts) | API 클라이언트 | Phase 3 |
| [frontend/src/lib/i18n/ko.ts](../frontend/src/lib/i18n/ko.ts) | 한국어 번역 | Phase 3 |
| [frontend/src/lib/i18n/en.ts](../frontend/src/lib/i18n/en.ts) | 영어 번역 | Phase 3 |
| [frontend/src/types/index.ts](../frontend/src/types/index.ts) | TypeScript 타입 | Phase 3 |
| [frontend/src/components/file-viewer/MarkdownRenderer.tsx](../frontend/src/components/file-viewer/MarkdownRenderer.tsx) | MD 렌더러 | Phase 3 |
| [backend/docs/MEMORY.md](../backend/docs/MEMORY.md) | 메모리 아키텍처 문서 | 전체 참조 |
| [backend/service/config/sub_config/general/ltm_config.py](../backend/service/config/sub_config/general/ltm_config.py) | LTM 설정 | Phase 5 |
| [backend/service/workflow/templates.py](../backend/service/workflow/templates.py) | 워크플로우 템플릿 | Phase 5 |
| [backend/service/shared_folder/shared_folder_manager.py](../backend/service/shared_folder/shared_folder_manager.py) | 공유 폴더 (글로벌 패턴 참조) | Phase 6 |

---

## 부록 B — 리스크 및 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| 기존 MD 파일 마이그레이션 실패 | 메모리 손실 | 마이그레이션 전 백업 + rollback 지원 |
| YAML frontmatter 파싱 오류 | 메타데이터 누락 | 파싱 실패 시 기본값 적용 (graceful degradation) |
| FAISS 인덱스 불일치 | 검색 결과 부정확 | reindex API로 수동 복구 가능 |
| 메모리 파일 크기 폭증 | 토큰 예산 초과 | compact 기능으로 자동 정리, 256KB 제한 유지 |
| 크로스 세션 메모리 충돌 | 데이터 불일치 | 글로벌 메모리는 append-only + 수동 병합 |
| Agent 메모리 도구 남용 | 불필요한 데이터 축적 | 중요도 기반 필터링, 자동 정리 |
| Frontend 성능 저하 | 대량 파일 시 느림 | 페이지네이션 + 가상 스크롤 |

---

*이 기획서는 현재 코드베이스의 심층 분석을 기반으로 작성되었습니다. 각 Phase는 독립적으로 배포 가능하며, Phase 1이 모든 후속 작업의 기반입니다.*
