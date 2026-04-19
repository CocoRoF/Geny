# Progress 기록 규약

구현이 시작된 이후에만 이 폴더에 파일을 쌓는다. 원칙:

1. **1 PR = 1 파일**. 파일명은 `NN_<slug>.md` (예: `01_bump_executor_dep.md`).
2. 모든 파일은 최소한 다음 필드를 포함한다.
   - `Scope`, `PR Link`, `Summary`, `Follow-ups`.
3. PR 설명과 중복 서술하지 않는다. PR 설명은 "무엇/왜" 를, progress 문서는
   "이 시점까지의 누적 위치" 를 기록한다.
4. 분석/계획에서 파생된 스펙과 어긋나게 구현해야 했다면, 그 이유를
   `Follow-ups` 바로 위에 *Deviations* 블록으로 기록하고 `analysis/` 또는
   `plan/` 문서에 역참조를 건다.
5. 머지되지 않은 PR 은 여기 기록하지 않는다 (draft 는 branch 와 Task 로 관리).
