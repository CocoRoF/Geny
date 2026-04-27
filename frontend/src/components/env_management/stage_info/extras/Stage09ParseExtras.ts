/**
 * Stage 9 (parse) — splits the LLM response into typed segments
 * (text / tool_use / thinking) and detects the completion signal.
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default — Anthropic content blocks',
      body: 'DefaultParser reads the content blocks Anthropic returns (text / tool_use / thinking). Standard for Claude 4 / Opus / Sonnet / Haiku models.',
    },
    {
      title: 'Strict tool-only output',
      body: 'StrictToolParser rejects responses that contain plain text alongside tool_use blocks — useful when you want the agent to ALWAYS call a tool and never narrate.',
    },
    {
      title: 'Custom completion signal',
      body: 'Replace the regex SignalDetector with a JsonSignalDetector if your prompt instructs the model to emit `{"done": true}` instead of `[SIGNAL: detail]`.',
    },
  ],
  configurations: [
    {
      name: 'Default',
      summary: 'Standard parser + regex signal.',
      highlights: [
        'parser: DefaultParser',
        'signal_detector: regex',
      ],
    },
    {
      name: 'Tool-only agent',
      summary: 'Reject text + tool_use mixed responses.',
      highlights: [
        'parser: StrictToolParser',
        'signal_detector: regex',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'Parse failure leaves response orphaned',
      body: 'If the parser rejects a response (StrictToolParser, schema mismatch), Stage 14 sees no progress and the loop spins until max_iterations. Always log parse failures.',
    },
    {
      title: 'Signal detector regex too greedy',
      body: 'A regex like `\\[SIGNAL.*\\]` matches ANY bracketed text — the model can accidentally trigger termination by quoting its own output. Anchor the regex tightly.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s09_parse/strategy.py',
      description: 'Parser + signal_detector slot definitions.',
    },
  ],
  relatedStages: [
    {
      order: 6,
      reason: 'Stage 6 produces the raw response Stage 9 parses.',
    },
    {
      order: 8,
      reason: 'Stage 8 (think) handles the thinking segment Stage 9 isolates.',
    },
    {
      order: 10,
      reason: 'Stage 10 (tools) executes the tool_use segments Stage 9 isolates.',
    },
    {
      order: 14,
      reason: 'Stage 14 (evaluate) reads Stage 9\'s completion signal to decide whether to loop or terminate.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '기본 — Anthropic content block',
      body: 'DefaultParser 가 Anthropic 이 반환하는 content block (text / tool_use / thinking) 을 읽습니다. Claude 4 / Opus / Sonnet / Haiku 모델 표준.',
    },
    {
      title: '엄격한 도구 전용 출력',
      body: 'StrictToolParser 는 tool_use 블록과 함께 일반 텍스트가 있는 응답을 거부합니다 — 에이전트가 항상 도구를 호출하고 절대 서술하지 않게 하고 싶을 때 유용.',
    },
    {
      title: '커스텀 완료 신호',
      body: '프롬프트가 모델에 `[SIGNAL: detail]` 대신 `{"done": true}` 를 emit 하도록 지시한다면 regex SignalDetector 를 JsonSignalDetector 로 교체.',
    },
  ],
  configurations: [
    {
      name: '기본',
      summary: '표준 파서 + regex 신호.',
      highlights: [
        'parser: DefaultParser',
        'signal_detector: regex',
      ],
    },
    {
      name: '도구 전용 에이전트',
      summary: '텍스트 + tool_use 혼합 응답 거부.',
      highlights: [
        'parser: StrictToolParser',
        'signal_detector: regex',
      ],
    },
  ],
  pitfalls: [
    {
      title: '파싱 실패 시 응답 고아 처리',
      body: '파서가 응답을 거부하면 (StrictToolParser, 스키마 불일치) Stage 14 가 진척을 보지 못하고 max_iterations 까지 루프가 도는 현상. 파싱 실패는 항상 로그하세요.',
    },
    {
      title: '신호 감지 regex 가 너무 탐욕적',
      body: '`\\[SIGNAL.*\\]` 같은 regex 는 어떤 대괄호 텍스트든 매칭 — 모델이 자기 출력을 인용하다 실수로 종료를 트리거할 수 있습니다. regex 를 단단히 anchor 하세요.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s09_parse/strategy.py',
      description: 'Parser + signal_detector 슬롯 정의.',
    },
  ],
  relatedStages: [
    {
      order: 6,
      reason: 'Stage 6 이 Stage 9 가 파싱할 raw 응답을 생산.',
    },
    {
      order: 8,
      reason: 'Stage 8 (think) 가 Stage 9 가 분리한 thinking 세그먼트를 처리.',
    },
    {
      order: 10,
      reason: 'Stage 10 (tools) 가 Stage 9 가 분리한 tool_use 세그먼트를 실행.',
    },
    {
      order: 14,
      reason: 'Stage 14 (evaluate) 가 Stage 9 의 완료 신호를 읽어 루프/종료 결정.',
    },
  ],
};

export const stage09Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
