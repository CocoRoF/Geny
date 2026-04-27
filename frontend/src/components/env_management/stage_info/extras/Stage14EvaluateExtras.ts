/**
 * Stage 14 (evaluate) — the loop terminator. Decides whether to feed
 * the result back to Stage 2 (continue looping) or fall through to
 * Phase C (emit / persist / yield).
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default — converge on completion signal',
      body: 'DefaultEvaluator terminates when Stage 9 detects the completion signal AND no pending tool calls remain. Standard for chat agents.',
    },
    {
      title: 'Step-bounded',
      body: 'Couple DefaultEvaluator with low pipeline.max_iterations (e.g. 3) so the agent gets at most N turns regardless of completion signal. Useful for "answer in three steps" workflows.',
    },
    {
      title: 'Score-threshold',
      body: 'ScoreEvaluator runs a cheap LLM check after each turn ("Is the user\'s question fully answered? 0-10"). Loop continues while score < threshold. Adds cost but improves quality on long tasks.',
    },
  ],
  configurations: [
    {
      name: 'Default chat',
      summary: 'Signal-driven termination + 50-iteration ceiling.',
      highlights: [
        'evaluator: DefaultEvaluator',
        'pipeline.max_iterations: 50',
      ],
    },
    {
      name: 'Cost-capped batch',
      summary: 'Hard cost cap, signal-driven within budget.',
      highlights: [
        'evaluator: DefaultEvaluator',
        'pipeline.max_iterations: 50',
        'pipeline.cost_budget_usd: 0.10',
      ],
    },
    {
      name: 'Tight 3-step agent',
      summary: 'Forced to wrap up within 3 turns.',
      highlights: [
        'evaluator: DefaultEvaluator',
        'pipeline.max_iterations: 3',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'max_iterations too low + signal not yet emitted',
      body: 'Hitting max_iterations terminates with truncate_status=hard_limit. Stage 17 (emit) sees the unfinished response. The user gets a half-baked answer. Either bump the limit or set the signal regex to be more permissive.',
    },
    {
      title: 'cost_budget_usd hit mid-tool-call',
      body: 'When the budget is exhausted mid-tool-execution, Stage 14 still terminates AFTER Stage 10 finishes the tool. You can\'t cancel an already-fired tool. Plan a generous buffer.',
    },
    {
      title: 'tool_review_flags ignored',
      body: 'Stage 11 reviewers append flags but Stage 14 doesn\'t auto-halt on them. Configure DefaultEvaluator.config.halt_on_flag_severity to actually use them.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s14_evaluate/strategy.py',
      description: 'Evaluator slot definitions.',
    },
    {
      label: 'geny-executor / core/config.py',
      description: 'PipelineConfig fields max_iterations / cost_budget_usd / context_window_budget — all the ceilings Stage 14 enforces.',
    },
  ],
  relatedStages: [
    {
      order: 7,
      reason: 'Stage 7 (token) maintains the cumulative cost tally Stage 14 reads to enforce cost_budget_usd.',
    },
    {
      order: 9,
      reason: 'Stage 9 (parse) detects the completion signal Stage 14 acts on.',
    },
    {
      order: 11,
      reason: 'Stage 11 (tool_review) flags surface in state.shared; Stage 14 can be configured to halt on them.',
    },
    {
      order: 16,
      reason: 'Stage 16 (loop) is the actual loop-back mechanism Stage 14 either triggers (continue) or skips (terminate).',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '기본 — 완료 신호 수렴',
      body: 'DefaultEvaluator 가 Stage 9 가 완료 신호를 감지하고 pending 도구 호출이 없을 때 종료. 채팅 에이전트 표준.',
    },
    {
      title: '스텝 제한',
      body: 'DefaultEvaluator 와 낮은 pipeline.max_iterations (예: 3) 조합으로 완료 신호 무관하게 N턴까지만. "3단계 안에 답변" 워크플로우에 유용.',
    },
    {
      title: '점수 임계',
      body: 'ScoreEvaluator 가 매 턴 후 저렴한 LLM 체크 ("사용자 질문이 완전히 답변됐는가? 0-10"). 점수 < 임계 동안 루프 지속. 비용 추가지만 긴 태스크에서 품질 향상.',
    },
  ],
  configurations: [
    {
      name: '기본 채팅',
      summary: '신호 기반 종료 + 50 반복 상한.',
      highlights: [
        'evaluator: DefaultEvaluator',
        'pipeline.max_iterations: 50',
      ],
    },
    {
      name: '비용 상한 배치',
      summary: '하드 비용 상한, 예산 내 신호 기반.',
      highlights: [
        'evaluator: DefaultEvaluator',
        'pipeline.max_iterations: 50',
        'pipeline.cost_budget_usd: 0.10',
      ],
    },
    {
      name: '빡빡한 3-step 에이전트',
      summary: '3턴 안에 강제 마무리.',
      highlights: [
        'evaluator: DefaultEvaluator',
        'pipeline.max_iterations: 3',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'max_iterations 너무 낮음 + 신호 미발화',
      body: 'max_iterations 도달 시 truncate_status=hard_limit 으로 종료. Stage 17 (emit) 이 미완성 응답을 봄. 사용자가 반쯤 익은 답변을 받음. 상한을 올리거나 signal regex 를 더 관대하게.',
    },
    {
      title: '도구 호출 중 cost_budget_usd 초과',
      body: '도구 실행 중 예산이 소진되면 Stage 14 는 여전히 Stage 10 도구 완료 후 종료. 이미 발화된 도구는 취소 불가. 넉넉한 버퍼를 두세요.',
    },
    {
      title: 'tool_review_flags 무시됨',
      body: 'Stage 11 리뷰어가 flag 를 추가하지만 Stage 14 는 자동 중단하지 않음. DefaultEvaluator.config.halt_on_flag_severity 를 설정해야 실제 사용.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s14_evaluate/strategy.py',
      description: 'Evaluator 슬롯 정의.',
    },
    {
      label: 'geny-executor / core/config.py',
      description: 'PipelineConfig 의 max_iterations / cost_budget_usd / context_window_budget — Stage 14 가 강제하는 모든 상한.',
    },
  ],
  relatedStages: [
    {
      order: 7,
      reason: 'Stage 7 (token) 가 Stage 14 가 cost_budget_usd 강제 시 읽는 누적 비용 집계 유지.',
    },
    {
      order: 9,
      reason: 'Stage 9 (parse) 가 Stage 14 가 작용하는 완료 신호 감지.',
    },
    {
      order: 11,
      reason: 'Stage 11 (tool_review) flag 가 state.shared 에 있고 Stage 14 가 이에 따라 중단하도록 설정 가능.',
    },
    {
      order: 16,
      reason: 'Stage 16 (loop) 가 Stage 14 가 트리거 (계속) 또는 건너뛰기 (종료) 하는 실제 loop-back 메커니즘.',
    },
  ],
};

export const stage14Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
