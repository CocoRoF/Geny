# 00 — Strategy

본 사이클의 전체 전략, Phase 순서, 두 레포의 버전 정책을 정의한다. **하위호환
shim / feature flag / legacy 병존** 은 일체 도입하지 않는다. 장기 유지보수
비용을 만든다는 이유 외에도, 두 경로 병존은 "어느 경로에서 테스트했는가" 를
흐릿하게 만들어 회귀를 숨긴다.

## 원칙

1. **Host 가 주인공이다**. Tool 인터페이스의 정의는 `geny-executor` 에 있어야
   하고, Geny 는 그 계약을 **consumer** 로서 충족한다.
2. **Manifest 는 단일 권위 있는 source of truth 이다**. 어떤 세션에서든 "무슨
   tool 이 활성화되어 있는가" 라는 질문은 manifest 만 보면 답이 나와야 한다.
3. **에러는 구조화되어 전파된다**. tool call 실패는 문자열로 평탄화되지 않고
   `ToolError(code, message, details)` 형태로 감싸진다. Logging 은 에러를
   삼키지 않는다.
4. **단일 경로, 한 번의 전환**. 새 구조가 들어오는 PR 에서 legacy 코드 경로를
   **함께** 제거한다. 두 경로가 잠깐이라도 동시에 존재하는 feature flag 를
   두지 않는다. 전환이 실패하면 PR 자체를 revert 한다.

## Phase 순서와 이유

Phase 는 "증상 진단을 방해하는 것 먼저 → 구조적 원인 → 그 위에 UX" 순서.

1. **Phase A — Host 계약 강화** (`plan/02`)
   - 입력 스키마 검증, structured error, tool 네임스페이스.
   - 이 장치들이 없으면 이후 변경의 효과를 측정할 수 없다.
2. **Phase B — MCP 수명주기** (`plan/03`)
   - manifest 로드 시점에 connect + list_tools 일체화.
3. **Phase C — 단일 tool surface** (`plan/01`)
   - `AdhocToolProvider` 훅을 도입하고, 같은 PR 에서 Geny 의 legacy
     `ToolRegistry()` 수동 register 블록 및 `GenyPresets(tools=...)` 분기를
     제거.
4. **Phase D — 관측성** (`plan/04`)
   - `(parse error)` swallower 제거, structured error 의 UI 표현.
5. **Phase E — 검증** (`plan/05`)
   - 스모크 / 수용 기준 / 회귀 방지 체크리스트.

## 두 레포의 버전 정책

- `geny-executor` 는 본 사이클에서 **minor 버전 bump + 명시적 breaking
  change** 로 배포한다 (예: v0.20.x → v0.22.0). 기존 API 시그니처가 바뀌는
  변경이 있으며, 이를 감추는 wrapper 는 두지 않는다.
- Geny `pyproject.toml` 의 `geny-executor` 하한을 v0.22.0 으로 올리고, 같은
  PR 에서 consumer 측 변경을 완결.
- 두 레포의 배포는 하나의 릴리스 윈도우에서 동기화하여 진행. executor 가 먼저
  배포되어도 Geny 가 새 버전을 pin 하기 전에는 의미가 없으므로, Geny PR 이
  머지되는 순간이 실질 cutover.

## Cutover 절차

1. `geny-executor` PR — 계약/MCP/추가 훅 변경을 한 번에. 단위 테스트 / 통합
   테스트 통과.
2. `geny-executor` v0.22.0 태깅 및 내부 경로(또는 로컬 editable install) 에
   반영.
3. Geny PR — 새 executor 버전을 pin. 같은 PR 에서:
   - `GenyToolProvider` 도입.
   - `AgentSession._build_pipeline` 의 legacy `ToolRegistry()` 수동 register
     블록 삭제.
   - `GenyPresets.*(tools=...)` 경로를 즉석 manifest + provider 경로로 교체.
   - `_format_tool_detail` swallower 제거.
4. 머지 후 수동 QA (Phase E 스모크) 일괄 수행.

## 실패 시 되돌리기

- 머지 후 스모크에서 회귀 발견 → 해당 PR 을 revert. feature flag 로 "숨긴
  채 복귀" 같은 옵션은 없다. 한 번의 revert 가 전환 전 상태로 되돌아간다.
- revert 후 원인을 분석하여 **다시 한 번에** 올바르게 PR 한다. 작은 조각으로
  쪼개 legacy 와 병존하게 만들지 않는다.

## 위험 요약

- **한 번에 전환의 부담**: Phase C PR 이 크다. 이를 줄이기 위해 **변경 폭은
  넓지만 의미 단위로 자체 검증이 되는 단일 변경** 이 되도록 설계한다 — 공통
  제너레이터 (`build_default_manifest`) 와 provider 구현을 먼저 safe refactor
  로 도입 (Phase A 종료 시점에 미리 머지 가능) 하고, Phase C 에서는 **switch
  over** 만 수행.
- **manifest 스키마 변경**: `ToolsSnapshot.external` 필드 추가 자체는 기존
  환경 문서 (디스크 저장) 의 load 를 깨지 않는다 (`from_dict` 가 unknown field
  에 관대하도록 유지). 하지만 기존 환경은 `external` 이 비어 있으므로, 마이
  그레이션 훅 (다음 항목) 으로 채워 넣는다.
- **기존 env_id 세션이 갑자기 tool 을 잃는 문제**: Phase C 머지 직후, 저장된
  env 들 중 legacy 경로에 의존하던 것들은 `tools.external` 이 비어 있어 Geny
  의 built-in 이 빠진 것으로 보인다. 이를 막기 위해 **단발 마이그레이션 스크립트**
  (`backend/scripts/migrate_environments_add_external_defaults.py`) 를 Phase C
  PR 에 포함. 기존 environment 파일을 읽어 Geny 기본 provider 이름들을
  `tools.external` 에 주입하고 저장. 마이그레이션이 끝나면 스크립트는 폐기.
- **두 레포 버전 드리프트**: Geny 가 구버전 executor 에 대해 import 할 가능성.
  해결: Geny `pyproject.toml` 에 `geny-executor>=0.22.0,<0.23.0` 과 같이 **상한
  도 함께** 지정해, 이하 환경에서 fail fast.

## 성공 지표

`index.md` 에 나열된 다섯 개의 Done 기준:

1. `env_id` 세션의 `news_search` 가 실제 JSON 결과를 돌려받는다.
2. `ToolsSnapshot` 만으로 tool 구성이 완결된다.
3. 알 수 없는 tool 호출이 structured error 로 전달된다.
4. MCP 서버 연결 실패는 **세션 시작 시** 드러난다.
5. `(parse error)` 문자열이 어떤 경로로도 사용자에게 노출되지 않는다.

Phase E 종료 시 다섯 기준 모두 충족 여부를 `progress/NN_....md` 최종 PR
기록에 명시.
