# 세션 스토리지 & 메모리 시스템 상호작용 검토

> 작성일: 2026-03-29
> 범위: `memory/`, `transcripts/`, `vectordb/`, `WORK_LOG.md`, `_shared/`, `.claude_session.json`

---

## 1. 세션 디렉토리 전체 구조

```
{session_storage}/
├── .claude_session.json        ← 세션 메타데이터 (ID, 이름, 스토리지 경로 등)
├── .mcp.json                   ← MCP 설정 (해당 시)
│
├── memory/                     ← 장기 기억 (LongTermMemory + StructuredWriter)
│   ├── MEMORY.md               ← 메인 장기 기억 아카이브
│   ├── _index.json             ← 파일 인덱스 + 태그맵 + 링크 그래프
│   ├── daily/                  ← 날짜별 실행 기록/일지
│   ├── topics/                 ← 토픽별 노트
│   ├── entities/               ← 엔티티(사람, 서비스 등) 노트
│   ├── projects/               ← 프로젝트 추적 노트
│   └── insights/               ← 인사이트 노트
│
├── transcripts/                ← 단기 기억 (ShortTermMemory)
│   ├── session.jsonl           ← 대화 기록 (JSONL, 최대 2000줄)
│   └── summary.md              ← 세션 요약 (선택적)
│
├── vectordb/                   ← 벡터 검색 인덱스 (VectorMemoryManager)
│   ├── index.faiss             ← FAISS 코사인 유사도 인덱스
│   └── metadata.json           ← 청크 메타데이터 (텍스트, 소스파일 등)
│
├── WORK_LOG.md                 ← 실행 작업 로그 (ProcessManager 전용)
│
└── _shared/ → {ROOT}/_shared   ← 글로벌 공유 폴더 (심볼릭 링크/Junction)
```

---

## 2. 각 서브시스템 역할 정리

### 2.1 Memory 시스템 (`memory/`)
| 항목 | 내용 |
|------|------|
| **담당 코드** | `service/memory/manager.py` → `SessionMemoryManager` |
| **하위 모듈** | `LongTermMemory`, `StructuredMemoryWriter`, `MemoryIndexManager` |
| **생성 시점** | `SessionMemoryManager.initialize()` 호출 시 |
| **기록 방식** | `MEMORY.md` append + `daily/*.md` 구조화 노트 + DB 이중 기록 |
| **용도** | 지식/사실/결정/인사이트 등 **영구 보존** 대상 정보 |

### 2.2 Transcripts 시스템 (`transcripts/`)
| 항목 | 내용 |
|------|------|
| **담당 코드** | `service/memory/short_term.py` → `ShortTermMemory` |
| **소유자** | `SessionMemoryManager` (memory 시스템의 일부) |
| **생성 시점** | `SessionMemoryManager.initialize()` 호출 시 |
| **기록 방식** | `session.jsonl`에 JSONL 1줄씩 append |
| **용도** | 대화 히스토리 전체 기록 (**원문 그대로** 보존) |
| **제한** | 2000줄 초과 시 오래된 것부터 삭제 (rotation) |

### 2.3 VectorDB (`vectordb/`)
| 항목 | 내용 |
|------|------|
| **담당 코드** | `service/memory/vector_memory.py` → `VectorMemoryManager` |
| **소유자** | `SessionMemoryManager` (memory 시스템의 일부) |
| **생성 시점** | LTM config에서 enabled=True 일 때, 첫 인덱싱 시 |
| **데이터 소스** | `memory/*.md` 파일들을 청킹 → 임베딩 → FAISS 저장 |
| **용도** | 시맨틱 검색 (유사도 기반 메모리 조회) |

### 2.4 WORK_LOG.md
| 항목 | 내용 |
|------|------|
| **담당 코드** | `service/claude_manager/process_manager.py` → `_append_work_log()` |
| **소유자** | `ClaudeProcess` (메모리 시스템과 **독립**) |
| **생성 시점** | 첫 실행(execute) 완료 후 |
| **기록 방식** | 실행마다 Markdown 엔트리 append |
| **용도** | 실행 감사 로그 (프롬프트, 툴 호출, 비용, 소요시간) |

### 2.5 Shared Folder (`_shared/`)
| 항목 | 내용 |
|------|------|
| **담당 코드** | `service/shared_folder/shared_folder_manager.py` |
| **생성 시점** | 세션 생성 시 (`AgentSessionManager._link_shared_folder()`) |
| **방식** | Windows: `mklink /J`, Unix: 심볼릭 링크 |
| **용도** | 모든 세션이 공유하는 글로벌 스토리지 |

### 2.6 `.claude_session.json`
| 항목 | 내용 |
|------|------|
| **담당 코드** | `process_manager.py` → `_create_session_info_file()` |
| **생성 시점** | `ClaudeProcess.initialize()` 시 |
| **용도** | 세션 메타데이터 (ID, 이름, 역할, 공유폴더 경로 등) |

---

## 3. 데이터 흐름도

```
사용자 입력 → 실행 시작
      │
      ├─────────────────── LangGraph 경로 ───────────────────┐
      │  (agent_session.py)                                   │
      │                                                       │
      │  ① record_message("user", input)                     │
      │     → transcripts/session.jsonl (JSONL append)        │
      │     → DB 이중 기록                                     │
      │                                                       │
      │  ② [실행 완료 후] record_execution(...)               │
      │     → memory/daily/YYYY-MM-DD.md (구조화 노트)         │
      │     → memory/MEMORY.md (append)                       │
      │     → vectordb/ (재인덱싱, 활성화 시)                   │
      │     → DB 이중 기록                                     │
      │                                                       │
      │  ✗ WORK_LOG.md 기록 안 함                              │
      │                                                       │
      ├─────────────── ClaudeProcess 경로 ───────────────────┐
      │  (process_manager.py)                                 │
      │                                                       │
      │  ① [실행 완료 후] _append_work_log(...)               │
      │     → WORK_LOG.md (Markdown append)                   │
      │                                                       │
      │  ✗ memory/ 시스템 직접 기록 안 함                       │
      │  ✗ transcripts/ 직접 기록 안 함                        │
      │                                                       │
      └───────────────────────────────────────────────────────┘
```

---

## 4. 충돌/중복 분석

### 4.1 ✅ 충돌 없음 — Memory ↔ Transcripts

| 구분 | Transcripts (`session.jsonl`) | Memory (`memory/*.md`) |
|------|------|------|
| **목적** | 대화 원문 그대로 보존 | 지식/사실 추출 및 영구 저장 |
| **포맷** | JSONL (구조화 로그) | Markdown + YAML frontmatter |
| **유지기간** | 2000줄 로테이션 (일시적) | 무기한 (영구) |
| **소유자** | `ShortTermMemory` | `LongTermMemory` + `StructuredWriter` |

**관계**: Transcripts는 memory 시스템의 **하위 모듈**이며 `SessionMemoryManager`가 두 가지를 모두 관리한다. 동일 데이터를 중복 저장하지 않으며, 서로 다른 계층의 정보를 담당한다.

- Transcripts = "무엇을 말했는가" (원문)
- Memory = "무엇을 기억해야 하는가" (추출/요약된 지식)

**결론: 충돌 없음. 설계 의도대로 분리됨.**

---

### 4.2 ⚠️ 부분 중복 — WORK_LOG.md ↔ Memory `record_execution()`

**핵심 발견: 두 시스템이 유사한 실행 기록을 각각 독립적으로 생성한다.**

| 구분 | WORK_LOG.md | memory/daily/*.md |
|------|-------------|-------------------|
| **호출 위치** | `process_manager.py:572` | `agent_session.py:982` |
| **실행 엔진** | Claude Process (레거시) | LangGraph Agent (신규) |
| **기록 내용** | 프롬프트, 출력, 툴 호출, 비용, 소요시간 | 프롬프트, 출력 요약, 이터레이션, 성공/실패 |
| **DB 백업** | ❌ 없음 | ✅ 이중 기록 |
| **벡터 인덱싱** | ❌ 안 됨 | ✅ FAISS 인덱싱 (활성화 시) |
| **frontmatter** | ❌ 없음 | ✅ 제목, 태그, 카테고리, 중요도 |
| **검색 가능** | ❌ 파일 뷰만 가능 | ✅ 시맨틱 + 태그 + 카테고리 검색 |

**결론:**
- **현재 상태**: LangGraph 세션은 `record_execution()`으로 `memory/daily/`에 기록하고, WORK_LOG.md는 생성하지 않음. ClaudeProcess 세션은 `WORK_LOG.md`만 생성하고 memory에는 기록하지 않음. **두 경로가 서로 다른 실행 엔진에서 사용되므로 실질적 중복은 없다.**
- **잠재 이슈**: 만약 향후 두 엔진이 통합되면 중복 기록 가능성이 있음.
- **심각도**: 🟢 낮음 (현재 충돌 없음)

---

### 4.3 ✅ 충돌 없음 — `_index.json` ↔ `metadata.json`

| 구분 | `memory/_index.json` | `vectordb/metadata.json` |
|------|---------------------|--------------------------|
| **관리 주체** | `MemoryIndexManager` | `SessionVectorStore` |
| **내용** | 파일 목록, 태그맵, 링크 그래프 (파일 단위) | 벡터 청크 메타데이터 (청크 단위) |
| **용도** | 파일 탐색, 태그/카테고리 필터링 | 시맨틱 검색 시 청크 매칭 |

**결론: 서로 다른 레벨의 인덱스. 충돌 없음.**

---

### 4.4 ✅ 충돌 없음 — Shared Folder ↔ Memory

| 구분 | `_shared/` | `memory/` |
|------|-----------|-----------|
| **범위** | 글로벌 (모든 세션 공유) | 세션별 (또는 글로벌 메모리) |
| **접근 방식** | 파일 직접 읽기/쓰기 | API를 통한 구조화된 접근 |
| **링크** | 심볼릭 링크/Junction | 물리적 디렉토리 |

`_shared/`는 사용자가 직접 파일을 올리는 공유 스토리지이고, `memory/`는 에이전트가 자동으로 지식을 기록하는 시스템이라 역할이 완전히 다르다.

**결론: 충돌 없음.**

---

### 4.5 ✅ 충돌 없음 — StorageTab 표시

`StorageTab`은 `list_storage_files()`를 통해 세션 디렉토리 내 **모든 파일**을 재귀적으로 나열한다. `MemoryTab`은 `memory/` 하위만을 memory API를 통해 구조화된 형태로 보여준다.

| 구분 | StorageTab | MemoryTab |
|------|-----------|-----------|
| **표시 범위** | 세션 전체 파일 (memory, transcripts, vectordb, WORK_LOG 포함) | `memory/` 하위만 |
| **표시 방식** | 파일 트리 + 원본 뷰어 | 카테고리/태그 필터 + frontmatter 파싱 뷰어 |
| **편집** | ❌ 읽기 전용 | ✅ 생성/수정/삭제 |

**결론: 두 탭은 같은 데이터를 다른 관점으로 보여줌. 의도된 설계.**

---

## 5. 종합 판정

| 검토 항목 | 결과 | 비고 |
|-----------|------|------|
| Memory ↔ Transcripts 충돌 | ✅ 없음 | STM과 LTM으로 명확히 분리 |
| WORK_LOG ↔ Memory 중복 | ⚠️ 부분 중복 | 서로 다른 실행 엔진에서만 사용되므로 실질 충돌 없음 |
| `_index.json` ↔ `metadata.json` 충돌 | ✅ 없음 | 파일 레벨 vs 청크 레벨 인덱스 |
| Shared Folder ↔ Memory 충돌 | ✅ 없음 | 완전히 독립적 |
| StorageTab ↔ MemoryTab 충돌 | ✅ 없음 | 같은 데이터의 다른 뷰 |
| VectorDB 동기화 | ⚠️ 주의 | memory 파일 삭제 시 vectordb 재빌드 필요 |

### 최종 결론

**현재 시스템에 심각한 충돌은 없다.** 각 서브시스템이 명확한 역할 분담을 가지고 있으며, 데이터 흐름이 잘 분리되어 있다.

유일한 주의점:
1. **WORK_LOG.md는 ClaudeProcess 전용** — LangGraph 세션에서는 `memory/daily/`가 그 역할을 대신함. 향후 엔진 통합 시 정리 필요.
2. **VectorDB 동기화** — memory 파일을 수동 삭제하면 vectordb와 비동기 상태가 됨. reindex API 호출로 해결 가능.
3. **Transcripts 로테이션** — 2000줄 초과 시 오래된 대화가 유실되나, 이는 의도된 설계 (장기 보존은 memory 시스템 담당).
