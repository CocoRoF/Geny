# Geny — Project Documentation

Geny 프로젝트의 상위 문서 인덱스. 백엔드 내부 아키텍처 문서는 [`backend/docs/`](../backend/docs/README.md) 참조.

## 현재 상태 (2026-04-24 기준)

Geny backend 는 [`geny-executor`](https://github.com/CocoRoF/geny-executor) Pipeline 기반으로 통일되어 있다. Command / VTuber / Messenger 세 채널 모두 동일한 `execute_command()` 경로를 통해 `Pipeline.run()` 으로 수렴. LangGraph 흔적은 `_archive/langgraph-era/` 로 이동 완료.

- 전체 스냅샷 → [`CURRENT_STATE_REPORT.md`](CURRENT_STATE_REPORT.md)
- Executor 통합 보고서 → [`EXECUTOR_INTEGRATION_REPORT.md`](EXECUTOR_INTEGRATION_REPORT.md)
- 듀얼 에이전트 아키텍처 → [`DUAL_AGENT_ARCHITECTURE_PLAN.md`](DUAL_AGENT_ARCHITECTURE_PLAN.md)
- VTuber 아키텍처 리뷰 → [`VTUBER_ARCHITECTURE_REVIEW.md`](VTUBER_ARCHITECTURE_REVIEW.md)

## 레이아웃

```
docs/
├── README.md                  ← 이 파일
├── *.md                       ← 루트 = Current & Reference (최신)
├── planning/                  ← 진행 중 / 대기 중 계획
├── analysis/                  ← 완료된 조사·리뷰
└── _archive/                  ← 더 이상 유효하지 않은 히스토리
    ├── vtuber-porting-v1/
    ├── langgraph-era/
    ├── executor-migration-v1/
    └── debugging-logs/
```

### 루트 (Current & Reference)

실시간으로 유효한 상위 기술 문서. 새 문서는 카테고리가 불명확하면 먼저 여기에 두고, 시간이 지나 성격이 확정되면 `planning/` / `analysis/` / `_archive/` 로 이동.

| 문서 | 내용 |
|---|---|
| [`CURRENT_STATE_REPORT.md`](CURRENT_STATE_REPORT.md) | 전체 아키텍처 스냅샷 |
| [`EXECUTOR_INTEGRATION_REPORT.md`](EXECUTOR_INTEGRATION_REPORT.md) | geny-executor 통합 현황 |
| [`DUAL_AGENT_ARCHITECTURE_PLAN.md`](DUAL_AGENT_ARCHITECTURE_PLAN.md) | VTuber + Sub-Worker 이중 아키텍처 |
| [`VTUBER_ARCHITECTURE_REVIEW.md`](VTUBER_ARCHITECTURE_REVIEW.md) | VTuber 서브시스템 리뷰 |
| [`VTUBER_AVATAR_CREATION_GUIDE.md`](VTUBER_AVATAR_CREATION_GUIDE.md) | VTuber 아바타 제작 가이드 |
| [`OmniVoice_INTEGRATION.md`](OmniVoice_INTEGRATION.md) | OmniVoice TTS 통합 |
| [`Thinking_trigger.md`](Thinking_trigger.md) | Thinking trigger 개념 |
| [`broadcast_logic.md`](broadcast_logic.md) | 브로드캐스트 실행 흐름 |
| [`source_live2d_model.md`](source_live2d_model.md) | Live2D 모델 소싱 |

### `planning/` — 진행 중 / 대기 중 계획

구현 예정이거나 검토 중인 작업 계획. 실현되면 관련 리포트로 대체되고 `_archive/` 로 이동.

### `analysis/` — 완료된 조사·리뷰

특정 시점에 수행된 심층 분석. 재작업이 필요해지면 최상단에 "SUPERSEDED BY: …" 주석 후 `_archive/` 로 이동.

### `_archive/` — 히스토리

세부 이유는 [`_archive/README.md`](_archive/README.md) 참조.

## 사이클 로그

Sprint 단위 작업은 `../dev_docs/<YYYYMMDD>_<N>/` 하위 `analysis/`, `plan/`, `progress/` 에 기록. 최신 cycle: [`dev_docs/20260424_1/`](../dev_docs/20260424_1/) — *LangGraph-era legacy cleanup*.
