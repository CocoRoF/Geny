# 05. 갭 요약 — Geny 현재 상태 vs 목표 상태

> 본 문서는 `01~04` 의 사실을 "무엇을 빼고, 무엇을 고치고, 무엇을 새로 넣는가" 로
> 축약한다. `plan/` 은 이 표를 원점으로 삼는다.

## 1. 한눈에 보는 대분류

| 영역 | 현재 Geny | 목표 상태 | 격차 수준 |
|------|---------|-----------|----------|
| executor 버전 | `>=0.8.3` | `>=0.20.0` | S (의존성 교체) |
| executor 연동 | `GenyPresets.{vtuber,worker_adaptive}` + 내장툴 + `SessionMemoryManager` | `PipelineBuilder` / `PipelinePresets` / `EnvironmentManifest` 중 택 + `MemoryProvider` | M~L (구조 재편) |
| 메모리 서브시스템 | Geny 자체 구현 (5 계층 + FAISS + DB dual-write) | executor `MemoryProvider` 프로토콜 기반 | L (데이터 이동 + 인터페이스 재작성) |
| Environment 시스템 | **부재** | web v0.9.0 와 동등 (Service + REST 15 개 + Catalog 5 개 + UI 탭 2 개) | XL (완전 신규) |
| 툴 시스템 | `ToolLoader → ToolRegistry` 브리지 + 내장 6 + MCP | 동일 + (옵션) `AdhocTool` | S (유지 가능) |
| 세션 계층 | 자체 `AgentSessionManager` | 자체 유지 + executor `session/` 와 경계 설정 | S~M |
| 프런트엔드 | Next.js (AvatarView/Chat/Memory/…) | + Environment 탭 + Builder 탭 | L (신규 페이지) |
| 인증/권한 | 기존 `auth_controller` | Environment/Memory 엔드포인트에도 적용 | S |
| DB 스키마 | `session_memory_entries` + 기타 | executor SQL 프로바이더와 공존 / 데이터 마이그레이션 | M~L |

## 2. 구체 갭 테이블

### 2-A. 의존성·임포트

| 위치 | 현재 | 수정 |
|------|------|------|
| `backend/pyproject.toml` | `geny-executor>=0.8.3` | `geny-executor>=0.20.0` + `[postgres]` extra 고려 |
| `agent_session.py` import | `GenyPresets`, `ToolRegistry`, `Tool{Context,Result}`, 내장툴, `PipelineState` | 그대로 통과 (§03.1). 단 구성 로직은 재검증 |

### 2-B. 파이프라인 구축

| 결정 후보 | 장점 | 단점 |
|-----------|------|------|
| A. `GenyPresets` 유지 | 기존 코드 최소 수정; `SessionMemoryManager` 재사용 | executor 가 "legacy adapter" 로 레이블링; 신규 기능(Environment/MemoryProvider) 통합이 우회적 |
| B. `PipelineBuilder` 직접 | 유연; Environment 와 자연스러운 공존 | Geny `SessionMemoryManager` 와 연결하려면 자체 어댑터 작성 |
| C. `EnvironmentManifest` 우선 | UI 와 완전 통합; 동적 환경 가능 | 초기 부팅시 기본 Env 템플릿 필요 |

⇒ `plan/02` 에서 **A 를 1 단계 호환 유지용**, **B 를 2 단계 이관용**, **C 를 3 단계 풍부화용** 으로 순차 채택 권장.

### 2-C. 메모리

| 운영 | 현재 Geny | 이식 방식 |
|------|---------|-----------|
| STM | JSONL + DB dual-write (`short_term.py`) | `SQLMemoryProvider.stm()` 로 대체 가능. 기존 JSONL 은 읽기전용 아카이브 |
| LTM | Markdown + DB dual-write (`long_term.py`) | `SQLMemoryProvider.ltm()` + `notes()` 혼용. MEMORY.md 의 evergreen 의미는 별도 키로 표현 |
| Notes | `StructuredMemoryWriter` + `MemoryIndexManager` + 파일 | `NotesHandle` + 외부 `_index.json` 은 제거, executor `IndexHandle` 사용 |
| Vector | FAISS flat + JSON sidecar + 자체 `EmbeddingProvider` (openai/google/voyage) | executor `VectorHandle` + `EmbeddingClient` (local/openai/voyage/google 네 종) |
| Curated | `_curated_knowledge/{user}/` + 자체 CRUD | `Scope.USER` + `curated()` 핸들 (Composite 프로바이더로 라우팅) |
| Global | `_global_memory/` | `Scope.GLOBAL` + `global_()` |
| Reflection | `auto_flush()` + LLM 요약 | executor `Capability.REFLECT/SUMMARIZE` — 실제 LLM 콜은 Geny 의 `reflect_utils.py` 로 유지 |
| Promotion | `record_execution()` (자동 태그 + dual-write) | `Capability.PROMOTE` + Geny 의 자동태그 휴리스틱은 "노트 write 전 preprocessor" 로 유지 |
| Index | `_index.json` 파일 캐시 | `IndexHandle` + DB 백엔드 |
| Obsidian 인제스트 | `UserOpsidianManager` | executor 대응 없음 — Geny 레이어 유지 (단, `Capability.LINK` 사용) |

### 2-D. Environment 시스템 (신규)

Geny 에 없는 것 전부 신규 구축:

- `EnvironmentService` (`backend/service/environment/` 디렉토리 신규).
- Environment REST 라우터 (15 엔드포인트).
- Catalog REST 라우터 (5 엔드포인트).
- 프런트 `environment/` + `builder/` 페이지 세트.
- 데이터 경로: `./data/environments/*.json` (web 과 동일 포맷).

### 2-E. 세션 REST 확장

| 변경점 | 현재 | 목표 |
|-------|------|------|
| `POST /api/agents` | 프리셋/역할 기반 | `env_id` (선택) / `memory_config` (선택) 수용 |
| `GET /api/agents/{id}` | 프리셋 라벨 반환 | `env:<id>` 합성 라벨 지원 |
| `/api/sessions/{id}/memory/*` | (없음) | web v0.9.0 3 엔드포인트 상응 |

### 2-F. 인증/권한

Geny 의 현존 `auth_controller` 는 Bearer/세션쿠키 기반. Environment 템플릿과 메모리 엔드포인트에도 `owner_username` 을 적용할지 결정 필요 (web 에는 이 개념 없음).

## 3. 데이터 마이그레이션 이슈

- **DB 스키마 이동**: 현재 Geny 의 `session_memory_entries` 는 "STM+LTM 통합 테이블" 구조. executor SQL 프로바이더는 레이어별 테이블을 만든다. 공존 전략:
  - 단기: 양쪽 테이블 동시 유지. 읽기 경로는 새 프로바이더, 쓰기는 양쪽 (migration 기간).
  - 장기: 배치 스크립트로 Geny 테이블 → 프로바이더 테이블.
- **Vector 리인덱스**: FAISS flat → pgvector(프로덕션) 또는 SQLite+FAISS fallback(로컬). 임베딩 dim 불일치 시 재생성 필요.
- **Markdown LTM 파일 유지 여부**: 인간이 읽는 대상이므로 "executor SQL + 파일 export" 병행이 현실적.

## 4. 리스크 & 경계

1. **부팅 순서**: 현재 main.py 는 AppDB → 툴로더 → MCP → agent_manager → vtuber → curation 순. Environment/Memory 는 agent_manager 직전 (DB 이후) 에 끼워 넣어야 세션 생성 요청 시 가용.
2. **싱글턴 충돌**: Geny `AgentSessionManager` 는 프로세스 싱글턴. executor `session.SessionManager` 는 인스턴스 단위. 두 개가 같은 `session_id` 를 관리하지 않도록 역할 분할 필요 (plan/02).
3. **VTuber 연계**: VTuber ↔ CLI 자동페어, 공유 폴더, ThinkingTrigger 는 Geny 도메인. Environment 가 세션을 만드는 경로에서도 이들이 일관되게 호출되는지 확인해야 함.
4. **큐레이션 스케줄러**: `CurationScheduler` 는 60 초 루프. `MemoryProvider` 로 전환 시 읽기 경로 변경 + LLM 콜은 Geny 측 유지 — 두 계층 간 계약 정의 필요.
5. **PyPI 동기**: executor 가 0.21 이후 계속 진화 — Geny 의 core CI 에 executor 버전 pin 변경시 자동 스모크를 넣을 필요.

## 5. 결론

Geny 통합 작업은 **"라이브러리 교체"가 아니라 "시스템 재설계"** 다. 세 레이어가 동시에 움직인다.

- **L1 (배관)**: pyproject / env / docker-compose / 부팅 순서.
- **L2 (백엔드 서비스)**: Environment / Memory / Catalog + 세션 확장 + 레거시 메모리 어댑터.
- **L3 (프런트)**: Environment/Builder 탭 + 메모리 UI 업데이트.

각 레이어는 단계별 PR 로 분해 가능 (plan/01 ~ plan/06 참조). **기존 Geny UX 는 깨지지 않도록** 1 단계는 호환 유지, 2 단계에서 executor-native 로 이관, 3 단계에서 Environment UI 로 풍부화.
