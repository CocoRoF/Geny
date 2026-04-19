# 02. Geny 의 레거시 메모리 서브시스템

> 대상 경로: `backend/service/memory/`
> 주목: Geny 는 **executor 의 `MemoryProvider` 를 모르는 시점 (v0.8.x)** 에 자체
> 설계되었으므로, v0.20.0 의 `Layer × Capability × Backend × Scope` 4축 모델과
> 개념은 겹치지만 **인터페이스가 전혀 호환되지 않음.**

## 1. 파일별 인벤토리

| 파일 | 핵심 타입 | 저장 계층 | 외부 의존 |
|------|-----------|-----------|-----------|
| `manager.py` | `SessionMemoryManager` (파사드) | 파일 + DB | 모든 하위 모듈 |
| `types.py` | `MemoryEntry`, `MemorySearchResult`, `MemoryStats`, `MemorySource` | — | dataclass 만 |
| `short_term.py` | `ShortTermMemory` (STM) | JSONL + DB (dual-write) | `memory_db_helper` |
| `long_term.py` | `LongTermMemory` (LTM) | Markdown + DB (dual-write) | `memory_db_helper` |
| `vector_memory.py` | `VectorMemoryManager` | FAISS 디스크 + JSON 메타 | `EmbeddingProvider`, `SessionVectorStore`, `LTMConfig` |
| `vector_store.py` | `SessionVectorStore`, `ChunkMeta`, `VectorSearchResult` | FAISS IndexFlatIP + `metadata.json` | `numpy`, `faiss` |
| `embedding.py` | `EmbeddingProvider` ABC + OpenAI/Google/Voyage 구현 | stateless HTTP | `httpx` |
| `index.py` | `MemoryIndexManager`, `MemoryIndex`, `MemoryFileInfo` | `_index.json` 캐시 | `frontmatter` |
| `structured_writer.py` | `StructuredMemoryWriter` (Obsidian-like CRUD) | `memory/{category}/*.md` + DB | `frontmatter`, `index` |
| `frontmatter.py` | `parse_frontmatter` / `render_frontmatter` / `extract_wikilinks` (PyYAML 없이) | 순수 파서 | — |
| `migrator.py` | `MemoryMigrator` | 파일 이동 + 프론트매터 시드 | `frontmatter` |
| `curated_knowledge.py` | `CuratedKnowledgeManager` (사용자별 볼트) | `_curated_knowledge/{user}/` | `structured_writer`, `index`, `vector_memory` |
| `curation_engine.py` | `CurationEngine` (LLM 기반 노트 정제) | — | `langchain_anthropic` |
| `curation_scheduler.py` | `CurationScheduler` (백그라운드 큐레이션) | — | 위 엔진 |
| `global_memory.py` | `GlobalMemoryManager` (크로스 세션) | `_global_memory/` | `structured_writer`, `index` |
| `reflect_utils.py` | LLM 호출 유틸 (반사 요약) | — | `anthropic` / `langchain_anthropic` |
| `user_opsidian.py` | `UserOpsidianManager` (외부 Obsidian 인제스트) | 사용자 볼트 경로 | `frontmatter`, `index` |
| `structured_writer.py` | (위 동일) | — | — |

### 디스크 레이아웃 (세션 한 개 기준)

```
<storage_path>/
├── transcripts/
│   ├── session.jsonl      # STM append-only (최대 2000 엔트리 truncate)
│   └── summary.md         # 옵션 세션 요약
├── memory/
│   ├── MEMORY.md          # LTM evergreen
│   ├── 2026-04-19.md      # LTM dated (날짜별 append)
│   ├── topics/
│   │   └── <slug>.md      # LTM topic
│   ├── daily/
│   │   └── <slug>.md      # 구조화 노트 (daily)
│   ├── entities/ projects/ insights/ root/
│   └── _index.json        # MemoryIndexManager 캐시
└── vectordb/
    ├── index.faiss        # FAISS IndexFlatIP
    └── metadata.json      # ChunkMeta[]
```

추가로:

```
<storage_root>/_curated_knowledge/<username>/...    # CuratedKnowledgeManager
<storage_root>/_global_memory/...                   # GlobalMemoryManager
```

## 2. 영속 계층 요약

| 계층 | Geny 저장소 | executor v0.20.0 대응 |
|------|-------------|-----------------------|
| STM | JSONL (session.jsonl, 파일) + DB (Postgres/SQLite) | `Layer.STM` — `SQLMemoryProvider` / `FileMemoryProvider` / `EphemeralMemoryProvider` |
| LTM | MEMORY.md / dated / topics + DB | `Layer.LTM` — 위와 동일 |
| Notes (structured) | `{category}/*.md` + `_index.json` + DB | `Layer.NOTES` |
| Vector | FAISS disk + JSON sidecar (파일-only) | `Layer.VECTOR` — SQLite(FAISS fallback) 또는 Postgres(pgvector) |
| Index (tag/link) | `_index.json` | `Layer.INDEX` (secondary index) |
| Curated | `_curated_knowledge/{user}/*.md` | `Layer.CURATED` + `Scope.USER` |
| Global | `_global_memory/*.md` | `Layer.GLOBAL` + `Scope.GLOBAL` |

> **주의**: Geny 는 "dual-write" (파일 + DB) 를 사용하지만 executor 의 SQL 프로바이더는
> DB 를 단일 진실의 원천으로 삼는다. 이 불일치는 마이그레이션 시 반드시 다룬다.

## 3. 11 개 메모리 오퍼레이션 × Geny 파일/메서드 × executor 매핑

`geny-executor-web/docs/MEMORY_ARCHITECTURE.md` 에서 요구된 11 개 오퍼레이션을
Geny 레거시 구현과 executor 프로바이더 매핑해 둔다.

| # | 오퍼레이션 | Geny 구현 | executor v0.20.0 대응 |
|---|------------|-----------|-----------------------|
| 1 | STM append/read | `manager.record_message()` → `short_term.add_message()` / `load_all()` / `get_recent()` | `stm().append(Turn)` / `stm().recent(n)` / `stm().search()` |
| 2 | LTM write | `manager.remember()` / `remember_dated()` / `remember_topic()` → `long_term.append/write_dated/write_topic` | `ltm().append` / `ltm().write_dated` / `ltm().write_topic` |
| 3 | Notes listing / tag search | `manager.list_notes()` / `get_memory_tags()` → `structured_writer.list_notes()` / `index_manager.get_all_tags()` | `notes().list(category, tag)` / `notes().tags()` |
| 4 | Vector embed + upsert | `vector_memory.index_memory_files()` / `index_text(...)` → `vector_store.add_chunks()` | `vector().index_batch(...)` (via `EmbeddingClient`) |
| 5 | Vector semantic search | `vector_memory.search(query, top_k, threshold)` | `vector().search(query, top_k, threshold)` / `provider.retrieve(RetrievalQuery)` |
| 6 | Curated load | `CuratedKnowledgeManager.list_notes()` / `search()` / `vector_search()` | `curated().list()` / `retrieve(RetrievalQuery(layers={CURATED}))` |
| 7 | Global read | `GlobalMemoryManager.list_notes()` / `search()` / `get_index()` | `global_().list()` / `global_().search()` |
| 8 | Reflection (STM tail → LTM) | `manager.auto_flush(recent_n)` → `long_term.write_dated` + `stm.write_summary` | `Capability.REFLECT` + `Capability.SUMMARIZE` (컨트랙트; Geny 측 LLM 호출 로직은 그대로 유지 가능) |
| 9 | Promotion STM→LTM 휴리스틱 | `manager.record_execution()` (dual-write LTM dated + 구조화 노트 + vector 인덱스) | `Capability.PROMOTE` (Scope 이동) + `notes().write` + `ltm().append` |
| 10 | Frontmatter 노트 메타데이터 | `structured_writer.write_note()` + `frontmatter.render_frontmatter()` | executor 가 강제하지 않음 — Geny 측 포맷 유지 가능 (프로바이더는 content + metadata 쌍으로 저장) |
| 11 | 외부 노트 인제스트 (Obsidian) | `migrator.migrate()` + `UserOpsidianManager` | `Capability.LINK` / `notes().import(vault_path)` (존재 여부는 *03* 에서 확인) |

## 4. 현재 REST 표면 (메모리 관련)

총 ~43 개 엔드포인트가 세션/큐레이트/사용자볼트 3 벌로 존재.

### `/api/agents/{session_id}/memory/*` (14 엔드포인트)

| Verb | Path | 컨트롤러 메서드 |
|------|------|----------------|
| GET | `/{session_id}/memory` | `get_memory_index` |
| GET | `/{session_id}/memory/stats` | `get_memory_stats` |
| GET | `/{session_id}/memory/tags` | `get_memory_tags` |
| GET | `/{session_id}/memory/graph` | `get_memory_graph` |
| GET | `/{session_id}/memory/files` | `list_memory_files` |
| GET | `/{session_id}/memory/files/{filename}` | `read_memory_file` |
| POST | `/{session_id}/memory/files` | `create_memory_file` |
| PUT | `/{session_id}/memory/files/{filename}` | `update_memory_file` |
| DELETE | `/{session_id}/memory/files/{filename}` | `delete_memory_file` |
| GET | `/{session_id}/memory/search` | `search_memory` (쿼리 파라미터) |
| POST | `/{session_id}/memory/search` | `search_memory_post` (바디) |
| POST | `/{session_id}/memory/links` | `create_memory_link` |
| POST | `/{session_id}/memory/reindex` | `reindex_memory` |
| POST | `/{session_id}/memory/migrate` | `migrate_memory` |
| POST | `/{session_id}/memory/promote` | `promote_to_global` |

### `/api/curated/*` (~15 엔드포인트)

Curated 볼트 CRUD + 검색 + `/curate` 이벤트.

### `/api/opsidian/*` (~14 엔드포인트)

사용자 볼트 CRUD + 검색.

## 5. 개념적 불일치 / 위험

- **dual-write 일관성**: 파일 ↔ DB truncation 시점이 다름. 읽기 경로가 DB 우선 → 파일 폴백이라 stale 읽기 가능. executor SQL 프로바이더는 단일 소스이므로 이식 시 **데이터 소유권 재설계** 필수.
- **벡터 백엔드 분기**: Geny 는 FAISS flat (파일) 고정. executor v0.20.0 은 SQLite = FAISS / Postgres = pgvector 분기. 마이그레이션 시 embedding dimension + 인덱스 포맷을 새로 뽑아야 할 가능성.
- **`_curated_knowledge` / `_global_memory` 경로**: executor 는 경로 강제 없음. 통합 시 파일 프로바이더의 `root` + `Scope` 로 재매핑해야 함.
- **Geny 의 `Importance` = critical/high/medium/low 2.0/1.5/1.0/0.5 부스트**. executor 에도 `Importance` enum 이 있으므로 **용어 일치** (단, 부스트 수치는 Geny 고유).
- **`Scope` enum 부재**: Geny 코드에는 세션/사용자/글로벌 구분이 경로로만 표현됨. executor 의 `Scope` (ephemeral/session/user/tenant/global) 로 명시화 필요.
- **WS 이벤트 미존재**: Geny 메모리 레이어는 구조화된 이벤트를 발행하지 않음. executor 측은 `pipeline.complete` 의 metadata 로 메모리 기록을 전파 가능하나, UI 가 실시간 반영하려면 별도 스트림 필요.

## 6. 오픈 퀘스천

- 레거시 Geny DB 의 `session_memory_entries` 테이블 스키마 vs executor `SQLMemoryProvider` 테이블 스키마 — 별도 확인 필요 (plan/03).
- `CurationEngine` 의 LLM 프롬프트와 executor `Reflect` 훅이 중복되면 어느 쪽을 유지할지 결정 필요.
- `record_execution()` 의 "자동 태그 추출 (debug/fix/test/…)" 휴리스틱은 executor 에 대응물 없음 → Geny 도메인 로직으로 유지.
