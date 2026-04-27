/**
 * Stage 8 (think) — handles Claude's extended thinking blocks
 * (Opus 4 / Sonnet 4+ "thinking" feature). Extracts thinking content
 * from the response, decides whether to surface it to the user, and
 * may persist it for downstream context.
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Hidden thinking — production default',
      body: 'OmittedDisplay strips thinking blocks from the user-visible response. The model still benefits from extended reasoning; users see only the final answer.',
    },
    {
      title: 'Summarised thinking (debug / power users)',
      body: 'SummarizedDisplay keeps a 1-2 sentence digest of the thinking visible. Helpful for power users who want to audit the chain-of-thought without reading every internal token.',
    },
    {
      title: 'No thinking',
      body: 'Disable Stage 8 (or set Model.thinking_enabled=false) for fast / cheap turns where deep reasoning isn\'t worth the latency hit.',
    },
  ],
  configurations: [
    {
      name: 'Default — hidden',
      summary: 'Thinking on, hidden from user.',
      highlights: [
        'Stage 6 model_override.thinking_enabled: true',
        'Stage 8 display: OmittedDisplay',
      ],
    },
    {
      name: 'Debug visible',
      summary: 'Thinking digest visible to user.',
      highlights: [
        'Stage 6 model_override.thinking_enabled: true',
        'Stage 8 display: SummarizedDisplay',
      ],
    },
    {
      name: 'Off',
      summary: 'No extended thinking at all.',
      highlights: [
        'Stage 6 model_override.thinking_enabled: false',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'thinking_budget_tokens too low',
      body: 'Below ~2000 tokens of thinking budget, the model may not have room to actually reason — the thinking block is empty and you paid for nothing. Either give it ≥ 4000 or turn thinking off.',
    },
    {
      title: 'Surfacing raw thinking to end users',
      body: 'Raw chain-of-thought can leak system prompt details, intermediate confused states, or sensitive tool args. Stick to OmittedDisplay or SummarizedDisplay for user-facing surfaces.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s08_think/strategy.py',
      description: 'Display slot + OmittedDisplay / SummarizedDisplay / RawDisplay.',
    },
    {
      label: 'geny-executor / core/config.py (ModelConfig)',
      description: 'thinking_enabled, thinking_budget_tokens, thinking_type fields.',
    },
  ],
  relatedStages: [
    {
      order: 6,
      reason: 'Stage 6 enables thinking via ModelConfig; Stage 8 processes the thinking block in the response.',
    },
    {
      order: 9,
      reason: 'Stage 9 (parse) splits the response into thinking + tool_use + text segments; Stage 8 owns the thinking segment.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '숨겨진 사고 — 프로덕션 기본',
      body: 'OmittedDisplay 가 사용자에게 보이는 응답에서 사고 블록을 제거합니다. 모델은 확장 추론의 이점을 누리고, 사용자는 최종 답변만 봅니다.',
    },
    {
      title: '요약된 사고 (디버그 / 파워 유저)',
      body: 'SummarizedDisplay 가 사고의 1-2 문장 digest 를 보여줍니다. 모든 내부 토큰을 읽지 않고도 chain-of-thought 를 감사하고 싶은 파워 유저에게 유용.',
    },
    {
      title: '사고 없음',
      body: '깊은 추론보다 지연이 더 중요한 빠른/저렴한 턴이라면 Stage 8 비활성화 (또는 Model.thinking_enabled=false).',
    },
  ],
  configurations: [
    {
      name: '기본 — 숨김',
      summary: '사고 켜짐, 사용자에게 숨김.',
      highlights: [
        'Stage 6 model_override.thinking_enabled: true',
        'Stage 8 display: OmittedDisplay',
      ],
    },
    {
      name: '디버그 표시',
      summary: '사고 digest 사용자에게 표시.',
      highlights: [
        'Stage 6 model_override.thinking_enabled: true',
        'Stage 8 display: SummarizedDisplay',
      ],
    },
    {
      name: '끔',
      summary: '확장 사고 사용 안 함.',
      highlights: [
        'Stage 6 model_override.thinking_enabled: false',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'thinking_budget_tokens 가 너무 낮음',
      body: '~2000 토큰 미만이면 모델이 실제로 추론할 공간이 없어 사고 블록이 비어 있고 돈만 낭비합니다. ≥ 4000 을 주거나 사고를 끄세요.',
    },
    {
      title: 'raw 사고를 최종 사용자에게 노출',
      body: 'raw chain-of-thought 는 시스템 프롬프트 세부, 중간 혼란 상태, 민감한 도구 인자를 누설할 수 있습니다. 사용자 대면 표면에서는 OmittedDisplay 또는 SummarizedDisplay 를 고수하세요.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s08_think/strategy.py',
      description: 'Display 슬롯 + OmittedDisplay / SummarizedDisplay / RawDisplay.',
    },
    {
      label: 'geny-executor / core/config.py (ModelConfig)',
      description: 'thinking_enabled, thinking_budget_tokens, thinking_type 필드.',
    },
  ],
  relatedStages: [
    {
      order: 6,
      reason: 'Stage 6 가 ModelConfig 로 사고를 활성화; Stage 8 이 응답의 사고 블록을 처리.',
    },
    {
      order: 9,
      reason: 'Stage 9 (parse) 가 응답을 thinking + tool_use + text 세그먼트로 분리; Stage 8 이 thinking 세그먼트를 담당.',
    },
  ],
};

export const stage08Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
