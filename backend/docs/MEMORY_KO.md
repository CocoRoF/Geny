# Memory System

> 장기 메모리(LTM) + 단기 메모리(STM) + FAISS 벡터 검색을 결합한 세션별 기억 시스템

## 아키텍처 개요

```
SessionMemoryManager (통합 파사드)
        │
        ├── LongTermMemory       ── Markdown 파일 + DB
        │     └── MEMORY.md, 날짜별.md, topics/*.md
        │
        ├── ShortTermMemory      ── JSONL 트랜스크립트 + DB
        │     └── session.jsonl, summary.md
        │
        └── VectorMemoryManager  ── FAISS + Embedding API
              ├── SessionVectorStore (IndexFlatIP)
              └── EmbeddingProvider (OpenAI / Google / Voyage)
```

모든 쓰기는 **파일 + DB 이중 기록**, 읽기는 **DB 우선 → 파일 폴백**.

---

## 장기 메모리 (LongTermMemory)

세션 간 지속되는 Markdown 파일 기반 지식 저장소.

### 저장소 레이아웃

```
{storage_path}/memory/
├── MEMORY.md                # 주 메모리 파일 (append-only)
├── 2026-03-21.md            # 날짜별 실행 기록
├── 2026-03-20.md
└── topics/
    ├── python-basics.md     # 토픽별 지식
    └── api-design.md
```

### 메서드

| 메서드 | 설명 |
|--------|------|
| `append(text, heading=None)` | MEMORY.md에 KST 타임스탬프와 함께 추가 |
| `write_dated(text, date=None)` | 날짜별 파일에 기록 (기본: 오늘) |
| `write_topic(topic, text)` | `topics/{slug}.md`에 기록 |
| `load_all()` | 모든 .md 파일 로드 (DB 우선) |
| `load_main()` | MEMORY.md만 로드 |
| `search(query, max_results=5)` | 키워드 검색 (밀도 + 최신성 점수화) |

### 검색 채점

```python
score = keyword_density * 0.7 + recency * 0.3
```

파일 최대 인덱싱 크기: 256 KB.

---

## 단기 메모리 (ShortTermMemory)

세션 내 대화 트랜스크립트. JSONL 형식.

### 저장소 레이아웃

```
{storage_path}/transcripts/
├── session.jsonl            # 대화 기록 (최대 2000라인)
└── summary.md               # 세션 요약
```

### JSONL 형식

```json
{"type": "message", "role": "user", "content": "...", "ts": "2026-03-21T15:30:00"}
{"type": "message", "role": "assistant", "content": "...", "ts": "..."}
{"type": "event", "event": "tool_call", "data": {"name": "web_search", "args": {...}}, "ts": "..."}
```

### 메서드

| 메서드 | 설명 |
|--------|------|
| `add_message(role, content, metadata)` | 메시지 추가 |
| `add_event(event, data)` | 이벤트 기록 |
| `write_summary(summary)` | 세션 요약 작성/덮어쓰기 |
| `load_all()` | 전체 트랜스크립트 (요약 제외) |
| `get_recent(n=20)` | 최근 N개 메시지 |
| `get_summary()` | 세션 요약 로드 |
| `search(query, max_results=10)` | 키워드 검색 + 최신성 부스트 |
| `message_count()` | 총 메시지 수 |

---

## 벡터 메모리 (FAISS)

의미 기반 유사도 검색. 장기 메모리 파일을 청킹하여 임베딩 → FAISS 인덱스 저장.

### 저장소 레이아웃

```
{storage_path}/vectordb/
├── index.faiss              # FAISS 인덱스 (IndexFlatIP)
└── metadata.json            # 청크 메타데이터
```

### Embedding Provider

설정: `LTMConfig` (Config System의 `ltm` 그룹)

| Provider | 모델 | 차원 |
|----------|------|------|
| **OpenAI** | `text-embedding-3-small` | 1536 |
| | `text-embedding-3-large` | 3072 |
| | `ada-002` | 1536 |
| **Google** | `text-embedding-004` | 768 |
| | `embedding-001` | 768 |
| **Voyage AI** | `voyage-3-large` | 1024 |
| | `voyage-3` | 1024 |
| | `voyage-3-lite` | 512 |
| | `voyage-code-3` | 1024 |

배치 크기: 요청당 96개. `httpx.AsyncClient` 사용.

### LTM 설정값

| 설정 | 기본값 | 설명 |
|------|--------|------|
| `enabled` | `false` | 벡터 메모리 활성화 여부 |
| `embedding_provider` | `"openai"` | 임베딩 제공자 |
| `embedding_model` | `"text-embedding-3-small"` | 모델 |
| `embedding_api_key` | `""` | API 키 |
| `chunk_size` | `1024` | 청크 크기 (문자) |
| `chunk_overlap` | `256` | 청크 겹침 (문자) |
| `top_k` | `6` | 검색 결과 수 |
| `score_threshold` | `0.35` | 최소 유사도 점수 |
| `max_inject_chars` | `10000` | 프롬프트 주입 최대 문자 |

### SessionVectorStore

FAISS `IndexFlatIP` (L2 정규화 벡터 = 코사인 유사도) 기반.

| 메서드 | 설명 |
|--------|------|
| `load_or_create()` | 디스크에서 로드 또는 새로 생성 (차원 검증) |
| `save()` | `index.faiss` + `metadata.json` 저장 |
| `add_chunks(texts, vectors, source_file, ...)` | 청크 추가 (중복 제거) |
| `remove_source(source_file)` | 소스 파일의 청크 제거 |
| `search(query_vector, top_k=5, score_threshold=0.0)` | 코사인 유사도 검색 |

### 텍스트 청킹

```python
chunk_text(text, chunk_size=512, chunk_overlap=64)
```

분할 우선순위: 문단(`\n\n`) → 문장(`.!?`) → 줄(`\n`) 경계. 겹침으로 문맥 유지.

### VectorMemoryManager

FAISS 인덱싱 + 검색 조정자.

| 메서드 | 설명 |
|--------|------|
| `initialize()` | 설정 로드, 임베딩 제공자 + 벡터 저장소 생성 |
| `index_memory_files()` | `memory/*.md` 스캔 → 청킹 → 임베딩 → FAISS 업서트 |
| `index_text(text, source_file, replace=False)` | 단일 텍스트 인덱싱 |
| `search(query, top_k, score_threshold)` | 쿼리 임베딩 → FAISS 검색 |
| `build_vector_context(results, max_chars)` | XML 태그로 결과 포맷 |

---

## SessionMemoryManager

LTM + STM + VMM을 통합하는 최상위 파사드.

### 기록 메서드

| 메서드 | 대상 | 설명 |
|--------|------|------|
| `record_message(role, content)` | STM | 대화 메시지 기록 |
| `record_event(event, data)` | STM | 이벤트 기록 |
| `remember(text, heading=None)` | LTM | MEMORY.md에 추가 |
| `remember_dated(text)` | LTM | 날짜별 파일에 기록 |
| `remember_topic(topic, text)` | LTM | 토픽 파일에 기록 |
| `record_execution(input_text, result_state, ...)` | LTM + VMM | 구조화된 실행 요약 기록 |

### record_execution 출력 형식

날짜별 LTM 파일에 기록되는 실행 요약:

```markdown
## ✅ Task: Python 웹 서버 만들어줘
- **Duration:** 12.3초 | **Difficulty:** easy | **Iterations:** 1
- **Completion:** COMPLETE
- **Cost:** $0.0234

### Output Preview
최종 응답의 처음 500자...
```

hard 경로는 TODO 목록, medium 경로는 리뷰 피드백, 모델 폴백 시 폴백 정보도 포함.

### 검색 메서드

```python
results = await manager.search("웹 서버", max_results=10)
# LTM 결과에 1.2x 가중치 부여
```

### 컨텍스트 빌드 (프롬프트 주입용)

```python
context = await manager.build_memory_context_async(
    query="웹 서버",
    include_summary=True,
    include_recent=True,
    max_chars=8000
)
```

출력 형식 (XML 태그):
```xml
<session-summary>
  세션 요약 내용...
</session-summary>

<long-term-memory>
  MEMORY.md 내용...
</long-term-memory>

<vector-memory>
  [memory/2026-03-20.md] 관련 청크...
  [memory/topics/python-basics.md] 관련 청크...
</vector-memory>

<memory-recall>
  키워드 검색 결과...
</memory-recall>

<recent-message>
  최근 대화 이력...
</recent-message>
```

기본 예산: 8000자.

---

## 데이터 타입

### MemoryEntry

```python
@dataclass
class MemoryEntry:
    source: MemorySource      # LONG_TERM, SHORT_TERM, BOOTSTRAP
    content: str
    timestamp: Optional[datetime]
    filename: Optional[str]
    line_start: Optional[int]
    line_end: Optional[int]
    metadata: Dict[str, Any]

    @property
    def token_estimate(self) -> int:
        return len(self.content) // 3  # 3 chars ≈ 1 token
```

### MemorySearchResult

```python
@dataclass
class MemorySearchResult:
    entry: MemoryEntry
    score: float
    snippet: str
    match_type: str  # "keyword", "recency", "combined", "db_keyword"
```

---

## 워크플로우와의 연동

`memory_inject` 노드가 워크플로우 실행 시 자동으로 메모리를 주입:

```
Memory Inject 노드
    │
    ├── 1. LLM 게이트: 메모리가 필요한지 판단 (MemoryGateOutput)
    │
    ├── 2. 필요한 경우:
    │     ├── 세션 요약 (STM summary)
    │     ├── MEMORY.md (LTM main)
    │     ├── FAISS 벡터 검색 (VMM)
    │     └── 키워드 검색 (LTM + STM)
    │
    └── 3. 상태 갱신:
          ├── memory_refs: 로드된 메모리 청크 목록
          └── memory_context: 포맷된 메모리 텍스트
```

---

## 관련 파일

```
service/memory/
├── types.py                # MemorySource, MemoryEntry, MemorySearchResult, MemoryStats
├── long_term.py            # LongTermMemory (Markdown + DB)
├── short_term.py           # ShortTermMemory (JSONL + DB)
├── embedding.py            # EmbeddingProvider ABC + 3종 구현
├── vector_store.py         # SessionVectorStore (FAISS), chunk_text()
├── vector_memory.py        # VectorMemoryManager (인덱싱 + 검색)
└── manager.py              # SessionMemoryManager (통합 파사드)
```
