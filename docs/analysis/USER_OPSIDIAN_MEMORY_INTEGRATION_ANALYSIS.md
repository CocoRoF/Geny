# User Opsidian × Curated Knowledge × Agent Memory 통합 설계서

> **작성일**: 2026-04-05
> **버전**: 2.0 (최종)
> **핵심 원칙**: Curated Knowledge는 기존 Opsidian 시스템과 **100% 호환** — 동일한 엔진, 동일한 노트 포맷, 동일한 UI 컴포넌트 재사용

---

## 목차

1. [현재 시스템 아키텍처](#1-현재-시스템-아키텍처)
2. [핵심 Gap 분석](#2-핵심-gap-분석)
3. [3-Tier + 3-Tab 아키텍처](#3-3-tier--3-tab-아키텍처)
4. [큐레이션 엔진 고도화 설계](#4-큐레이션-엔진-고도화-설계)
5. [완전 호환 Opsidian 시스템](#5-완전-호환-opsidian-시스템)
6. [Agent 통합 설계](#6-agent-통합-설계)
7. [최종 구현 계획](#7-최종-구현-계획)
8. [파일별 변경 사항](#8-파일별-변경-사항)
9. [보안·성능·운영](#9-보안성능운영)

---

## 1. 현재 시스템 아키텍처

### 1.1 공유 엔진 스택 (모든 메모리 스코프가 재사용)

```
StructuredMemoryWriter    → YAML frontmatter + wikilink + 카테고리 디렉토리 구조
MemoryIndexManager        → _index.json (태그맵, 링크 그래프, 파일 메타)
VectorMemoryManager       → FAISS IndexFlatIP + ChunkMeta sidecar
frontmatter.py            → YAML 파싱/렌더링 + [[wikilink]] 추출
```

모든 노트는 동일한 형식을 따른다:
```yaml
---
title: "노트 제목"
tags: [tag1, tag2]
category: topics          # daily | topics | entities | projects | insights | root
importance: medium        # low | medium | high | critical
created: "2026-04-05T..."
modified: "2026-04-05T..."
source: user              # user | reflection | promoted | curated | agent
links_to: [other-note.md]
---
# 본문 Markdown...
```

### 1.2 현재 3-Scope, 2-Tab 구조

| 스코프 | 클래스 | 저장소 | StatusBar 탭 |
|--------|--------|--------|-------------|
| **User Opsidian** | `UserOpsidianManager` | `_user_opsidian/{username}/` | 「사용자」 |
| **Session Memory** | `SessionMemoryManager` | `{session}/memory/` | 「세션」 |
| **Global Memory** | `GlobalMemoryManager` | `_global_memory/` | — (별도 UI 없음) |

### 1.3 현재 프론트엔드 구조

```
OpsidianHub.tsx
├── HubMode: 'user' | 'sessions'          ← 현재 2모드
├── UserOpsidianView   (mode='user')       ← ~1130줄, 인라인 서브컴포넌트
├── ObsidianView       (mode='sessions')   ← ~107줄, 세션 선택 우선
└── StatusBar                              ← 양쪽 스토어 동시 읽기
    └── obs-hub-nav: [사용자] [세션]        ← 현재 탭 2개
```

**핵심 설계 패턴**: StatusBar는 `hub.mode`에 따라 `useUserOpsidianStore` / `useObsidianStore`를 전환하여 파일 수, 문자 수, 태그, 링크 통계를 보여준다. 이 패턴을 그대로 확장하면 3번째 탭(큐레이터)을 추가할 수 있다.

### 1.4 현재 Agent 접근

| 계층 | Agent 접근 방식 |
|------|---------------|
| Session Memory | `memory_*` 7개 도구 (write/read/update/delete/search/list/link) |
| Session Memory (자동) | `MemoryInjectNode` — 5단계 검색 파이프라인으로 state에 자동 주입 |
| Session Memory (반성) | `MemoryReflectNode` — LLM이 인사이트 추출 후 구조화 노트로 저장 |
| User Opsidian | ❌ **Agent 접근 불가** |
| Global Memory | `promote()` 경유만 |

---

## 2. 핵심 Gap 분석

### 2.1 문제: User Opsidian은 "화이트보드"

User Opsidian은 사용자의 자유로운 지식 저장소다:
- 메모, 초안, 브레인스토밍, 임시 기록 등 혼재
- 품질이 보장되지 않는 raw 데이터
- Agent가 직접 접근하면 **노이즈 오염, 예산 낭비, 환각 유발**

### 2.2 Gap 목록

| # | Gap | 영향 |
|---|-----|------|
| G1 | **중간 큐레이션 계층 부재** | Agent가 정제된 사용자 지식에 접근 불가 |
| G2 | **Agent 도구 부재 (사용자 지식)** | `memory_tools.py` 7개 도구는 모두 세션 메모리 전용 |
| G3 | **AgentSession에 username 없음** | Agent가 어떤 사용자의 볼트에 접근해야 할지 모름 |
| G4 | **User Opsidian에 벡터 검색 없음** | 의미 기반 큐레이션·검색 불가능 |
| G5 | **MemoryInjectNode 미연동** | 자동 주입 시 사용자 지식 미포함 |
| G6 | **ExecutionContext에 user 정보 없음** | 워크플로우 노드에서 사용자 스코프 접근 불가 |
| G7 | **큐레이션 파이프라인 부재** | User Opsidian → 정제 → Agent 경로가 없음 |
| G8 | **UI 탭이 2개뿐** | 큐레이팅된 지식을 보여줄 공간 없음 |

---

## 3. 3-Tier + 3-Tab 아키텍처

### 3.1 최종 구조도

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                       3-Tier Knowledge Architecture (per-user)                    │
│                                                                                  │
│  Tier 1: Raw Data Lake         Tier 2: Curated Warehouse       Tier 3: Consumer  │
│  ┌───────────────────────┐     ┌───────────────────────┐     ┌───────────────┐   │
│  │   User Opsidian       │     │   Curated Knowledge   │     │    Agent      │   │
│  │   (화이트보드)          │────→│   (정제된 지식)        │────→│   (소비자)     │   │
│  │                       │     │                       │     │              │   │
│  │ • 메모, 초안           │     │ • 검증된 사실          │     │ • 자동 주입    │   │
│  │ • 잡다한 아이디어      │     │ • 핵심 인사이트        │     │ • 도구 검색    │   │
│  │ • 프로젝트 계획       │     │ • 요약·추출·융합 결과   │     │ • 반성 축적    │   │
│  │ • 학습 기록           │     │ • FAISS 벡터 인덱스     │     │              │   │
│  │                       │     │                       │     │ Index로 Raw   │   │
│  │ source: user          │     │ source: curated       │     │ 열람 가능     │   │
│  └───────────┬───────────┘     └──────────┬────────────┘     └──────┬───────┘   │
│              │                            │                         │            │
│              │    Knowledge Curator       │   MemoryInjectNode      │            │
│              │    (고도화 큐레이션 엔진)    │   + knowledge_* tools   │            │
│              └────────────────────────────┘                         │            │
│                                                                     │            │
│              ┌──────────────────────────────────────────────────────┘            │
│              │ user_doc_browse (Index-first, opt-in raw read)                    │
│              └──────────────────────────────────────────────────────────────────│
│                                                                                  │
│  ── 기존 유지 ──                                                                  │
│  Session Memory (memory_* tools, per-session)                                    │
│  Global Memory (promote, cross-session shared)                                   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 StatusBar 3-Tab UI

```
기존:  [사용자] [세션]
변경:  [사용자] [큐레이터] [세션]
```

```
HubMode = 'user' | 'curator' | 'sessions'
                     ↑ 신규 모드
```

| 탭 | 뷰 컴포넌트 | Zustand 스토어 | 백엔드 API |
|---|-----------|-------------|----------|
| 사용자 | `UserOpsidianView` (기존) | `useUserOpsidianStore` | `/api/opsidian/*` |
| **큐레이터** | **`CuratedKnowledgeView` (신규)** | **`useCuratedKnowledgeStore`** | **`/api/knowledge/*`** |
| 세션 | `ObsidianView` (기존) | `useObsidianStore` | `/api/memory/{session}/*` |

**핵심**: `CuratedKnowledgeView`는 `UserOpsidianView`의 UI/UX를 **그대로** 재사용한다. 같은 사이드바(파일/태그/링크), 같은 노트 에디터, 같은 그래프, 같은 검색. 추가되는 것은 큐레이션 관련 기능(큐레이션 출처 표시, 원본 링크, freshness 상태)뿐이다.

### 3.3 완전 호환 원칙

**Curated Knowledge는 User Opsidian과 동일한 시스템이다:**

| 구성 요소 | User Opsidian | Curated Knowledge |
|-----------|-------------|-------------------|
| 노트 포맷 | YAML frontmatter + Markdown | ✅ 동일 |
| 엔진 | StructuredMemoryWriter | ✅ 동일 (재사용) |
| 인덱스 | MemoryIndexManager (_index.json) | ✅ 동일 (재사용) |
| 벡터 검색 | ❌ 없음 | ✅ VectorMemoryManager 추가 |
| 카테고리 | daily/topics/entities/projects/insights | ✅ 동일 + reference 추가 |
| UI 컴포넌트 | UserOpsidianView | ✅ 동일 패턴 재사용 |
| REST API 패턴 | `/api/opsidian/*` | ✅ `/api/knowledge/*` (동일 구조) |
| 스토어 구조 | useUserOpsidianStore | ✅ 동일 패턴 |

**차별점은 메타데이터에서만 발생한다:**
```yaml
# Curated Knowledge 노트에만 추가되는 필드
source: curated                          # ← "curated" 고정
origin_file: "원본-user-opsidian-파일.md" # ← 원본 추적
origin_scope: "user_opsidian"            # ← user_opsidian | session | agent_reflect
origin_hash: "sha256..."                 # ← freshness 검증
curated_at: "2026-04-05T10:00:00"
curation_method: "summary"               # ← direct|summary|extract|merge|restructure
curation_quality: 0.85                   # ← LLM 평가 점수
```

---

## 4. 큐레이션 엔진 고도화 설계

### 4.1 아키텍처 개요

```
┌────────────────────────────────────────────────────────────────────────┐
│                    Knowledge Curator Engine                             │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────┐       │
│  │  Stage 1: Triage (분류·필터링)                                │       │
│  │  ├ Rule-based 자동 필터 (importance, tags, category, etc.)   │       │
│  │  ├ Length/completeness 필터 (최소 본문 200자, 제목 있음)      │       │
│  │  └ Duplicate 검출 (SHA256 hash + 유사도 벡터 비교)           │       │
│  └───────────────────────────────┬─────────────────────────────┘       │
│                                  │ 후보 노트                            │
│                                  ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐       │
│  │  Stage 2: LLM Analysis (심층 분석)                           │       │
│  │  ├ 품질 평가 (0.0~1.0): 사실성, 완결성, 유용성, 정확성       │       │
│  │  ├ 분류 제안: 카테고리, 태그, 중요도 재평가                   │       │
│  │  ├ 관계 발견: 기존 큐레이팅 노트와의 연관성                   │       │
│  │  └ 큐레이션 전략 결정: direct / summary / extract / merge     │       │
│  └───────────────────────────────┬─────────────────────────────┘       │
│                                  │ 분석 결과                            │
│                                  ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐       │
│  │  Stage 3: Transform (변환·정제)                              │       │
│  │  ├ Direct    → 원본 그대로 복사 (고품질 노트)                 │       │
│  │  ├ Summary   → LLM 요약 (장문 → 핵심 요약)                   │       │
│  │  ├ Extract   → 핵심 사실/패턴만 추출 (목록 형태)              │       │
│  │  ├ Merge     → 관련 노트 2~3개를 하나로 통합                  │       │
│  │  └ Restructure → 구조 재편 (목차화, 코드블록 정리 등)         │       │
│  └───────────────────────────────┬─────────────────────────────┘       │
│                                  │ 변환된 노트                          │
│                                  ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐       │
│  │  Stage 4: Enrich (보강·연결)                                 │       │
│  │  ├ 자동 태그 생성 (LLM 기반)                                 │       │
│  │  ├ 기존 큐레이팅 노트와 [[wikilink]] 자동 연결               │       │
│  │  ├ 중요도 재산정 (문맥 기반)                                 │       │
│  │  └ 벡터 임베딩 생성 + FAISS 인덱스 갱신                      │       │
│  └───────────────────────────────┬─────────────────────────────┘       │
│                                  │ 최종 큐레이팅 노트                    │
│                                  ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐       │
│  │  Stage 5: Store & Audit (저장·감사)                          │       │
│  │  ├ StructuredMemoryWriter로 저장 (기존 엔진)                 │       │
│  │  ├ _index.json 갱신 (기존 엔진)                              │       │
│  │  ├ FAISS 인덱스 갱신 (VectorMemoryManager)                   │       │
│  │  └ _curation_log.jsonl에 감사 기록                           │       │
│  └─────────────────────────────────────────────────────────────┘       │
└────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Stage 1: Triage (규칙 기반 분류)

```python
class CurationTriage:
    """규칙 기반 큐레이션 후보 필터링.

    빠르게 "큐레이션 대상인가?"를 판단하여 LLM 호출 비용을 절약한다.
    """

    # ── 자동 큐레이션 규칙 ──
    IMPORTANCE_THRESHOLD = "high"          # high, critical → 자동 큐레이션
    AUTO_CURATE_TAGS = {
        "important", "reference", "knowledge", "curate-me",
        "핵심", "중요", "레퍼런스"
    }
    AUTO_CURATE_CATEGORIES = {"reference", "insights", "projects"}
    AUTO_CURATE_PREFIXES = ["[REF]", "[핵심]", "[중요]", "[CORE]", "[KEY]"]
    MIN_BODY_LENGTH = 200                  # 최소 본문 길이 (노이즈 필터)

    # ── 자동 제외 규칙 ──
    EXCLUDE_TAGS = {"draft", "temp", "todo", "wip", "초안", "임시"}
    EXCLUDE_PREFIXES = ["[DRAFT]", "[TMP]", "[임시]", "[초안]"]

    @classmethod
    def triage(cls, note_metadata: dict, body: str) -> dict:
        """분류 결과 반환.

        Returns:
            {
                "action": "auto_curate" | "candidate" | "exclude",
                "reason": str,
                "confidence": float,     # 0.0~1.0
            }
        """
        importance = note_metadata.get("importance", "medium")
        tags = set(note_metadata.get("tags", []))
        category = note_metadata.get("category", "")
        title = note_metadata.get("title", "")

        # 자동 제외
        if tags & cls.EXCLUDE_TAGS:
            return {"action": "exclude", "reason": "draft/temp tag", "confidence": 0.95}
        if any(title.startswith(p) for p in cls.EXCLUDE_PREFIXES):
            return {"action": "exclude", "reason": "draft prefix", "confidence": 0.95}
        if len(body.strip()) < cls.MIN_BODY_LENGTH:
            return {"action": "exclude", "reason": "too short", "confidence": 0.80}

        # 자동 큐레이션
        if importance in ("high", "critical"):
            return {"action": "auto_curate", "reason": f"importance={importance}", "confidence": 0.90}
        if tags & cls.AUTO_CURATE_TAGS:
            matched = tags & cls.AUTO_CURATE_TAGS
            return {"action": "auto_curate", "reason": f"tags={matched}", "confidence": 0.85}
        if category in cls.AUTO_CURATE_CATEGORIES:
            return {"action": "auto_curate", "reason": f"category={category}", "confidence": 0.80}
        if any(title.startswith(p) for p in cls.AUTO_CURATE_PREFIXES):
            return {"action": "auto_curate", "reason": "title prefix", "confidence": 0.85}

        # 후보 (LLM 분석 필요)
        return {"action": "candidate", "reason": "needs_llm_analysis", "confidence": 0.50}
```

### 4.3 Stage 2: LLM Analysis (심층 분석)

이 단계가 큐레이션 품질의 **핵심**이다. LLM이 노트를 다차원으로 분석한다.

```python
_CURATION_ANALYSIS_PROMPT = """\
You are a Knowledge Curator AI. Analyze the following user note and \
provide a comprehensive curation assessment.

<note>
<title>{title}</title>
<category>{category}</category>
<tags>{tags}</tags>
<importance>{importance}</importance>
<body>
{body}
</body>
</note>

<existing_knowledge_index>
{existing_index}
</existing_knowledge_index>

Analyze and return JSON:
{{
  "quality_score": 0.0-1.0,       // overall quality for agent use
  "quality_dimensions": {{
    "factual_accuracy": 0.0-1.0,  // how factually reliable
    "completeness": 0.0-1.0,      // how complete the information is
    "actionability": 0.0-1.0,     // how useful for taking action
    "uniqueness": 0.0-1.0,        // not redundant with existing knowledge
    "clarity": 0.0-1.0            // well-organized and clear
  }},
  "should_curate": true/false,
  "curation_strategy": "direct|summary|extract|merge|restructure|skip",
  "strategy_reasoning": "why this strategy was chosen",
  "suggested_title": "improved title if needed (or null)",
  "suggested_category": "topics|insights|entities|projects|reference",
  "suggested_tags": ["tag1", "tag2", "tag3"],
  "suggested_importance": "low|medium|high|critical",
  "related_existing_notes": ["filename1.md", "filename2.md"],
  "merge_candidates": ["filename.md"],  // if strategy is "merge"
  "key_facts": [                  // extracted key facts for "extract" strategy
    "fact 1",
    "fact 2"
  ],
  "summary": "1-2 sentence summary of the note's value"
}}

Quality scoring guidelines:
- 0.9+: Verified facts, technical specs, proven patterns — always curate
- 0.7-0.9: Good insights with context — curate with minor adjustments
- 0.5-0.7: Partial information — extract key parts only
- 0.3-0.5: Rough notes with some value — summarize heavily
- <0.3: Noise, fragments, outdated — skip curation

Strategy selection:
- "direct": quality ≥ 0.8, well-written, complete → copy as-is
- "summary": quality ≥ 0.5, too long or verbose → condense to key points
- "extract": quality ≥ 0.5, contains scattered facts → pull out key facts
- "merge": related to existing note → combine into enhanced version
- "restructure": quality ≥ 0.6, poorly organized → reorganize structure
- "skip": quality < 0.3 or entirely redundant → do not curate"""
```

### 4.4 Stage 3: Transform (변환 전략별 LLM 프롬프트)

각 전략에 최적화된 LLM 프롬프트:

#### 4.4.1 Summary Transform
```python
_TRANSFORM_SUMMARY_PROMPT = """\
You are a Knowledge Curator. Condense the following note into a concise, \
agent-ready knowledge entry.

Rules:
1. Preserve ALL key facts, decisions, and technical details
2. Remove personal musings, redundancy, and filler
3. Use structured format: headers, bullet points, code blocks
4. Keep the original language (Korean or English)
5. Target length: {target_chars} characters maximum

Original note:
<title>{title}</title>
<body>{body}</body>

Return the curated content as clean Markdown (no frontmatter)."""
```

#### 4.4.2 Extract Transform
```python
_TRANSFORM_EXTRACT_PROMPT = """\
You are a Knowledge Extractor. From the following note, extract ONLY \
the key facts, specifications, decisions, and reusable knowledge.

Rules:
1. Extract as structured bullet points grouped by theme
2. Each fact must be self-contained (understandable without context)
3. Include precise numbers, names, versions, and dates
4. Skip opinions, speculation, and incomplete thoughts
5. Keep the original language

Original note:
<title>{title}</title>
<body>{body}</body>

Return as grouped bullet points in Markdown."""
```

#### 4.4.3 Merge Transform
```python
_TRANSFORM_MERGE_PROMPT = """\
You are a Knowledge Synthesizer. Merge the following related notes \
into a single comprehensive knowledge entry.

Rules:
1. Combine all unique information — no data loss
2. Resolve contradictions (prefer the more recent/detailed version)
3. Organize by theme with clear headers
4. De-duplicate overlapping content
5. Keep the original language

Notes to merge:
{notes_xml}

Return the merged content as clean Markdown with a suggested title \
as the first H1 header."""
```

#### 4.4.4 Restructure Transform
```python
_TRANSFORM_RESTRUCTURE_PROMPT = """\
You are a Knowledge Organizer. Restructure the following note for \
maximum clarity and usability.

Rules:
1. Add clear headers and logical sections
2. Convert prose to bullet points where appropriate
3. Format code blocks with language tags
4. Add a brief TL;DR at the top
5. Do NOT add, infer, or change any facts — only reorganize
6. Keep the original language

Original note:
<title>{title}</title>
<body>{body}</body>

Return the restructured content as clean Markdown."""
```

### 4.5 Stage 4: Enrich (자동 보강)

```python
_ENRICH_PROMPT = """\
You are a Knowledge Enricher. Given the following curated note and \
the existing knowledge index, suggest improvements.

<curated_note>
{curated_content}
</curated_note>

<existing_index>
{existing_index_summary}
</existing_index>

Return JSON:
{{
  "auto_tags": ["tag1", "tag2"],          // additional tags to add
  "suggested_links": ["filename.md"],     // wikilinks to establish
  "importance_assessment": "medium",      // recommended importance
  "title_improvement": null,              // or "improved title"
  "missing_context": null                 // or "what additional info would help"
}}"""
```

### 4.6 CuratedKnowledgeManager 전체 설계

```python
class CuratedKnowledgeManager:
    """Per-user curated knowledge vault — 100% Opsidian 호환.

    User Opsidian과 동일한 엔진(StructuredMemoryWriter + MemoryIndexManager)을
    사용하되, VectorMemoryManager를 추가하고, 큐레이션 메타데이터를 확장한다.

    Storage layout:
        {STORAGE_ROOT}/_curated_knowledge/{username}/
            daily/
            topics/
            entities/
            projects/
            insights/
            reference/          ← 추가 카테고리
            vectordb/
                index.faiss
                metadata.json
            _index.json
            _curation_log.jsonl
    """

    def __init__(self, username: str, base_path: Optional[str] = None):
        self.username = username
        self.memory_dir = f"{base_path}/_curated_knowledge/{username}/"

        # ── 기존 엔진 100% 재사용 ──
        self._writer: StructuredMemoryWriter     # 노트 CRUD
        self._index: MemoryIndexManager           # 인덱스 + 그래프
        self._vmm: VectorMemoryManager            # FAISS 벡터 검색 ★추가
        self._curation_log: CurationLog           # 감사 기록

    # ── Curate (핵심 파이프라인) ───────────────────────────────────

    async def curate_from_opsidian(
        self,
        user_opsidian: UserOpsidianManager,
        filename: str,
        *,
        method: str = "auto",         # auto|direct|summary|extract|merge|restructure
        extra_tags: List[str] = [],
        llm_model = None,             # 큐레이션용 LLM (memory_model 활용)
    ) -> CurationResult:
        """5-Stage 큐레이션 파이프라인 실행.

        Returns:
            CurationResult(
                success=True,
                curated_filename="...",
                method_used="summary",
                quality_score=0.82,
                analysis=...,
            )
        """
        # Stage 1: Triage
        note = user_opsidian.read_note(filename)
        triage = CurationTriage.triage(note["metadata"], note["body"])

        if triage["action"] == "exclude":
            return CurationResult(success=False, reason=triage["reason"])

        # Stage 2: LLM Analysis (auto일 때만)
        if method == "auto":
            analysis = await self._llm_analyze(note, llm_model)
            if not analysis["should_curate"]:
                return CurationResult(success=False, reason="LLM decided skip")
            method = analysis["curation_strategy"]
        else:
            analysis = None

        # Stage 3: Transform
        transformed = await self._transform(note, method, analysis, llm_model)

        # Stage 4: Enrich
        enriched = await self._enrich(transformed, analysis, llm_model)

        # Stage 5: Store & Audit
        curated_fn = self._store(enriched, note, method, analysis)
        self._log_curation(filename, curated_fn, method, analysis)

        return CurationResult(
            success=True,
            curated_filename=curated_fn,
            method_used=method,
            quality_score=analysis["quality_score"] if analysis else None,
        )

    async def curate_batch(
        self,
        user_opsidian: UserOpsidianManager,
        filenames: List[str],
        *,
        llm_model = None,
    ) -> List[CurationResult]:
        """여러 노트를 배치 큐레이션 (merge 포함)."""

    async def curate_from_text(
        self,
        title: str,
        content: str,
        *,
        origin: str = "agent_reflect",
        tags: List[str] = [],
        category: str = "insights",
        importance: str = "medium",
    ) -> Optional[str]:
        """Agent reflect 등에서 직접 텍스트로 큐레이팅 노트 생성."""

    # ── Read Operations (Opsidian과 100% 동일한 인터페이스) ─────

    def list_notes(self, *, category=None, tag=None) -> List[Dict]:
        """UserOpsidianManager.list_notes()와 동일한 형식."""

    def read_note(self, filename: str) -> Optional[Dict]:
        """UserOpsidianManager.read_note()와 동일한 형식."""

    def search(self, query: str, max_results: int = 10) -> List[Dict]:
        """키워드 검색 (UserOpsidianManager.search()와 동일)."""

    async def vector_search(self, query: str, top_k: int = 5):
        """FAISS 의미 검색 ★추가."""

    async def hybrid_search(self, query: str, max_results: int = 10) -> List[Dict]:
        """키워드 + 벡터 하이브리드 검색 ★추가.

        두 결과를 RRF(Reciprocal Rank Fusion)로 통합하여
        가장 관련성 높은 노트를 반환한다.
        """

    def get_index(self) -> Optional[Dict]:
        """UserOpsidianManager.get_index()와 동일."""

    def get_stats(self) -> Dict:
        """UserOpsidianManager.get_stats()와 동일."""

    def get_graph(self) -> Dict:
        """UserOpsidianManager.get_graph()와 동일."""

    # ── Curation-specific Operations ──────────────────────────────

    def get_origin_info(self, filename: str) -> Optional[Dict]:
        """큐레이팅 노트의 원본 정보 조회.
        Returns:
            {"origin_file": "...", "origin_scope": "...",
             "curated_at": "...", "curation_method": "...",
             "quality_score": 0.82, "is_stale": False}
        """

    def check_freshness(self, user_opsidian: UserOpsidianManager) -> List[Dict]:
        """원본이 수정된 큐레이팅 노트 감지 (origin_hash 비교)."""

    async def refresh_stale(
        self, user_opsidian: UserOpsidianManager, *, llm_model=None
    ) -> int:
        """stale 노트를 원본에서 재큐레이팅."""

    def get_curation_log(self, limit: int = 50) -> List[Dict]:
        """큐레이션 이력 조회."""

    # ── Write (User UI에서 직접 편집도 가능) ──────────────────────

    def write_note(self, **kwargs) -> Optional[str]:
        """UserOpsidianManager.write_note()와 동일 — 사용자가 큐레이터 뷰에서 직접 편집."""

    def update_note(self, filename, **kwargs) -> bool:
        """UserOpsidianManager.update_note()와 동일."""

    def delete_note(self, filename) -> bool:
        """UserOpsidianManager.delete_note()와 동일."""

    def create_link(self, source, target) -> bool:
        """UserOpsidianManager.create_link()와 동일."""

    def reindex(self) -> int:
        """UserOpsidianManager.reindex()와 동일."""
```

### 4.7 큐레이션 트리거 체계

| 트리거 | 시점 | 방식 |
|--------|------|------|
| **자동 — 노트 CUD** | User Opsidian 노트 생성/수정 시 | `user_opsidian_controller.py`에 비동기 훅 |
| **자동 — Agent 반성** | `MemoryReflectNode` 실행 후 | 인사이트 노트를 curated에 promote |
| **수동 — UI 큐레이트** | 사용자가 User Opsidian에서 버튼 클릭 | 방법 선택 다이얼로그 → API 호출 |
| **수동 — API** | REST API 직접 호출 | `POST /api/knowledge/curate` |
| **배치 — 전체 재큐레이션** | 관리자 수동 트리거 | `POST /api/knowledge/refresh` |
| **배치 — Freshness 체크** | 주기적 (옵션) | 원본 변경된 노트 재큐레이팅 |

### 4.8 큐레이션 결과 데이터 모델

```python
@dataclass
class CurationResult:
    success: bool
    curated_filename: Optional[str] = None
    method_used: Optional[str] = None     # direct|summary|extract|merge|restructure
    quality_score: Optional[float] = None  # 0.0~1.0
    analysis: Optional[Dict] = None        # Stage 2 LLM analysis 전문
    reason: Optional[str] = None           # 실패 시 사유

@dataclass
class CurationLogEntry:
    timestamp: str
    action: str                            # curate|refresh|delete|merge
    source_file: str                       # 원본 파일
    source_scope: str                      # user_opsidian|session|agent_reflect
    curated_file: Optional[str]
    method: str
    quality_score: Optional[float]
    llm_tokens_used: int
```

---

## 5. 완전 호환 Opsidian 시스템

### 5.1 프론트엔드 3-Tab 전환 설계

#### 5.1.1 HubMode 확장

```typescript
// OpsidianHubContext.tsx
export type HubMode = 'user' | 'curator' | 'sessions';  // ← 'curator' 추가

interface HubContextValue {
  mode: HubMode;
  setMode: (m: HubMode) => void;
  refreshRef: MutableRefObject<() => void>;
}
```

#### 5.1.2 OpsidianHub 확장

```typescript
// OpsidianHub.tsx
export default function OpsidianHub() {
  const [mode, setMode] = useState<HubMode>('user');
  const refreshRef = useRef<() => void>(() => {});
  const ctx = useMemo(() => ({ mode, setMode, refreshRef }), [mode]);

  return (
    <HubContext.Provider value={ctx}>
      <div className="opsidian-hub">
        <div className="opsidian-hub-content">
          {mode === 'user' && <UserOpsidianView />}
          {mode === 'curator' && <CuratedKnowledgeView />}     {/* ★ 신규 */}
          {mode === 'sessions' && <ObsidianView />}
        </div>
        <StatusBar onRefresh={() => refreshRef.current()} />
      </div>
    </HubContext.Provider>
  );
}
```

#### 5.1.3 StatusBar 3-Tab

```typescript
// StatusBar.tsx  — 3개 탭 버튼
{hub && (
  <div className="obs-hub-nav">
    <button
      className={`obs-hub-nav-btn ${hub.mode === 'user' ? 'obs-hub-nav-active' : ''}`}
      onClick={() => hub.setMode('user')}
    >
      {t('opsidian.userVault')}       {/* "사용자" */}
    </button>
    <button
      className={`obs-hub-nav-btn ${hub.mode === 'curator' ? 'obs-hub-nav-active' : ''}`}
      onClick={() => hub.setMode('curator')}
    >
      {t('opsidian.curatorVault')}    {/* ★ "큐레이터" */}
    </button>
    <button
      className={`obs-hub-nav-btn ${hub.mode === 'sessions' ? 'obs-hub-nav-active' : ''}`}
      onClick={() => hub.setMode('sessions')}
    >
      {t('opsidian.sessionsVault')}   {/* "세션" */}
    </button>
  </div>
)}
```

StatusBar 통계 데이터는 3개 스토어 중 활성 모드에 맞춰 전환:
```typescript
const isCuratorMode = hub?.mode === 'curator';  // ★ 추가
const isUserMode = hub?.mode === 'user';

const totalFiles = isUserMode
  ? userStore.stats?.total_files ?? 0
  : isCuratorMode
    ? curatorStore.stats?.total_files ?? 0       // ★ 추가
    : obsidian.memoryStats?.total_files ?? 0;
// ... 나머지 통계도 동일 패턴
```

### 5.2 CuratedKnowledgeView — UserOpsidianView 패턴 100% 재사용

`CuratedKnowledgeView`는 `UserOpsidianView`의 구조를 **그대로 복제**하되, 큐레이션 전용 기능을 추가한다:

```
CuratedKnowledgeView (신규, ~1200줄 예상)
├── Sidebar (동일 패턴)
│   ├─ 파일 / 태그 / 링크 탭
│   ├─ 카테고리 / 그래프 / 검색 뷰
│   └─ ★ 큐레이션 히스토리 탭 (추가)
├── NoteEditor (동일 + 큐레이션 메타 표시)
│   ├─ 편집/저장/삭제 (동일)
│   ├─ ★ 원본 정보 배지 (origin_file, curation_method)
│   ├─ ★ Freshness 상태 (✅ fresh / ⚠️ stale)
│   └─ ★ 품질 점수 표시 (quality_score)
├── GraphViewer (동일 SVG 그래프)
├── SearchView (동일 + 벡터 검색 옵션)
├── CreateNoteModal (동일 + 큐레이션 필드)
│   └── ★ "User Opsidian에서 가져오기" 버튼
└── ★ CurationPanel (신규)
    ├─ 큐레이션 대기 목록 (User Opsidian 후보)
    ├─ 큐레이션 방법 선택 (auto/direct/summary/extract/merge)
    └─ 큐레이션 실행 버튼
```

### 5.3 useCuratedKnowledgeStore — useUserOpsidianStore 패턴 100% 동일

```typescript
interface CuratedKnowledgeState {
  // ── UserOpsidianStore와 동일한 필드 ──
  username: string;
  memoryIndex: MemoryIndex | null;
  stats: MemoryStats | null;
  files: MemoryFileInfo[];
  selectedFile: string | null;
  fileDetail: MemoryFileDetail | null;
  openFiles: Array<{ filename: string; title: string }>;
  graphNodes: MemoryGraphNode[];
  graphEdges: MemoryGraphEdge[];
  searchQuery: string;
  searchResults: MemorySearchResult[];
  searchLoading: boolean;
  loading: boolean;
  error: string | null;
  viewMode: 'category' | 'graph' | 'search';
  sidebarPanel: 'files' | 'tags' | 'links';
  sidebarCollapsed: boolean;
  rightPanelOpen: boolean;

  // ── 큐레이션 전용 필드 (추가) ──
  curationCandidates: CurationCandidate[];    // User Opsidian 큐레이션 후보
  curationHistory: CurationLogEntry[];        // 큐레이션 이력
  curationInProgress: boolean;                // 큐레이션 실행 중
  stalenessReport: StaleNote[];               // stale 노트 목록
}
```

### 5.4 REST API — `/api/knowledge/*` (User Opsidian API와 완전 동일 패턴)

```
# ── 기본 CRUD (User Opsidian과 동일 구조) ──
GET    /api/knowledge                          ← 인덱스
GET    /api/knowledge/stats                    ← 통계
GET    /api/knowledge/graph                    ← 그래프
GET    /api/knowledge/tags                     ← 태그 목록
GET    /api/knowledge/files                    ← 파일 목록 (필터링)
GET    /api/knowledge/files/{filename}         ← 파일 읽기
POST   /api/knowledge/files                    ← 파일 생성 (직접 편집)
PUT    /api/knowledge/files/{filename}         ← 파일 수정
DELETE /api/knowledge/files/{filename}         ← 파일 삭제
GET    /api/knowledge/search?q=                ← 검색

# ── 큐레이션 전용 (추가) ──
POST   /api/knowledge/curate                   ← 큐레이션 실행
  body: { source_filename, source_scope?, method?, extra_tags? }
POST   /api/knowledge/curate/batch             ← 배치 큐레이션
  body: { filenames: [...], method? }
GET    /api/knowledge/curation-log             ← 큐레이션 이력
GET    /api/knowledge/staleness                ← stale 노트 감지
POST   /api/knowledge/refresh                  ← stale 노트 재큐레이팅
POST   /api/knowledge/links                    ← 링크 생성
POST   /api/knowledge/reindex                  ← 인덱스 재구축
```

### 5.5 User Opsidian UI에 "Curate" 버튼 추가

User Opsidian의 NoteEditor에 큐레이션 버튼을 추가한다:

```
┌─────────────────────────────────────────────────────────────┐
│  FastAPI 비동기 패턴                                         │
│  ─────────────────────────────────────────────────────────── │
│  [편집] [저장] [삭제]  ......  [★ Curate ▾]                  │
│                                   ├─ 자동 분석 후 큐레이팅    │
│                                   ├─ 원본 그대로 복사         │
│                                   ├─ 요약하여 큐레이팅        │
│                                   ├─ 핵심만 추출              │
│                                   └─ 구조 재편                │
│  ─────────────────────────────────────────────────────────── │
│  # FastAPI 비동기 패턴                                       │
│  ...                                                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. Agent 통합 설계

### 6.1 Agent 도구 4개

#### 6.1.1 knowledge_search — 큐레이팅 지식 검색

```python
class KnowledgeSearchTool(BaseTool):
    name = "knowledge_search"
    description = (
        "Search the user's curated knowledge base. Contains refined, "
        "verified information — summaries, key facts, and organized "
        "knowledge extracted from the user's personal notes. "
        "This is your PRIMARY source for user-specific knowledge. "
        "Use this before falling back to user_doc_browse."
    )

    parameters_schema = {
        "query": {"type": "string", "description": "Search query", "required": True},
        "max_results": {"type": "integer", "default": 10, "description": "Max results"},
        "search_type": {
            "type": "string", "default": "hybrid",
            "enum": ["keyword", "vector", "hybrid"],
            "description": "Search strategy"
        },
    }

    async def _execute(self, session_id: str, query: str, **kwargs) -> str:
        mgr = self._get_curated_manager()
        search_type = kwargs.get("search_type", "hybrid")

        if search_type == "hybrid":
            results = await mgr.hybrid_search(query, max_results)
        elif search_type == "vector":
            results = await mgr.vector_search(query, top_k=max_results)
        else:
            results = mgr.search(query, max_results)

        return self._format_results(results)
```

#### 6.1.2 knowledge_read — 큐레이팅 노트 읽기

```python
class KnowledgeReadTool(BaseTool):
    name = "knowledge_read"
    description = "Read a specific curated knowledge note by filename."

    parameters_schema = {
        "filename": {"type": "string", "required": True},
    }
```

#### 6.1.3 knowledge_list — 큐레이팅 목록 조회

```python
class KnowledgeListTool(BaseTool):
    name = "knowledge_list"
    description = "List curated knowledge notes, optionally filtered by category or tag."

    parameters_schema = {
        "category": {"type": "string", "default": ""},
        "tag": {"type": "string", "default": ""},
    }
```

#### 6.1.4 user_doc_browse — User Opsidian 인덱스 전용 열람

```python
class UserDocBrowseTool(BaseTool):
    name = "user_doc_browse"
    description = (
        "Browse the user's raw personal Opsidian vault. Returns ONLY "
        "the index (titles, tags, categories) by default — NOT full content. "
        "If you find a note that looks relevant, use read_filename to "
        "get its full content. Use this ONLY when curated knowledge "
        "doesn't have what you need."
    )

    parameters_schema = {
        "query": {"type": "string", "default": "", "description": "Search in index"},
        "read_filename": {"type": "string", "default": "", "description": "Read specific note raw content"},
        "category": {"type": "string", "default": ""},
        "tag": {"type": "string", "default": ""},
    }

    async def _execute(self, session_id: str, **kwargs) -> str:
        mgr = self._get_user_opsidian_manager()
        read_fn = kwargs.get("read_filename", "")

        if read_fn:
            # Opt-in raw read — 특정 노트 본문 반환
            note = mgr.read_note(read_fn)
            return self._format_note(note)

        # 기본: 인덱스만 반환 (본문 없음)
        query = kwargs.get("query", "")
        if query:
            results = mgr.search(query, max_results=20)
            # 본문(snippet) 제거 — 메타데이터만 반환
            for r in results:
                r.pop("snippet", None)
            return self._format_index_results(results)

        notes = mgr.list_notes(
            category=kwargs.get("category") or None,
            tag=kwargs.get("tag") or None,
        )
        return self._format_note_list(notes)
```

**설계 의도**: Agent가 User Opsidian의 **full body를 무분별하게 가져오는 것을 방지**한다. 기본은 메타데이터(제목, 태그, 카테고리, 중요도)만 반환하고, Agent가 "이 노트가 필요하다"고 명시적으로 판단한 경우에만 `read_filename`으로 본문에 접근한다.

### 6.2 Agent 우선순위 체계

```
Agent 정보 탐색 순서:

  1. Session Memory (memory_*)      → 현재 세션 맥락
  2. Curated Knowledge (knowledge_*) → 사용자의 정제된 지식 ★
  3. Global Memory (기존)             → 크로스 세션 공유 지식
  4. User Opsidian (user_doc_browse) → Raw 화이트보드 (인덱스 우선) ★
```

### 6.3 MemoryInjectNode 확장 — 6-7단계 추가

기존 5단계 파이프라인 후에:

```python
# ── 6. Curated Knowledge 벡터 검색 ────────────────────────────
curated_mgr = context.curated_knowledge_manager
curated_budget = int(budget * 0.30)          # 전체 예산의 30%

if curated_mgr and (budget - total_chars) > 200:
    try:
        curated_results = await curated_mgr.hybrid_search(
            query, max_results=max_results
        )
        for cr in curated_results:
            chunk = (
                f'<curated-knowledge source="{cr["filename"]}" '
                f'score="{cr.get("score", 0):.2f}" '
                f'origin="{cr.get("origin_file", "")}">\n'
                f'{cr.get("snippet", "")}\n'
                f'</curated-knowledge>'
            )
            if (total_chars + len(chunk)) > budget:
                break
            parts.append(chunk)
            total_chars += len(chunk)
            refs.append({
                "filename": cr["filename"],
                "source": "curated_knowledge",
                "char_count": len(cr.get("snippet", "")),
                "injected_at_turn": 0,
            })
    except Exception:
        pass

# ── 7. Cross-scope Backlink 탐색 (session + curated 통합) ────
remaining = budget - total_chars
if remaining > 200 and refs:
    try:
        # 기존 session backlinks + curated backlinks 통합
        linked_text = self._add_linked_context(
            refs, mgr, remaining // 2        # session scope
        )
        if linked_text:
            parts.append(linked_text)
            total_chars += len(linked_text)

        if curated_mgr and (budget - total_chars) > 200:
            curated_linked = self._add_linked_context(
                refs, curated_mgr, budget - total_chars   # curated scope
            )
            if curated_linked:
                parts.append(curated_linked)
                total_chars += len(curated_linked)
    except Exception:
        pass
```

### 6.4 MemoryReflectNode 확장 — Curated Knowledge Promote

```python
# memory_reflect_node.py — 인사이트 저장 후 추가

# ★ 고품질 인사이트는 Curated Knowledge에도 promote
curated_mgr = context.curated_knowledge_manager
if curated_mgr and item.importance in ("high", "critical"):
    try:
        await curated_mgr.curate_from_text(
            title=f"Agent Insight: {item.title}",
            content=item.content,
            origin="agent_reflect",
            tags=["agent-generated", "auto-insight"] + (item.tags or []),
            category="insights",
            importance=item.importance,
        )
    except Exception:
        pass
```

### 6.5 ExecutionContext + AgentSession 확장

```python
# service/workflow/nodes/base.py
@dataclass
class ExecutionContext:
    ...
    curated_knowledge_manager: Any = None   # ★ 추가
    user_opsidian_manager: Any = None       # ★ 추가
    owner_username: Optional[str] = None    # ★ 추가

# service/langgraph/agent_session.py
class AgentSession:
    def __init__(
        self,
        ...
        owner_username: Optional[str] = None,  # ★ 추가
    ):
        ...
        self._owner_username = owner_username
```

---

## 7. 최종 구현 계획

### Phase 1: 기반 인프라 (필수 선행)

| # | 작업 | 파일 | 난이도 |
|---|------|------|--------|
| 1.1 | AgentSession에 `owner_username` 추가 | `agent_session.py` | 🟢 |
| 1.2 | ExecutionContext에 3필드 추가 | `base.py` | 🟢 |
| 1.3 | agent_controller에서 username 전달 | `agent_controller.py` | 🟢 |
| 1.4 | LTMConfig에 curated_* / user_opsidian_* 설정 추가 | `ltm_config.py` | 🟢 |

### Phase 2: CuratedKnowledgeManager 핵심 구현

| # | 작업 | 파일 | 난이도 |
|---|------|------|--------|
| 2.1 | `CuratedKnowledgeManager` 클래스 (기존 엔진 재사용) | `curated_knowledge.py` ★신규 | 🟡 |
| 2.2 | CRUD + search + index + graph (UserOpsidianManager 동일) | (동일 파일) | 🟡 |
| 2.3 | VectorMemoryManager 통합 (큐레이팅 볼트용 FAISS) | (동일 파일) | 🟡 |
| 2.4 | `get_curated_knowledge_manager()` 싱글턴 캐시 | (동일 파일) | 🟢 |

### Phase 3: 큐레이션 엔진 고도화

| # | 작업 | 파일 | 난이도 |
|---|------|------|--------|
| 3.1 | `CurationTriage` — 규칙 기반 필터링 | `curation_engine.py` ★신규 | 🟢 |
| 3.2 | Stage 2: LLM Analysis (품질 평가 + 전략 결정) | (동일 파일) | 🔴 |
| 3.3 | Stage 3: Transform (5가지 변환 전략 + LLM 프롬프트) | (동일 파일) | 🔴 |
| 3.4 | Stage 4: Enrich (자동 태그, 링크, 벡터 인덱싱) | (동일 파일) | 🟡 |
| 3.5 | Stage 5: Store & Audit (저장 + 감사 로그) | (동일 파일) | 🟡 |
| 3.6 | Merge 전략 (관련 노트 통합) | (동일 파일) | 🔴 |
| 3.7 | Freshness 체크 + 자동 재큐레이팅 | (동일 파일) | 🟡 |

### Phase 4: Agent 도구 + 워크플로우 노드

| # | 작업 | 파일 | 난이도 |
|---|------|------|--------|
| 4.1 | `knowledge_search` / `knowledge_read` / `knowledge_list` | `knowledge_tools.py` ★신규 | 🟡 |
| 4.2 | `user_doc_browse` (인덱스 우선 + opt-in raw) | (동일 파일) | 🟡 |
| 4.3 | MemoryInjectNode 6-7단계 확장 | `memory_inject_node.py` | 🟡 |
| 4.4 | MemoryReflectNode curated promote | `memory_reflect_node.py` | 🟢 |
| 4.5 | UserOpsidianManager에 인덱스 전용 경량 메서드 추가 | `user_opsidian.py` | 🟢 |

### Phase 5: 백엔드 API + 컨트롤러

| # | 작업 | 파일 | 난이도 |
|---|------|------|--------|
| 5.1 | `curated_knowledge_controller.py` (CRUD + 큐레이션 API) | ★신규 | 🟡 |
| 5.2 | `user_opsidian_controller.py`에 자동 큐레이션 훅 추가 | 수정 | 🟢 |
| 5.3 | `main.py`에 라우터 등록 | 수정 | 🟢 |

### Phase 6: 프론트엔드 3-Tab UI

| # | 작업 | 파일 | 난이도 |
|---|------|------|--------|
| 6.1 | HubMode에 'curator' 추가 | `OpsidianHubContext.tsx` | 🟢 |
| 6.2 | OpsidianHub에 CuratedKnowledgeView 렌더링 | `OpsidianHub.tsx` | 🟢 |
| 6.3 | StatusBar 3-Tab + 3-Store 전환 | `StatusBar.tsx` | 🟡 |
| 6.4 | RightPanel 3-Mode 확장 | `RightPanel.tsx` | 🟡 |
| 6.5 | `useCuratedKnowledgeStore` (useUserOpsidianStore 기반) | ★신규 | 🟡 |
| 6.6 | `curatedKnowledgeApi` (userOpsidianApi 기반) | `api.ts` | 🟢 |
| 6.7 | `CuratedKnowledgeView` (UserOpsidianView 기반) | ★신규 | 🔴 |
| 6.8 | UserOpsidianView에 Curate 버튼 | 수정 | 🟡 |
| 6.9 | i18n 키 추가 (ko.ts, en.ts) | 수정 | 🟢 |

### Phase 7: 통합 테스트 + 최적화

| # | 작업 | 난이도 |
|---|------|--------|
| 7.1 | E2E: User Opsidian → 큐레이션 → Agent 사용 흐름 검증 | 🟡 |
| 7.2 | 성능: FAISS 인덱스 lazy init, 큐레이션 배치 처리 | 🟡 |
| 7.3 | 보안: username 격리 검증, read-only 도구 검증 | 🟡 |

---

## 8. 파일별 변경 사항

### 8.1 백엔드 (16 파일)

| # | 파일 | 유형 | 내용 |
|---|------|------|------|
| 1 | `service/memory/curated_knowledge.py` | **신규** | CuratedKnowledgeManager (Opsidian 100% 호환) |
| 2 | `service/memory/curation_engine.py` | **신규** | 5-Stage 큐레이션 엔진 (Triage, LLM Analysis, Transform, Enrich, Store) |
| 3 | `tools/built_in/knowledge_tools.py` | **신규** | knowledge_search/read/list + user_doc_browse |
| 4 | `controller/curated_knowledge_controller.py` | **신규** | `/api/knowledge/*` REST API |
| 5 | `service/langgraph/agent_session.py` | **수정** | `owner_username` 파라미터 + property |
| 6 | `service/workflow/nodes/base.py` | **수정** | ExecutionContext +3 필드 |
| 7 | `service/workflow/nodes/memory/memory_inject_node.py` | **수정** | 6-7단계 curated 검색 |
| 8 | `service/workflow/nodes/memory/memory_reflect_node.py` | **수정** | curated promote |
| 9 | `service/config/sub_config/general/ltm_config.py` | **수정** | curated_* 설정 |
| 10 | `controller/agent_controller.py` | **수정** | username 전달 |
| 11 | `controller/user_opsidian_controller.py` | **수정** | 자동 큐레이션 훅 |
| 12 | `service/langgraph/state.py` | **수정** | MemoryRef.source에 curated_knowledge 타입 |
| 13 | `service/memory/user_opsidian.py` | **수정** | 인덱스 전용 경량 조회 |
| 14 | `service/memory/__init__.py` | **수정** | CuratedKnowledgeManager export |
| 15 | `main.py` | **수정** | curated_knowledge_router 등록 |
| 16 | `prompts/` | **신규** | 큐레이션 LLM 프롬프트 파일들 (선택) |

### 8.2 프론트엔드 (10 파일)

| # | 파일 | 유형 | 내용 |
|---|------|------|------|
| 17 | `components/curated-knowledge/CuratedKnowledgeView.tsx` | **신규** | 큐레이터 뷰 (~1200줄) |
| 18 | `store/useCuratedKnowledgeStore.ts` | **신규** | Zustand 스토어 |
| 19 | `components/OpsidianHubContext.tsx` | **수정** | HubMode + 'curator' |
| 20 | `components/OpsidianHub.tsx` | **수정** | 3-way 모드 전환 |
| 21 | `components/obsidian/StatusBar.tsx` | **수정** | 3-Tab + 3-Store |
| 22 | `components/obsidian/RightPanel.tsx` | **수정** | curator 모드 데이터 |
| 23 | `components/user-opsidian/UserOpsidianView.tsx` | **수정** | Curate 버튼 |
| 24 | `lib/api.ts` | **수정** | curatedKnowledgeApi |
| 25 | `lib/i18n/ko.ts` | **수정** | curatorVault + 큐레이션 UI 키 |
| 26 | `lib/i18n/en.ts` | **수정** | 동일 |

---

## 9. 보안·성능·운영

### 9.1 접근 제어

```
                      Session   Curated    User Opsidian   Global
                      Memory    Knowledge  (Raw)           Memory
──────────────────    ────────  ─────────  ──────────────  ────────
Agent 검색/읽기        ✅        ✅          📋 인덱스만*   ✅
Agent 쓰기            ✅        ❌          ❌              promote만
Agent 삭제            ✅        ❌          ❌              ❌
User UI 전체 CRUD     ✅        ✅          ✅              ✅
Curator 파이프라인     ─         ✅ (쓰기)   ✅ (읽기)       ─
```
\* `user_opsidian_raw_read_enabled` 시 Agent가 특정 노트 raw 본문도 읽기 가능

### 9.2 예산 분배

```
MemoryInjectNode max_inject_chars (기본 10,000자):

  세션 메모리         : 55% (5,500자) — summary, MEMORY.md, vector, keyword
  큐레이팅 지식       : 30% (3,000자) — hybrid search (vector + keyword)
  글로벌 메모리       : 5%  (500자)   — inject_context
  백링크             : 10% (1,000자) — session + curated 통합
  ──────────────────────────────────────────────────────
  합계               : 100% (10,000자)
```

### 9.3 성능 최적화

| 최적화 | 설명 |
|--------|------|
| **Lazy Init** | CuratedKnowledgeManager의 FAISS는 첫 검색 시에만 로드 |
| **싱글턴 캐시** | `_curated_managers[username]` — 동일 유저 재생성 방지 |
| **비동기 큐레이션** | 자동 큐레이션은 `asyncio.create_task()`로 요청과 분리 |
| **배치 큐레이션** | 여러 노트를 한 번에 분석하여 LLM 호출 최소화 |
| **Index 캐시** | `MemoryIndexManager`의 `_index.json` 메모리 캐시 재사용 |
| **Hybrid Search RRF** | 벡터+키워드 결과를 Reciprocal Rank Fusion으로 통합 |
| **Freshness Hash** | SHA256 비교로 원본 변경 감지 (전체 비교 불필요) |

### 9.4 운영 모니터링

```python
# _curation_log.jsonl 엔트리 예시
{
    "timestamp": "2026-04-05T10:00:00+09:00",
    "action": "curate",
    "source_file": "fastapi-async-notes.md",
    "source_scope": "user_opsidian",
    "curated_file": "fastapi-async-patterns-curated.md",
    "method": "summary",
    "quality_score": 0.82,
    "quality_dimensions": { ... },
    "llm_tokens_used": 1247,
    "duration_ms": 3200,
    "triage_result": "auto_curate",
    "username": "gkfua"
}
```

---

## 부록 A: 전체 아키텍처 Before/After

### Before (현재)
```
┌─────────┐   CRUD    ┌──────────────────┐
│  User   │──────────→│  User Opsidian   │  ❌ Agent 접근 불가
└─────────┘           └──────────────────┘

┌─────────┐ memory_*  ┌──────────────────┐
│  Agent  │──────────→│  Session Memory  │  (유일한 지식원)
└─────────┘           └──────────────────┘

StatusBar: [사용자] [세션]
```

### After (변경 후)
```
┌─────────┐   CRUD     ┌──────────────────┐
│  User   │──────────→ │  User Opsidian   │
└─────────┘  Curate▾   │  (화이트보드)      │
                │       └────────┬─────────┘
                │                │ 5-Stage Curator
                │                ▼
                │       ┌──────────────────────┐
                │       │  Curated Knowledge    │  ← FAISS + Hybrid Search
                │       │  (정제된 지식)         │
                │       └────────┬─────────────┘
                │                │
                │    ┌───────────┼───────────────────────┐
                │    │           │                       │
                ▼    ▼           ▼                       ▼
┌─────────┐   ┌───────────┐  ┌────────────┐   ┌──────────────┐
│  Agent  │←─→│knowledge_*│  │InjectNode  │   │user_doc_     │
└─────────┘   │(검색+읽기)│  │(자동 주입)  │   │browse        │
    │         └───────────┘  └────────────┘   │(인덱스+opt-in)│
    │                                          └──────────────┘
    │ memory_*                                        │
    ▼                                                 ▼
┌──────────────────┐                     ┌──────────────────┐
│  Session Memory  │                     │  User Opsidian   │
└──────────────────┘                     │  (raw 열람)      │
                                         └──────────────────┘

StatusBar: [사용자] [큐레이터] [세션]
```

---

## 부록 B: Agent 능력 비교

| 시나리오 | Before | After |
|---------|--------|-------|
| "내 FastAPI 패턴 노트 참고해줘" | ❌ "기억에 없습니다" | ✅ knowledge_search → 큐레이팅된 요약 반환 |
| "지난주 프로젝트 계획 이어서" | ❌ 세션 밖이면 불가 | ✅ InjectNode가 큐레이팅 프로젝트 정보 자동 주입 |
| 사용자 메모 100개 (잡다한 것 포함) | ❌ 접근 불가 | ✅ 큐레이션 통과한 20개만 Agent 사용 → 노이즈 80% 차단 |
| "내 노트 Python 관련 있었지?" | ❌ 불가 | ✅ user_doc_browse → 인덱스에서 Python 태그 노트 목록 |
| Agent가 고품질 인사이트 발견 | 세션 메모리에만 저장 | ✅ ReflectNode → Curated에 promote → 영구 축적 |
| LLM Gate "메모리 필요" 판단 | 세션만 검색 | ✅ 세션 + 큐레이팅 동시 검색 → 2배 풍부한 컨텍스트 |
| 초안/미완성 메모 대량 존재 | ❌ 접근 불가 | ✅ Triage에서 draft 자동 제외 → 환각 방지 |
| 관련 메모 여러 개 흩어져 있음 | ❌ | ✅ Merge 전략으로 하나의 통합 노트 생성 |

---

## 부록 C: 구현 의존성 그래프

```
Phase 1 (기반)
  ├─ AgentSession.owner_username
  ├─ ExecutionContext +3 fields
  ├─ agent_controller username relay
  └─ LTMConfig curated_* settings
        │
Phase 2 (핵심 Manager)
  └─ CuratedKnowledgeManager
     ├─ StructuredMemoryWriter (기존 재사용)
     ├─ MemoryIndexManager     (기존 재사용)
     └─ VectorMemoryManager    (기존 재사용)
            │
Phase 3 (큐레이션 엔진)          Phase 4 (Agent 도구)
  ├─ CurationTriage              ├─ knowledge_search/read/list
  ├─ LLM Analysis                ├─ user_doc_browse
  ├─ 5 Transform 전략             ├─ MemoryInjectNode +2단계
  ├─ Enrich                      └─ MemoryReflectNode promote
  └─ Merge / Freshness
            │                           │
Phase 5 (API)                   Phase 6 (프론트엔드)
  ├─ curated_knowledge_controller   ├─ HubMode + 'curator'
  ├─ user_opsidian auto hook        ├─ 3-Tab StatusBar
  └─ main.py router                 ├─ CuratedKnowledgeView
                                    ├─ useCuratedKnowledgeStore
                                    └─ Curate 버튼 (User Opsidian)
                                           │
                                    Phase 7 (검증)
                                      └─ E2E Test + 성능 + 보안
```

---

## 부록 D: 설정 키 전체 목록 (LTMConfig 확장)

```python
# ── Curated Knowledge ──
curated_knowledge_enabled: bool = False       # 큐레이터 시스템 활성화
curated_vector_enabled: bool = True           # 큐레이터 벡터 검색
curated_inject_budget: int = 3000             # InjectNode 문자 예산
curated_max_results: int = 5                  # 검색 최대 결과

# ── Auto-Curation ──
auto_curation_enabled: bool = True            # 자동 큐레이션 파이프라인
auto_curation_method: str = "auto"            # auto|direct|summary|extract
auto_curation_importance_threshold: str = "high"
auto_curation_use_llm: bool = True            # LLM 분석 단계 사용
auto_curation_quality_threshold: float = 0.5  # LLM 품질 최소값

# ── User Opsidian Agent Access ──
user_opsidian_index_enabled: bool = True      # Agent에 인덱스 열람 허용
user_opsidian_raw_read_enabled: bool = True   # Agent에 raw 본문 요청 허용
```
