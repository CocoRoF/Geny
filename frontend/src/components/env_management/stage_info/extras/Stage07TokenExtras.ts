/**
 * Stage 7 (token) — token bookkeeping. Counts the assembled request +
 * the LLM response, updates running cost tally, surfaces budget
 * status to Stage 14 (evaluate) for termination decisions.
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default — accurate accounting',
      body: 'Use ApiResponseCounter. Reads the official input_tokens / output_tokens / cache_read_tokens fields the Anthropic API returns. Free, exact.',
    },
    {
      title: 'Pre-flight estimate (local heuristic)',
      body: 'Use HeuristicCounter when you need a token count BEFORE sending — for instance to short-circuit on overly long requests. ~5% accuracy on English / Korean text.',
    },
  ],
  configurations: [
    {
      name: 'Production — exact counting',
      summary: 'Default Anthropic API counter.',
      highlights: ['counter: ApiResponseCounter'],
    },
    {
      name: 'Pre-flight cap',
      summary: 'Heuristic + reject if estimate > budget.',
      highlights: [
        'counter: HeuristicCounter',
        'config.reject_if_over_budget: true',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'Disabling Stage 7 hides cost from Stage 14',
      body: 'Without Stage 7 the running cost tally stops updating, so Stage 14 (evaluate) cannot enforce cost_budget_usd. Loops can run away unchecked.',
    },
    {
      title: 'Heuristic counter on multilingual text',
      body: 'Heuristic divides chars by 4. CJK text is closer to 1.5–2 chars per token, so estimates over-count by ~2x. Either use the API counter, or tune the divisor in config.chars_per_token.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s07_token/strategy.py',
      description: 'Counter slot + ApiResponseCounter / HeuristicCounter.',
    },
  ],
  relatedStages: [
    {
      order: 14,
      reason: 'Stage 14 (evaluate) reads the cumulative token / cost tally Stage 7 maintains to decide loop termination.',
    },
    {
      order: 5,
      reason: 'Stage 5 (cache) hits reduce the input token count Stage 7 sees on subsequent turns.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '기본 — 정확한 회계',
      body: 'ApiResponseCounter 사용. Anthropic API 가 반환하는 공식 input_tokens / output_tokens / cache_read_tokens 필드를 읽습니다. 무료, 정확.',
    },
    {
      title: '사전 추정 (로컬 휴리스틱)',
      body: '전송 전에 토큰 수가 필요할 때 HeuristicCounter — 예: 너무 긴 요청을 단락 (short-circuit). 영/한 텍스트 ~5% 오차.',
    },
  ],
  configurations: [
    {
      name: '프로덕션 — 정확한 카운팅',
      summary: '기본 Anthropic API 카운터.',
      highlights: ['counter: ApiResponseCounter'],
    },
    {
      name: '사전 상한',
      summary: '휴리스틱 + 추정이 예산 초과면 거부.',
      highlights: [
        'counter: HeuristicCounter',
        'config.reject_if_over_budget: true',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'Stage 7 비활성화 시 Stage 14 가 비용을 못 봄',
      body: 'Stage 7 없이는 누적 비용 집계가 멈춰서 Stage 14 (evaluate) 가 cost_budget_usd 를 강제할 수 없습니다. 루프가 무제한 도주 가능.',
    },
    {
      title: '다국어 텍스트의 휴리스틱 카운터',
      body: '휴리스틱은 문자 수 / 4. CJK 텍스트는 토큰당 1.5-2 문자에 가까워 추정이 ~2배 과대 계산됩니다. API 카운터를 쓰거나 config.chars_per_token 으로 분모를 조정하세요.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s07_token/strategy.py',
      description: 'Counter 슬롯 + ApiResponseCounter / HeuristicCounter.',
    },
  ],
  relatedStages: [
    {
      order: 14,
      reason: 'Stage 14 (evaluate) 가 Stage 7 이 유지하는 누적 토큰/비용 집계를 읽어 루프 종료를 결정.',
    },
    {
      order: 5,
      reason: 'Stage 5 (cache) 적중은 후속 턴에서 Stage 7 이 보는 입력 토큰 수를 감소시킵니다.',
    },
  ],
};

export const stage07Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
