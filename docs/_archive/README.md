# Archived Documents

더 이상 유효하지 않지만 히스토리 보존용으로 남긴 문서들. 삭제하지 않는 이유: 과거 의사결정 맥락 (왜 이 설계를 선택했나 / 무엇을 버렸나) 은 git history 보다 이 문서들에 더 잘 남아있음.

새로 참고할 용도가 아니라 과거 결정을 재추적할 때만 읽는 폴더.

## `vtuber-porting-v1/`

2026-01~03 Geny 에 VTuber 기능을 이식할 때 작성한 초기 기획서·리포트. AIRI 프로젝트 참조 구현 분석 포함. 이식은 완료되어 현재는 [`../VTUBER_ARCHITECTURE_REVIEW.md`](../VTUBER_ARCHITECTURE_REVIEW.md) 와 실제 코드가 Source of Truth.

- `01_VTuber_렌더링_시스템_분석_리포트.md`
- `02_Geny_구조_및_이식_가능성_리포트.md`
- `03_VTuber_이식_세부_계획서.md`
- `AIRI_이식_구현_리포트.md`

## `langgraph-era/`

Geny backend 가 LangGraph StateGraph 기반이었던 시기 (2025~2026-03) 의 기획·분석 문서. 2026-04 에 `geny-executor` 로 통합되면서 전면 대체됨.

- `SESSION_CLI_LIFECYCLE_REPORT.md` — Claude CLI 기반 세션 생명주기 분석
- `OPTIMIZED_GRAPH_ENHANCEMENT_PLAN.md` — LangGraph 그래프 최적화 계획
- `optimizing_model.md` — `ClaudeCLIChatModel` + `AgentSession._build_graph()` 시절 모델 최적화 노트 (2026-04-24 이동, 언급된 클래스들이 현재 모두 존재하지 않음)

## `executor-migration-v1/`

geny-executor 통합 1차 마이그레이션 (2026-03~04) 진행·완료 보고서. 이번 사이클 (20260424_1) 의 cleanup 은 이 마이그레이션 이후 남은 레거시를 정리하는 후속 작업.

- `MIGRATION_PROGRESS.md`, `MIGRATION_REPORT.md`
- `EXECUTION_AUDIT_V2.md`, `EXECUTION_FINAL_REPORT.md`

## `debugging-logs/`

특정 이슈 디버깅 과정에서 남은 단발성 로그·명령 모음. 해당 이슈는 이미 해소됨.

- `TTS_CUDA_ERROR_DIAGNOSTIC_REPORT.md`
- `tts_problem_0401.md`
- `GPT_SOVITS_DEBUG_COMMANDS.md`
