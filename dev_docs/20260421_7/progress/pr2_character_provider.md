# PR-X1-2 · `feat/character-persona-provider` — 진행 기록

**Date.** 2026-04-21
**Status.** Implemented, 14 new cases pass (총 28 pass).

## 적용된 변경

### 신규 모듈
- `backend/service/persona/character_provider.py` — `CharacterPersonaProvider`.
  - `set_static_override(session_id, text|None)` — SD2 대체 (PUT /system-prompt).
  - `set_character(session_id, name)` — SD1 대체 (`prompts/vtuber_characters/{name}.md`
    → `default.md` fallback + cache). 빈 파일 / 누락 silently skip.
  - `append_context(session_id, text)` — SD3 대체 (sub-worker delegation notice).
    중복 append 방지.
  - `reset(session_id)` — restore/shutdown 경로에서 상태 초기화.
  - `resolve(state, session_meta)` — role 분기 (`is_vtuber`), adaptive 는 worker 만,
    static override > default, character append, context append 순서 고정.
  - `cache_key` — role/override/character/ctx flag 4자로 요약.
- `backend/service/persona/__init__.py` — `CharacterPersonaProvider` re-export 추가.

### 신규 테스트
- `backend/tests/service/persona/test_character_provider.py` (14 cases).
  Protocol 부합, 기본 페르소나 (vtuber / worker), static override, character 파일 로드
  및 fallback, 누락 dir, append_context 중복 방지, 세션 격리, reset, cache_key 변화,
  파일 캐싱 동작 검증.

## 회귀 위험

0 — 여전히 경로 미사용. `AgentSession._build_pipeline` 교체는 PR-X1-3.

## 다음 PR

**PR-X1-3 · `refactor/remove-system-prompt-sidedoors`** — 5 사이트 철거 + AgentSession
가 `CharacterPersonaProvider` + `DynamicPersonaSystemBuilder` 를 쓰도록 교체.
