# Geny ↔ geny-executor v0.20.0 통합 작업 인덱스

이 문서는 `geny-executor` v0.20.0 (현재 PyPI 게시 최신)을 Geny에 완전 통합하기 위한
분석·계획·진행 기록의 최상단 내비게이션 허브다. 본 작업은 다음 세 축을 다룬다.

1. **Executor 구조 갱신** — Geny 가 고정 중인 `geny-executor>=0.8.3` 에서
   `geny-executor>=0.20.0` 으로의 점프. 파이프라인/세션/스테이지/툴 브릿지가
   전부 바뀐다.
2. **Memory 서브시스템 재통합** — Geny 의 자체 구현 (short/long/vector/
   curated/global/reflect/user_opsidian 등) 을 v0.20.0 의 `MemoryProvider`
   프로토콜 위로 재배치한다. Geny 가 쓰고 있던 11 개의 메모리 오퍼레이션은
   이제 executor 의 네이티브 레이어/케이퍼빌리티로 표현 가능하다.
3. **ENVIRONMENT 시스템 이식** — `geny-executor-web` v0.9.0 에서 검증된
   Environment/Manifest/Preset/Resolver 파이프라인을 Geny 에도 동일 형태로
   실장한다.

> **주의**: v0.20.0 통합 사이클 (2026-04-19 까지) 의 `plan/` 과 `progress/`
> 는 `dev_docs/20260419/` 로 이관되었다. 이후 작업은 `dev_docs/YYYYMMDD/`
> 단위로 분리된다.

## 폴더

- [dev_docs/20260419/analysis/](dev_docs/20260419/analysis/index.md) — 현재 시스템 사실 수집 (v0.20.0 통합 시 작성)
- [dev_docs/20260419/plan/](dev_docs/20260419/plan/index.md) — v0.20.0 통합 마이그레이션 계획
- [dev_docs/20260419/progress/](dev_docs/20260419/progress/index.md) — v0.20.0 통합 PR 단위 기록
- [dev_docs/20260420/](dev_docs/20260420/) — post-v0.20.0 추가 작업 (탭 통합, 세션 그래프 env 표시, VTuber 챗 버그 등)

## 참조

- `geny-executor` v0.20.0 소스: `/home/geny-workspace/geny-executor`
- `geny-executor-web` v0.9.0 소스 (거울/검증 레퍼런스): `/home/geny-workspace/geny-executor-web`
- 요구사항 스펙 문서: `geny-executor-web/docs/MEMORY_ARCHITECTURE.md`
