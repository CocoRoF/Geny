/**
 * Stage 16 (loop) — the actual loop-back mechanism. When Stage 14
 * decides "continue", Stage 16 routes execution back to Stage 2.
 * When Stage 14 decides "terminate", Stage 16 falls through to Phase C.
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default — straight loop-back',
      body: 'StraightLoop simply re-enters Stage 2 with the updated state. No transformation. Standard for almost every agent.',
    },
    {
      title: 'Conditional re-entry',
      body: 'ConditionalLoop applies a transform to state before re-entering — for instance summarising the last turn into a single message before re-entering Stage 2 to keep the conversation lean.',
    },
  ],
  configurations: [
    {
      name: 'Default',
      summary: 'Re-enter Stage 2 verbatim.',
      highlights: ['loop: StraightLoop'],
    },
    {
      name: 'Compress on loop',
      summary: 'Summarise the last turn before re-entering.',
      highlights: ['loop: ConditionalLoop', 'config.compress_on_loop: true'],
    },
  ],
  pitfalls: [
    {
      title: 'Disabling Stage 16 forces single-turn',
      body: 'Without Stage 16 the loop never closes — Stage 14\'s "continue" decision has nowhere to land, so the pipeline always falls through to emit / yield. Effectively single-turn.',
    },
    {
      title: 'ConditionalLoop with aggressive compression',
      body: 'Compressing aggressively on every loop loses fidelity over many turns. Pair with Stage 18 / Stage 19 so the original detail still lives somewhere.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s16_loop/strategy.py',
      description: 'StraightLoop / ConditionalLoop slot definitions.',
    },
  ],
  relatedStages: [
    {
      order: 14,
      reason: 'Stage 14 (evaluate) decides whether Stage 16 actually loops or skips.',
    },
    {
      order: 2,
      reason: 'Stage 16 routes back to Stage 2 (context) on a continue decision.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '기본 — 직선 loop-back',
      body: 'StraightLoop 가 단순히 갱신된 state 로 Stage 2 재진입. 변환 없음. 거의 모든 에이전트의 표준.',
    },
    {
      title: '조건부 재진입',
      body: 'ConditionalLoop 가 재진입 전에 state 에 변환 적용 — 예: 마지막 턴을 단일 메시지로 요약한 후 Stage 2 재진입으로 대화 간결 유지.',
    },
  ],
  configurations: [
    {
      name: '기본',
      summary: 'Stage 2 그대로 재진입.',
      highlights: ['loop: StraightLoop'],
    },
    {
      name: '루프 시 압축',
      summary: '재진입 전 마지막 턴 요약.',
      highlights: ['loop: ConditionalLoop', 'config.compress_on_loop: true'],
    },
  ],
  pitfalls: [
    {
      title: 'Stage 16 비활성화 시 single-turn 강제',
      body: 'Stage 16 없이는 루프가 닫히지 않음 — Stage 14 의 "계속" 결정이 도착할 곳이 없어 파이프라인이 항상 emit / yield 로 떨어짐. 사실상 single-turn.',
    },
    {
      title: '공격적 압축의 ConditionalLoop',
      body: '매 루프마다 공격적 압축은 다중 턴에서 fidelity 손실. Stage 18 / Stage 19 와 페어링해서 원본 디테일이 어딘가에 남도록.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s16_loop/strategy.py',
      description: 'StraightLoop / ConditionalLoop 슬롯 정의.',
    },
  ],
  relatedStages: [
    {
      order: 14,
      reason: 'Stage 14 (evaluate) 가 Stage 16 이 실제로 루프할지 건너뛸지 결정.',
    },
    {
      order: 2,
      reason: 'Stage 16 이 계속 결정 시 Stage 2 (context) 로 라우팅.',
    },
  ],
};

export const stage16Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
