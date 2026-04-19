# 2026-04-20 작업 계획

v0.20.0 통합 사이클 이후 실사용 단계에서 드러난 3 가지 이슈 +
폴더 구조 정리.

---

## 0. 배경 / 범위

v0.20.0 통합은 2026-04-19 사이클로 코드 범위 완수
([`../20260419/progress/FINAL_INTEGRATION_REPORT.md`](../20260419/progress/FINAL_INTEGRATION_REPORT.md)).
이후 prod 사용 중 드러난 UX 3 종과 VTuber 출력 버그를 이 사이클에서
닫는다.

---

## 1. 이슈 1 — Environments + Builder 탭 통합

### 현재 상태

`frontend/src/components/TabNavigation.tsx:15` 의 `GLOBAL_TAB_IDS` 에
`'environments'` 와 `'builder'` 가 독립 탭으로 나란히 등록되어 있다.
Builder 는 실제로는 환경이 먼저 선택돼야만 의미가 있으므로 (현재
구조에서도 `builderEnvId` 가 null 이면 빈 placeholder 로 렌더), 두
탭이 병렬 존재하는 것은 사용자에게 혼란.

- `EnvironmentsTab.tsx:758` — 카드 클릭 → `setOpenInBuilder(env.id)`
  → `setActiveTab('builder')` 로 전환 (useEnvironmentStore).
- `BuilderTab.tsx:356-359` — "Back to Environments" 버튼 →
  `closeBuilder()` + `setActiveTab('environments')`.
- `TabContent.tsx` 의 `TAB_MAP` 에 양쪽 등록.

### 목표 UX

**단일 "Environments" 탭**. 내부에 2 가지 모드가 있다:

1. **List 모드 (기본)** — 현재의 EnvironmentsTab 내용 (카드 그리드,
   검색/필터/정렬, multi-select + bulk delete/export, Import,
   Compare 2, DiffMatrix, …).
2. **Builder 모드** — List 에서 env 카드를 "Edit" 하거나 drawer 의
   "Open in Builder" 버튼을 누르면 진입. 현재 BuilderTab 의 내용
   (StageList, StageCard, ToolsEditor, SchemaForm, StrategyEditors)
   + 상단에 "환경: [env 이름] ∨" 픽커 + "← List" breadcrumb.

탭 enum 에서 `'builder'` 를 제거한다. 기존 deep-link / 저장된 상태 가
`'builder'` 를 가리키면 자동으로 `'environments'` + builder 모드로
리라우팅.

### 변경 사항 (파일 단위)

1. `frontend/src/components/TabNavigation.tsx` — `GLOBAL_TAB_IDS` 에서
   `'builder'` 제거. 네비게이션 항목도 1 개 줄어듦.
2. `frontend/src/components/TabContent.tsx` — `TAB_MAP` 에서 `'builder'`
   키 제거. `'builder'` 요청이 들어오면 `'environments'` 로 fallback.
3. `frontend/src/store/useEnvironmentStore.ts` — `builderEnvId` 는
   유지 (Builder 모드 진입 트리거). 추가로 `mode: 'list' | 'builder'`
   를 탭-로컬 상태로 둘지, 또는 기존대로 `builderEnvId !== null` 을
   "builder 모드" 로 해석할지 결정 — **후자 채택** (상태 중복 회피).
4. `frontend/src/components/tabs/EnvironmentsTab.tsx` — 최상단에서
   `builderEnvId` 값에 따라 List UI 또는 BuilderTab 의 body 를 렌더.
   → BuilderTab 의 body 부분만 자식 컴포넌트로 추출해 재사용.
5. `frontend/src/components/tabs/BuilderTab.tsx` — 파일은 유지하되
   내부를 "BuilderView" 컴포넌트로 export. EnvironmentsTab 이 직접
   import.
6. `EnvironmentsTab` 의 "← List" 버튼은 `closeBuilder()` 호출 (기존과
   동일).

### 수용 기준

- 탭바에 "Environments" 1 개만 보임 (Builder 탭 사라짐).
- Environments 클릭 → List 모드.
- 카드의 "Edit" / "Open in Builder" → 같은 탭 안에서 Builder 모드로
  in-place 전환 (URL / activeTab 변경 없음).
- Builder 모드에서 "← List" → List 모드로 복귀, 선택 상태 (필터/정렬)
  유지.
- 기존 `setActiveTab('builder')` 호출부가 자동 리라우팅 되어 회귀 없음.

### 리스크

- Back 버튼 동선의 근본 구조 변경은 아니지만 `builderEnvId` 를
  모드 switch 로도 쓰므로, `openInBuilder(id)` 와 `loadEnvironment(id)`
  의 타이밍이 충돌하지 않도록 useEffect 순서 점검 필요.
- i18n key 2 개 정도 제거/변경 (`tabs.builder` 등).

### PR 단위

- 단일 PR — `feat(frontend): merge Builder tab into Environments`.
  최소 1 개, 최대 2 개 (i18n 분리시).

---

## 2. 이슈 2 — Session Graph 에 연결된 환경 표시

### 현재 상태

`frontend/src/components/tabs/GraphTab.tsx:14-31` 의
`PIPELINE_STAGES` 는 static 배열 (16 stage 하드코딩). 현재 세션의
`env_id` 를 읽지 않으며, 각 세션이 실제로 어떤 Environment manifest
로 실행되는지 GraphTab 에서 보이지 않는다.

세션 타입에는 이미 `SessionInfo.env_id` 필드 존재
(`frontend/src/types/index.ts:24`, v0.20.0 통합 시 추가).

### 목표 UX

GraphTab 상단에 **"Environment: [name]"** 배지 / 카드 표시:

- env_id 가 있으면 → 이름 + "Open in Environments" 버튼 (클릭 시
  Environments 탭 + 해당 env drawer 열기).
- env_id 가 없으면 → "Preset: [role]" (레거시 프리셋 경로).
- 그래프 스테이지 표기는 가능하면 manifest 의 실제 stage order 를
  반영. (Stretch goal — first pass 는 배지만.)

### 변경 사항 (파일 단위)

1. `frontend/src/components/tabs/GraphTab.tsx` — 상단에 `EnvBadge`
   추가. `env_id` 를 가진 세션이면 `useEnvironmentStore` 에서
   manifest 를 조회 (이미 load 되어 있지 않으면 `loadEnvironment(id)`
   lazy fire) 후 이름 / 배지 렌더.
2. `EnvBadge` 는 클릭 시 `setActiveTab('environments')` +
   `setOpenEnvId(id)` (drawer 진입).
3. (Stretch) `PIPELINE_STAGES` 를 manifest 기반으로 동적 구성 — env
   manifest 의 stage 배열과 현재 static 배열을 merge. 이슈 1 의
   Builder 통합 이후 manifest shape 재사용이 자연스러움. **이번
   사이클에서는 배지 + drill-down 까지만, 동적 stage 는 별도 PR 로
   분리**.

### 수용 기준

- env 로 생성된 세션 → GraphTab 진입 시 상단에 env 이름 + 배지 표시.
- 배지 클릭 → Environments 탭 + drawer 열림.
- Preset 기반 세션 → "Preset: worker" 등 라벨 fallback.
- env_id 가 제거(soft-delete)된 env 를 가리키면 → "Environment
  unavailable (deleted)" 빨간 tint.

### PR 단위

- 단일 PR — `feat(frontend): show linked environment in session Graph`.

---

## 3. 이슈 3 — VTuber Chat 출력이 stream 종료 시 500 자로 잘리는 버그

### 증상 (사용자 재확인)

> "Stream 단계에서는 전체가 출력되었다가, 출력이 종료되면 500 자
> 정도로 잘려서 나타나는 현상이 발견되었어. 즉 전체 데이터는 오지만,
> 실제로 사용자에게는 일부만 마지막에 잘려서 보여지는 문제."

이 증상은 "stream 중에는 ok → 종료 후 500자 truncated message 가
스트리밍 버블을 대체" 로 해석된다.

### 근본 원인 (확정)

**geny-executor `pipeline.complete` 이벤트의 `result` 필드가
`EVENT_DATA_TRUNCATE = 500` 으로 잘려서 송출되며, Geny 의
`agent_session.py` 가 이 잘린 값으로 streaming 누적 텍스트를
덮어쓴다.**

증거 chain:

1. **Source — geny-executor**
   - `geny-executor/src/geny_executor/core/pipeline.py:84`
     ```python
     EVENT_DATA_TRUNCATE = 500  # max chars for event data preview
     ```
   - 같은 파일 `:285` (run_stream)
     ```python
     PipelineEvent(
         type="pipeline.complete",
         data={
             "result": state.final_text[: self.EVENT_DATA_TRUNCATE],
             "iterations": state.iteration,
             "total_cost_usd": state.total_cost_usd,
         },
     )
     ```
   - 의도: 이벤트 페이로드의 "preview" — 디버그 출력용. 그러나 Geny
     는 이를 final result 로 신뢰한다.

2. **Sink — Geny `agent_session.py`**
   - `backend/service/langgraph/agent_session.py:894-906` (`_invoke_pipeline`)
     ```python
     if event_type == "text.delta":
         text = event_data.get("text", "")
         if text:
             accumulated_output += text          # ← 전체 누적 (정상)
             ...
     elif event_type == "pipeline.complete":
         accumulated_output = event_data.get("result", accumulated_output)
         #                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
         #                    ← 누적된 전체 텍스트를 500자 preview 로 덮어씀!
     ```
     반환: `return {"output": accumulated_output, ...}` (line 955) —
     이 시점에 이미 500자.
   - `backend/service/langgraph/agent_session.py:1049-1059` (`_astream_pipeline`)
     동일 패턴:
     ```python
     elif event_type == "pipeline.complete":
         result_text = event_data.get("result", accumulated_output)
         ...
         yield {"__end__": {"final_answer": result_text, ...}}
     ```

3. **Downstream 영향 경로**
   - `agent_executor.execute_command` 가 `invoke_result.get("output")`
     로 500자를 받음 → `result.output` (`agent_executor.py:499-540`).
   - `chat_controller._poll_logs` 가 `result.output.strip()` 을
     `chat_message.content` 로 store 에 저장 (line 668-684).
   - `conversation_store.add_message` → DB(TEXT, 무제한) 에는 500자
     그대로 들어감.
   - WS `chat_stream._stream_room_events` 가 store 에서 읽어 그대로
     클라이언트 송신.
   - `VTuberChatPanel.tsx:207-226` 의 `'message'` 핸들러가 streaming
     bubble 을 제거하고 (line 215-220) persisted 메시지를 추가
     (line 223-226) → 사용자 시점에서는 "stream 종료 → 500자로
     교체" 로 보임.

### 왜 이게 4월 19일 통합 이후에 드러났나

- v0.20.0 통합으로 Geny 의 agent 실행 경로가 geny-executor 의
  `Pipeline.run_stream` 으로 전면 교체됨.
- 그 전에는 `langgraph` 그래프가 직접 `accumulated_output` 을
  관리했고, `pipeline.complete.result` 같은 외부 이벤트 의존이
  없었음.
- 통합 시 `event_data.get("result", accumulated_output)` 패턴이
  들어왔고, 이 fallback default 가 무해해 보였지만 사실은 항상
  truncated `result` 가 들어와 덮어쓰기 발생.

### 수정안

**Two-sided fix (방어적):**

#### Fix A — geny-executor (원천)
`geny-executor/src/geny_executor/core/pipeline.py:280-290` 의
`run_stream` 경로 `pipeline.complete` 페이로드에서 `result` 필드를
**자르지 않는다**. EVENT_DATA_TRUNCATE 는 `pipeline.start.input` 같은
입력 preview 용으로 두고, 최종 결과는 truncate 없이 송출.

```diff
PipelineEvent(
    type="pipeline.complete",
    data={
-       "result": state.final_text[: self.EVENT_DATA_TRUNCATE],
+       "result": state.final_text,  # full final text — consumer needs untruncated
        "iterations": state.iteration,
        "total_cost_usd": state.total_cost_usd,
    },
)
```

`Pipeline.run` (non-stream, line 237) 은 애초에 `result` 를 보내지
않고 `PipelineResult` 객체를 직접 반환하므로 영향 없음.

#### Fix B — Geny (consumer 방어)
`backend/service/langgraph/agent_session.py:894-906` 와
`:1049-1059` 양쪽에서, `pipeline.complete.result` 가 streaming 으로
누적된 `accumulated_output` 보다 짧으면 누적 값을 신뢰한다:

```python
elif event_type == "pipeline.complete":
    streamed_result = event_data.get("result", "")
    # Defensive: streaming via text.delta is the source of truth;
    # pipeline.complete.result may be a truncated preview.
    if len(streamed_result) >= len(accumulated_output):
        accumulated_output = streamed_result
    total_cost = event_data.get("total_cost_usd", 0.0) or 0.0
    iterations = event_data.get("iterations", 0)
```

이렇게 하면 geny-executor 가 어느 버전이어도 (구 truncated /
신 untruncated) Geny 에서 회귀 없음. 두 PR 을 분리.

### 검증 단계

1. **Reproduce** — VTuber Chat 으로 600+ 자 응답을 유도하는 프롬프트
   ("아래 문장을 1000자 이상 풀어 설명해 줘") 를 실행. stream 중
   전체가 보이고 종료 시 500자로 줄어드는지 확인.
2. **Instrument (옵션)** — `agent_session.py:906` 직전에
   `logger.debug(f"[truncation-check] streamed_len={len(accumulated_output)} pipeline_result_len={len(event_data.get('result',''))}")` 추가, 한 번 실행 후 로그
   확인 → 가설 확정 후 instrumentation 제거.
3. **Fix A 적용** → geny-executor 패치, Geny 단독 fresh 실행
   재테스트. 풀 텍스트가 message 로 저장되는지 DB 직접 확인
   (`SELECT length(content) FROM chat_message ORDER BY created_at DESC LIMIT 1;`).
4. **Fix B 적용** → 두 fix 가 함께 동작.
5. **Regression** — 짧은 응답 (< 500자) 정상 동작, total_cost /
   iterations 필드 손상 없음.

### 수용 기준

- 2000 자 응답이 VTuber Chat 에 stream 종료 후에도 전체로 표시됨.
- DB `chat_message.content` 의 길이 = 모델 실제 출력 길이.
- 짧은 응답 / 에러 응답 / TTS 출력 회귀 없음.
- 프런트엔드 코드 변경 불필요 (truncation 은 백엔드에서 발생했음).

### PR 단위

- **PR-A** — `fix(executor): emit untruncated result in pipeline.complete`
  (geny-executor repo).
- **PR-B** — `fix(backend): trust streamed accumulation over pipeline.complete preview`
  (Geny repo, agent_session.py invoke + stream 양쪽).
- 두 PR 모두 머지 후 `dev_docs/20260420/progress/` 에 기록.

---

## 4. 폴더 구조 정리 (선행 작업 — 이 PR 에서 바로 진행)

### 이동

```
analysis/      → dev_docs/20260419/analysis/
plan/          → dev_docs/20260419/plan/
progress/      → dev_docs/20260419/progress/
```

### 신규

```
dev_docs/20260420/
├── plan.md                  # 이 문서
└── progress/                # 이번 사이클의 PR 기록 (작업 시 생성)
```

### 영향받는 참조

- `docs/MEMORY_UPGRADE_PLAN.md` — plan/progress 링크를
  `../dev_docs/20260419/…` 로 수정.
- `index.md` — 폴더 목록 업데이트.
- `plan/` 과 `progress/` 내부 상대 참조는 모두 `../plan/` /
  `../progress/` 형태라 같은 부모 디렉토리로 함께 이동하면
  링크가 그대로 유효.
- `analysis/` 도 같은 사이클 산출물이므로 함께 이동 확정 (사용자
  index.md 수정으로 확인됨).

---

## 5. 실행 순서

1. **PR #1** (Geny) — 폴더 구조 정리 (plan/progress → dev_docs/20260419,
   dev_docs/20260420/plan.md 추가, stale 참조 수정). 이 문서 자체를
   담고 있는 PR. **← 지금 이 단계.**
2. **PR #2** (Geny) — 이슈 1: Builder 탭을 Environments 안으로 통합.
3. **PR #3** (Geny) — 이슈 2: Session Graph 에 env 배지 + drill-down.
4. **PR #4-A** (geny-executor) — 이슈 3 Fix A: `pipeline.complete.result`
   untruncate.
5. **PR #4-B** (Geny) — 이슈 3 Fix B: `agent_session.py` 가 streaming
   누적을 신뢰하도록 방어 코드 + executor 의존 버전 bump (lock 파일).
6. 각 PR merge 후 `dev_docs/20260420/progress/NN_*.md` 기록.

---

## 6. 리스크 / 되돌리기

- 이슈 1: Builder 탭 제거는 breaking UX 변경. i18n / deep link /
  saved tab state 복구 경로 반드시 확인.
- 이슈 3: 진단 결과 근본 원인이 TTS 엔진 쪽 (outbound) 이면 단순
  코드 수정으론 끝나지 않을 수 있음 — "chunked TTS" 설계 필요.
- 폴더 이동은 `git mv` 로 처리되므로 history 는 보존. revert 1 PR 로
  복원 가능.

---

## 7. 사용자 확인 필요 항목

1. **이슈 3 — geny-executor 동시 패치 승인**: 근본 원인이
   `EVENT_DATA_TRUNCATE = 500` 이 `pipeline.complete.result` 에까지
   적용된 데서 비롯되므로 진짜 fix 는 geny-executor 쪽 PR
   (PR #4-A). Geny 쪽 (PR #4-B) 은 방어 패치 + executor 버전 업.
   geny-executor repo 에 패치를 내는 것이 맞는지 확인 부탁.
2. 이슈 2 의 "Stretch: manifest 기반 동적 stage 표시" 는 이번
   사이클 범위에 포함할지? (기본 답: 별도 사이클 — 이번엔 배지 +
   drill-down 까지.)
3. 탭 통합 (이슈 1) 후 deep-link 가 `?tab=builder` 같은 URL 로
   구현돼 있다면 외부 북마크 호환을 위해 `?tab=environments&builderEnvId=X`
   리라우트 유지. (현재 코드가 URL query 파라미터를 쓰는지 먼저
   확인 필요.)
