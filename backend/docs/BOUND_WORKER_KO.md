# BoundWorker 계약

> 모든 VTuber 세션은 정확히 하나의 Worker 세션을 소유합니다. 이 문서는 그 바인딩이 어떻게 형성되고, 무엇이 그것을 유지하며, 어떻게 해제되는지에 대한 정식 명세입니다.

## 목적

VTuber 세션은 **페르소나 레이어**입니다 — 대화형, 캐릭터 유지, 대화 컨텍스트 최적화. Worker 세션은 **실행 레이어**입니다 — 툴 사용이 많고, 멀티턴, 실제 작업 수행에 최적화. 둘을 동시에 하려는 VTuber는 시스템 프롬프트가 비대해지고 페르소나 일관성이 떨어지며, 대화를 하려는 Worker도 마찬가지입니다.

Bound Worker 바인딩은 이 두 에이전트 분리를 **일급 기능(first-class)**으로 만듭니다:

- VTuber의 생성 요청이 Worker 설정을 함께 전달합니다 (`bound_worker_model`, `bound_worker_system_prompt`, `bound_worker_env_id`).
- 시스템이 VTuber 시작의 일부로 Worker를 원자적으로 생성합니다.
- Worker의 `session_id`가 VTuber의 시스템 프롬프트에 `## Bound Worker Agent` 블록으로 주입되어, VTuber가 복잡한 작업을 누구에게 위임할지 압니다.
- Worker의 `linked_session_id`는 VTuber를 역참조하므로, Worker가 작업을 마쳤을 때 누구에게 답변할지 압니다.

위임은 단순히 VTuber에서 바운드 Worker의 `session_id`로 `geny_send_direct_message`를 호출하는 것입니다. 답변은 `[CLI_RESULT]` 태그로 VTuber의 인박스에 도착하고, 페르소나에 맞게 요약됩니다.

---

## 불변성(Invariants)

### I1. 1:1 바인딩

VTuber 세션은 **정확히 하나의** 바운드 Worker를 가집니다. Worker 세션은 **최대 하나의** VTuber에 바인딩됩니다.

- 생성 시점에 강제됨: `AgentSessionManager.create_session`의 auto-pair 블록은 `session_type != "bound" and not linked_session_id` 가드 아래에서 VTuber 요청당 정확히 한 번 실행됩니다.
- 런타임에는 강제되지 않음: 호출자가 수동으로 `create_session(role=WORKER, linked_session_id=<vtuber_id>, session_type="bound")`을 두 번째로 호출하는 것은 막지 않습니다. 하지 마세요. **비목표(Non-goals)** 참고.

### I2. 생성 시점 바인딩

바인딩은 **VTuber 세션 생성 중에** 형성되며, 사후에 형성되지 않습니다. `bind_worker(vtuber_id, worker_id)` API는 없습니다.

- 이유: VTuber의 시스템 프롬프트는 빌드 시점에 Worker의 `session_id`를 알아야 합니다. 후기 바인딩은 VTuber의 파이프라인을 해체하고 재빌드해야 하는데, 이는 지원되지 않는 동작입니다.

### I3. 종료 시점 해제

양쪽 중 어느 쪽이 종료되든, 바인딩은 해제됩니다.

- **VTuber 종료**: 바운드 Worker는 말단(leaf)이며 세션 스토어의 일반 종료 경로로 정리 가능합니다. `agent_session_manager.stop_session(vtuber_id)`는 현재 바운드 Worker에 **연쇄적으로 작용하지 않습니다** — Worker는 살아남아 직접 호출될 수 있습니다. 이는 의도된 동작입니다 (아래 **고아 Worker** 실패 모드 참고).
- **Worker 종료**: VTuber의 `## Bound Worker Agent` 블록이 이제 죽은 세션을 참조합니다. 이후의 `geny_send_direct_message` 호출은 툴 레이어에서 `is_error=True`로 실패합니다. VTuber는 계속 기능하지만, 새 VTuber 세션이 생성될 때까지 위임은 깨진 상태입니다.

### I4. 핫스왑(Hot-swap) 불가

바운드 Worker의 `session_id`, `env_id`, `model`, `system_prompt`는 VTuber 생성 시점에 고정됩니다. VTuber를 살려둔 채로 Worker를 교체하는 API는 없습니다.

- Worker 설정을 변경하려면, 원하는 `bound_worker_*` 필드로 새 VTuber 세션을 생성하세요.

### I5. 바운드 Worker는 스스로 바인딩할 수 없음

`session_type == "bound"`인 Worker 세션은 또 다른 auto-pair 스폰을 트리거할 수 없습니다. `AgentSessionManager.create_session`의 재귀 가드는 다음과 같습니다:

```python
if (
    request.role == SessionRole.VTUBER
    and request.session_type != "bound"
    and not request.linked_session_id
):
    # 바운드 Worker 생성
```

`session_type != "bound"` 절이 핵심(load-bearing) 검사입니다. `not linked_session_id`는 링크를 이미 가진 요청을 잡아내는 보조 술어(belt-and-braces)입니다.

---

## 세션 라이프사이클

### 생성 시퀀스

```
Client POST /api/sessions
    │
    ▼
AgentSessionManager.create_session(role=VTUBER, bound_worker_env_id=...)
    │
    ├─ resolve_env_id(VTUBER, request.env_id)         → env_id: "template-vtuber-env"
    ├─ env_id로부터 manifest 빌드
    ├─ AgentSession 인스턴스화 (V1)
    ├─ attach_runtime(system_builder, tool_context, …)
    ├─ V1의 파이프라인 시작
    │
    ├─ 재귀 가드: role==VTUBER, session_type!="bound", linked_session_id is None  ✓
    │
    ├─ worker_request 빌드:
    │     role                      = WORKER
    │     env_id                    = request.bound_worker_env_id   (None 가능)
    │     model                     = request.bound_worker_model    (None 가능)
    │     system_prompt             = request.bound_worker_system_prompt
    │     linked_session_id         = V1.session_id
    │     session_type              = "bound"
    │
    ├─ 재귀: create_session(worker_request)
    │     └─ resolve_env_id(WORKER, request.env_id)   → None이면 "template-worker-env"
    │     └─ 가드: session_type=="bound"   ✗  (추가 스폰 없음)
    │     └─ W1 반환
    │
    ├─ V1._system_prompt에 "## Bound Worker Agent\n… session_id=`W1` …" 주입
    ├─ "🔗 Bound Worker created: W1" 로그
    │
    ▼
V1을 클라이언트에 반환. W1은 존재하며 V1에 역참조됨, DM으로 접근 가능.
```

### 종료 경로

| 시작자 | VTuber에 미치는 영향 | 바운드 Worker에 미치는 영향 |
|--------|---------------------|------------------------------|
| 클라이언트가 V1 중지 | V1 → STOPPED | W1은 계속 실행 (별도 중지 가능) |
| 클라이언트가 W1 중지 | V1 계속; 이후 W1로의 DM 실패 | W1 → STOPPED |
| V1 크래시 | V1 → ERROR | W1 영향 없음; 필요 시 수동으로 재연결 가능 |
| W1 크래시 | V1 계속; 다음 W1 DM은 툴 레이어에서 실패 | W1 → ERROR |
| Idle 모니터 | V1은 RUNNING 유지 (VTuber는 always-on) | W1은 RUNNING 유지 (바운드 Worker는 `AgentSession._is_always_on`을 통해 always-on 정책 공유) |

자동 연쇄 없음: 한쪽을 멈춰도 다른 쪽이 멈추지 않습니다. 양쪽 모두 종료하려면 `stop_session`을 두 번 호출하거나, 세션 스토어의 일괄 정리에 의존하세요.

### 재시작 후 복원

백엔드가 재시작되면 세션 복원 중에 `AgentSessionManager._build_system_prompt`가 다시 실행됩니다. VTuber의 경우 `role == "vtuber" and request.linked_session_id` 분기가 영속화된 `linked_session_id`를 사용해 `## Bound Worker Agent` 블록을 재주입합니다. 문구는 auto-pair 생성 경로와 동일하므로, VTuber는 재시작 전후로 같은 시스템 프롬프트를 읽습니다.

---

## env_id 해결

바운드 Worker는 다른 모든 세션과 마찬가지로 `resolve_env_id(role, explicit)`를 통과합니다 (`plan/02_default_env_ids.md` 참고):

| 전달된 `bound_worker_env_id` | 동작 |
|------------------------------|------|
| `None` (기본) | `resolve_env_id(WORKER, None)` → `ROLE_DEFAULT_ENV_ID[WORKER]` = `"template-worker-env"`로 폴백 |
| `"template-worker-env"` | 명시적 기본값; `None`과 동일하지만 문서화됨 |
| `"template-developer-env"` | 바운드 Worker가 developer manifest로 실행 (더 넓은 툴 세트, 개발 지향 시스템 프롬프트) |
| 알 수 없는 env_id | `resolve_env_id`가 VTuber 생성 시점에 예외 발생 → 클라이언트가 에러 수신, 부분 상태 없음 |

plan/02 아래에서 env가 stage 레이아웃을 소유하고, `manifest.tools.built_in` / `.external`이 툴 선택을 담당합니다. 바운드 Worker는 auto-pair 경로에서 `workflow_id` / `graph_name` / `tool_preset_id` 오버라이드가 없습니다 — 커스텀이 필요하면 새 env를 작성하세요.

---

## 실패 모드

### 전송 시점에 Worker 사용 불가

증상: VTuber가 `geny_send_direct_message(target_session_id=<W1>, …)`를 호출하고 `is_error=True`를 받음.

처리:
- MCP 툴 레이어가 VTuber의 에이전트 루프에 일반 툴 결과로 에러를 반환합니다.
- VTuber는 맹목적으로 재시도하지 말고 대화로 복구해야 합니다 ("뭔가 문제가 생긴 것 같아…").
- **자동 재시작 없음.** Worker를 재생성하는 것은 I4(핫스왑 불가)를 위반하며 VTuber의 시스템 프롬프트 재생성이 필요합니다.

### 인박스 가득 참

증상: 대상 세션의 인박스가 보존 기간을 초과할 때 `InboxManager.deliver`가 예외를 발생시키거나 잘라냅니다.

처리:
- 인박스 보존은 전역 정책입니다 (`SHARED_FOLDER.md`의 정리 규칙 참고 — 현재 인박스는 무제한 JSON 파일). 일반 사용에서는 오버플로가 예상되지 않습니다.
- 발생 시 생산자 측 툴 호출이 VTuber의 에이전트 루프에 에러를 전달합니다. 복구 경로는 "Worker 사용 불가"와 동일합니다.

### 툴 호출 타임아웃

증상: VTuber의 `geny_send_direct_message` 호출이 MCP 툴 타임아웃 내에 반환되지 않음 (단순 send는 기본 60초; 답변을 기다리는 `execute` 스타일 툴은 더 김).

처리:
- `geny_send_direct_message`는 fire-and-forget 방식입니다 — DM이 큐에 들어갔음만 확인하고, Worker가 처리했음을 확인하지 않습니다. 정상 경로: VTuber가 send 호출 → 즉시 반환 → Worker가 비동기로 처리 → Worker가 `[CLI_RESULT]` 태그로 자체 `geny_send_direct_message` 응답 → VTuber 인박스에 도착 → VTuber의 다음 에이전트 턴에서 인박스 비움.
- VTuber가 특정 결과를 기다리고 싶다면 페르소나를 유지한 채 ("잠시만, 알아볼게!") Worker가 끝났을 때 `[CLI_RESULT]` 트리거가 깨우도록 두어야 합니다.

### 고아 Worker (VTuber 사라짐, Worker 살아있음)

증상: VTuber 세션이 중지되거나 크래시됨; 바운드 Worker는 세션 스토어에 여전히 있음.

처리:
- Worker는 다른 세션의 직접 DM으로 계속 접근 가능합니다. 이는 **의도된 동작**입니다 — 운영자가 Worker를 독립적으로 디버그하거나 재사용할 수 있도록.
- 세션 스토어의 일괄 정리(`DELETE FROM sessions WHERE ended_at < NOW() - INTERVAL '7 days'`)가 결국 제거합니다. 고아 바운드 Worker에 특화된 더 짧은 TTL은 없습니다.

### 재귀 가드 실패

증상: VTuber 요청이 재귀 가드를 빠져나가 바운드 Worker의 무한 체인을 생성함.

처리:
- 가드는 `session_type != "bound" and not linked_session_id`입니다. 바운드 Worker 요청에 이 필드를 모두 설정하지 않는 버그가 이를 깨뜨릴 수 있습니다. PR 18 + 20의 스모크 테스트가 현재 가드의 유효성을 검증합니다.
- 만약 실제로 실패한다면, `SessionStore.count_active_sessions()`가 급증하고 idle 모니터 로그에 짧은 창 안에 많은 `🔗 Bound Worker created:` 라인이 표시됩니다. 폭주하는 세션을 수동으로 중지하세요.

---

## 비목표(Non-goals)

다음은 설계된 BoundWorker 계약의 **명시적 범위 외**입니다. 버그가 아니며, 우리가 구축하지 않기로 선택한 기능입니다.

### 다중 Worker 팬아웃(fan-out)

*"두 개의 바운드 Worker를 가진 VTuber — 하나는 코드용, 하나는 연구용."*

지원되지 않음. 바인딩은 불변성 I1에 의해 1:1입니다. 팬아웃을 근사하려면, 단일 Worker 자체가 `geny_send_direct_message`로 서브 세션에 위임할 수 있습니다 (바운드 세션뿐 아니라 어떤 세션이든 대상). 하지만 VTuber는 여전히 하나의 Worker만 봅니다.

### 핫스왑(Hot-swap)

*"VTuber를 재생성하지 않고 바운드 Worker 교체."*

지원되지 않음. 불변성 I4 참고. 런타임에 VTuber의 시스템 프롬프트를 재빌드하는 것을 평가했지만 거부했습니다 — 현재 executor(v0.26.0)에서 파이프라인을 해체하고 재연결하는 것이 멱등적이지 않기 때문입니다.

### VTuber 간 공유

*"리소스 절약을 위해 두 VTuber가 하나의 바운드 Worker 공유."*

지원되지 않음. Worker의 `linked_session_id`는 리스트가 아닌 단일 필드입니다. `[CLI_RESULT]`를 통한 역응답은 정확히 하나의 VTuber를 대상으로 합니다. 공유하려면 라우팅 레이어가 필요합니다.

### 동적 재바인딩(Dynamic rebind)

*"첫 VTuber가 끝나면 Worker를 다른 VTuber에 재바인딩."*

지원되지 않음. VTuber가 종료되면 그 바운드 Worker는 풀 리소스가 아닌 고아 Worker가 됩니다 (**실패 모드** 참고). 미래에 필요가 생기면 새 기능이지, 현재 계약의 수리가 아닙니다.

---

## 관련 코드

| 파일 | 바인딩에서의 역할 |
|------|-------------------|
| `service/claude_manager/models.py` | `CreateSessionRequest.bound_worker_model` / `_system_prompt` / `_env_id`; `session_type` enum 값에 `"bound"` 포함 |
| `service/langgraph/agent_session_manager.py` | `create_session`의 auto-pair 블록; 재귀 가드; 생성과 복원 시점의 프롬프트 주입 |
| `service/langgraph/agent_session.py` | `_session_type` 필드와 `_is_always_warm` 정책 (`"bound"` → not always warm) |
| `service/execution/agent_executor.py` | Worker 작업 완료 시 VTuber에게 `[CLI_RESULT]` 태그 답변 전송 |
| `service/vtuber/delegation.py` | VTuber 에이전트 루프에서 소비되는 `DelegationTag.CLI_RESULT` / `ACTIVITY_TRIGGER` 리터럴 |
| `service/vtuber/thinking_trigger.py` | VTuber가 바운드 Worker에게 위임할 `[ACTIVITY_TRIGGER]` 프롬프트 생성 |
| `controller/tts_controller.py` | TTS 출력 전에 `[CLI_RESULT]` / `[ACTIVITY_TRIGGER]` 태그 리터럴 제거 |
| `prompts/vtuber.md` | VTuber 페르소나 기본 프롬프트 — 위임 단락, 트리거 처리 |

## 관련 문서

- [`SESSIONS_KO.md`](SESSIONS_KO.md) — 일반 세션 라이프사이클, idle 모니터, 상태 머신
- [`PROMPTS_KO.md`](PROMPTS_KO.md) — 프롬프트 레이어 아키텍처와 토큰 예산
- [`EXECUTION_KO.md`](EXECUTION_KO.md) — 에이전트 executor, `[CLI_RESULT]` 발신, 툴 호출 흐름
- `dev_docs/20260420_3/plan/03_vtuber_worker_binding.md` — 이 계약을 만든 계획
- `dev_docs/20260420_3/plan/02_default_env_ids.md` — `resolve_env_id`와 역할별 기본값
