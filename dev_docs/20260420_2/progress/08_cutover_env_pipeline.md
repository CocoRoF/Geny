# 08 — Geny cutover, env_id half (PR8, Phase C)

- **Repo**: `Geny` (backend)
- **Plan 참조**: `plan/01_unified_tool_surface.md` §"단일 전환 계획"
  3단계 (env_id 측면만)
- **Branch**: `feat/cutover-v0220-env-pipeline`
- **PR**: [CocoRoF/Geny#139](https://github.com/CocoRoF/Geny/pull/139)
- **의존**: `geny-executor` v0.22.0 릴리즈 (PR5 #26),
  PR6 #135 (`GenyToolProvider`), PR7 #137 (logging swallower 제거).

## 변경 요지

Phase C 의 **env_id 절반**. Plan/01 §"단일 전환 계획" 3단계를 두 PR
로 쪼개서 다음과 같이 정리:

| 부분 | 본 PR | 후속 PR |
| --- | --- | --- |
| `pyproject.toml` pin → `>=0.22.0,<0.23.0` | ✅ | — |
| `EnvironmentService.instantiate_pipeline` 가 `from_manifest_async + adhoc_providers` 사용 | ✅ | — |
| `AgentSessionManager` 의 env_id 분기에서 `GenyToolProvider` 활성화 | ✅ | — |
| `AgentSession._build_pipeline` 의 `GenyPresets.*` 블록 삭제 | — | ⏭️ |
| `build_default_manifest` 의 `stages=[]` 채우기 + post-construction attach 헬퍼 | — | ⏭️ |

분리 사유는 §"왜 두 PR 로 쪼갰나" 참고.

## 추가 / 변경된 파일

1. **수정** `backend/pyproject.toml`, `backend/requirements.txt`
   - `geny-executor>=0.20.1` → `geny-executor>=0.22.0,<0.23.0`. PR5
     릴리즈가 minor bump 한 번에 4개의 breaking 을 묶었기 때문에
     강한 upper-bound 로 잠가 둠 (`<0.23.0`).

2. **수정** `backend/service/environment/service.py`
   - `instantiate_pipeline` 시그니처를 sync → async 로 변경하고
     `adhoc_providers: Sequence[Any] = ()` kwarg 추가.
   - 내부 호출도 `Pipeline.from_manifest` → `await Pipeline.
     from_manifest_async(manifest, api_key=..., strict=...,
     adhoc_providers=...)` 로 교체. PR3 의 fail-fast MCP 와 PR4 의
     external-tool 등록이 한 entry-point 로 합쳐짐.

3. **수정** `backend/service/langgraph/agent_session_manager.py`
   - env_id 분기 (line 444-) 가 `self._tool_loader` 가 있을 때
     `GenyToolProvider(self._tool_loader)` 한 개를 만들어
     `instantiate_pipeline(adhoc_providers=[...])` 로 전달.
   - `await` 추가. 이미 async 컨텍스트 (`_create_agent_session` 가
     `await AgentSession.create(...)` 를 호출하던) 이라 별도 변경
     없음.

4. **수정** `backend/service/langgraph/geny_tool_provider.py`
   - 모듈 docstring 의 "Dead code" 표현을 제거하고 "Active in env_id
     sessions" 로 교체. non-env_id 경로는 여전히 GenyPresets 사용
     중이라는 점을 명시.

5. **수정** `backend/service/langgraph/default_manifest.py`
   - 모듈 docstring 을 "Still inactive after the Phase C cutover PR"
     로 정직하게 갱신. 후속 PR 이 무엇을 채워야 하는지 (stages +
     attach 헬퍼) 를 명시.

## 검증

- `python3 -m py_compile` — 6 개 수정 파일 모두 성공.
- v0.22.0 venv (`/home/geny-workspace/geny-executor/.venv`) 에서
  smoke:
  - `geny_executor.__version__ == "0.22.0"` ✅
  - `isinstance(GenyToolProvider(None), AdhocToolProvider) is True` —
    Protocol 호환 유지 (PR6 의 duck-typing 설계가 환경 이동 후에도
    유효함을 확인).
  - `inspect.iscoroutinefunction(EnvironmentService.instantiate_pipeline)`
    `is True` — async 시그니처 정착.
  - 시그니처에 `adhoc_providers: Sequence[Any] = ()` 노출.
  - `build_default_manifest("worker_adaptive",
    external_tool_names=["news_search"])` → `tools.external ==
    ["news_search"]` 로 정확히 round-trip. (manifest stages 는 여전히
    비어 있음 — 후속 PR 의 작업.)

## 왜 두 PR 로 쪼갰나

Plan/01 §"단일 전환 계획" 3단계는 한 PR 안에서 legacy `_build_pipeline`
까지 통째로 교체하는 것을 그렸지만, 코드를 깊게 본 뒤 두 PR 로 쪼개는
편이 안전하다고 판단:

- `GenyPresets.worker_adaptive(memory_manager=..., llm_reflect=...,
  curated_knowledge_manager=..., tool_context=...)` 는 **runtime
  객체** 들을 직접 stage 생성자에 주입한다 (`GenyMemoryRetriever
  (memory_manager,...)`, `GenyMemoryStrategy(memory_manager,...)`).
- 반면 `Pipeline.from_manifest_async` 는 manifest 의 stage 항목으로
  부터 **선언적** 으로 stage 를 생성하고 (`create_stage(name,
  artifact, **kwargs)` + `PipelineMutator.restore(snapshot)`),
  `memory_manager` / `llm_reflect` 같은 runtime 객체 직접 주입 훅이
  아직 노출돼 있지 않다.
- 따라서 `_build_pipeline` 교체는 **두 가지** 가 갖춰져야 가능:
  (a) `build_default_manifest` 의 `stages=[]` 가 worker_adaptive /
      vtuber 의 stage chain 을 정확히 표현.
  (b) Pipeline 조립 후 `pipeline.stages` 를 walk 하면서 Context /
      Memory stage 의 retriever / strategy / persistence 에
      `memory_manager` 와 callback 들을 주입하는 attach 헬퍼.

(a) 는 manifest schema 만으로도 가능하지만, (b) 는 `geny-executor`
쪽에 새로운 attach 인터페이스를 추가해야 깨끗히 되거나, Geny 쪽에서
stage 객체에 직접 접근해서 monkey-patch 하는 추한 형태로 만들어야
한다. 이 결정은 별도 사이클의 plan 에서 검토하기로 하고, 본 PR 은
env_id 측면 (manifest 가 이미 외부에서 정의되고 disk 에 있는 경로) 만
정리해서 안전하게 머지.

env_id 가 production 에서 가장 많이 쓰이는 경로이므로, 이 변경 만으로도
plan/01 §"성공 기준" 의 두 가지는 부분적으로 달성:
- `SessionEnvironmentTab` 의 tool 목록이 manifest 의 `tools.external`
  까지 표시 → 별도 frontend 작업 (이미 PR4 의 manifest schema 변경에
  맞춰져 있음) 으로 가능.
- `news_search` 가 manifest 경로 (env_id 세션) 에서 동작.

남은 성공 기준 ("env_id 기반과 non-env_id 세션 모두 동일한 tool 집합")
은 후속 PR 의 책임.

## 호환성

- `EnvironmentService.instantiate_pipeline` 의 시그니처가 sync →
  async 로 바뀌었음. **유일한 호출 지점** 은 `agent_session_manager.
  py:469` 이며 이미 async 컨텍스트라 즉시 `await` 적용. 외부에서 이
  메서드를 직접 호출하는 코드는 grep 으로 확인했을 때 없음.
- 기존에 `tools.external` 이 비어 있던 manifest 는 동작 변화 없음
  (provider 가 등록할 tool 이 없어 빈 registry 만 attach).
- `GenyPresets.*` 경로 (vtuber / worker_adaptive 의 non-env_id 세션)
  는 본 PR 에서 변경 없음.

## 후속 TODO (별도 plan/사이클)

1. `default_manifest.build_default_manifest` 의 `stages=[]` 채우기.
   - `worker_adaptive`: context, system, guard, cache, think, parse,
     tool, evaluate(BinaryClassify), loop(max_turns), memory, yield.
   - `vtuber`: context, system, guard, cache, evaluate, loop(10),
     memory, yield.
2. Post-construction attach 헬퍼 (Geny 또는 executor 쪽) 작성.
3. `_build_pipeline` 의 `GenyPresets.*` 블록 삭제 + 위 두 piece 호출.
4. `build_geny_tool_registry` / 그것을 호출하는 `agent_session_manager.
   py:434-442` 블록 정리 — env_id, non-env_id 모두 `GenyToolProvider`
   경로로 일원화되면 pre-built registry 가 더 이상 필요 없음.
5. Plan/01 §"성공 기준" 의 마지막 항목 ("동일한 tool 집합") E2E
   확인.
