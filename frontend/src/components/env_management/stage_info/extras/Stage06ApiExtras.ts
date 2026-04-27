/**
 * Stage 6 (api) — supplementary detail content for the info modal.
 *
 * The single most-edited stage in any environment. Sourced from
 *   src/geny_executor/stages/s06_api/{strategy.py, artifact/default/stage.py}
 *   src/geny_executor/core/config.py (ModelConfig)
 *   src/geny_executor/core/environment.py (StageManifestEntry.model_override)
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default — pipeline-wide model',
      body: 'Leave model_override null. Stage 6 reads pipeline.model directly. Configure once in Global > Model and every stage that calls an LLM (api, context summarizer, memory reflective) uses it.',
    },
    {
      title: 'Heavier model just for the main turn',
      body: 'Set Stage 6 model_override to a stronger model (e.g. claude-opus-4-7 or claude-sonnet-4-7) while Stage 18 (memory) keeps the cheaper pipeline default. The expensive model only fires once per turn.',
    },
    {
      title: 'Headless preview / structured-output mode',
      body: 'Disabling Stage 6 entirely produces a "no LLM" pipeline — useful for replaying conversations against fixtures or for testing routing logic without burning tokens.',
    },
  ],
  configurations: [
    {
      name: 'Sonnet 4.6 — balanced',
      summary: 'Default for most agents.',
      highlights: [
        'model: claude-sonnet-4-6',
        'temperature: 0.7',
        'max_tokens: 4096',
      ],
    },
    {
      name: 'Opus 4.7 — premium reasoning',
      summary: 'For complex tool-using agents that need deeper planning.',
      highlights: [
        'model: claude-opus-4-7',
        'thinking_enabled: true',
        'thinking_budget_tokens: 8000',
        'thinking_type: enabled',
      ],
    },
    {
      name: 'Haiku 4.5 — cheap fast loop',
      summary: 'High-volume routine workflows where latency / $ matters.',
      highlights: [
        'model: claude-haiku-4-5',
        'temperature: 0.0',
        'max_tokens: 2048',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'thinking_enabled with low max_tokens silently truncates',
      body: 'Extended thinking eats from the same max_tokens budget as the visible response. If thinking_budget_tokens is 8000 and max_tokens is also 8192, the visible reply has only ~192 tokens — answers will be cut off. Rule of thumb: max_tokens ≥ thinking_budget_tokens × 2.',
    },
    {
      title: 'temperature + top_p set together',
      body: 'Anthropic API rejects both at once. Pick one. The frontend ModelConfigEditor only enables one input at a time, but a manually edited manifest can slip through.',
    },
    {
      title: 'Toggling Stage 6 off in production breaks tool calls',
      body: 'Stage 6 is the LLM call. Without it, Stage 9 (parse) sees no response, Stage 10 (tools) has nothing to execute, and the loop terminates immediately. Use single_turn or stateless flags instead if you want a "no-loop" agent.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / core/config.py',
      description: 'ModelConfig dataclass — every field surfaced by ModelConfigEditor.',
    },
    {
      label: 'geny-executor / stages/s06_api/strategy.py',
      description: 'LLMCaller slot. Default: AnthropicLLMCaller. The artifact picks which caller fires.',
    },
    {
      label: 'geny-executor / core/environment.py',
      description: 'StageManifestEntry.model_override — per-stage ModelConfig override.',
    },
  ],
  relatedStages: [
    {
      order: 2,
      reason: 'Stage 2 (context) can also use a model_override (cheaper summary model) so the context compaction step does not pay the Stage 6 model price.',
    },
    {
      order: 9,
      reason: 'Stage 9 (parse) consumes the LLM response Stage 6 produced.',
    },
    {
      order: 18,
      reason: 'Stage 18 (memory) reflective strategies have their own model_override — usually a cheap fast model since it summarises.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '기본 — 파이프라인 전역 모델',
      body: 'model_override 를 null 로 두면 6단계는 pipeline.model 을 직접 사용합니다. 전역 > 모델 한 번 설정으로 LLM 을 호출하는 모든 단계 (api, context summarizer, memory reflective) 가 같은 모델을 씁니다.',
    },
    {
      title: '메인 턴만 더 무거운 모델로',
      body: '6단계 model_override 를 더 강한 모델 (예: claude-opus-4-7 또는 claude-sonnet-4-7) 로 설정하고 18단계 (memory) 는 저렴한 파이프라인 기본값을 유지하세요. 비싼 모델은 턴당 한 번만 발화합니다.',
    },
    {
      title: '헤드리스 프리뷰 / 구조화 출력 모드',
      body: '6단계를 완전히 비활성화하면 "LLM 없는" 파이프라인이 됩니다 — fixtures 로 대화를 재생하거나 토큰 소모 없이 라우팅 로직을 테스트할 때 유용합니다.',
    },
  ],
  configurations: [
    {
      name: 'Sonnet 4.6 — 균형',
      summary: '대부분의 에이전트에 권장되는 기본값.',
      highlights: [
        'model: claude-sonnet-4-6',
        'temperature: 0.7',
        'max_tokens: 4096',
      ],
    },
    {
      name: 'Opus 4.7 — 프리미엄 추론',
      summary: '심층 계획이 필요한 복잡한 tool-using 에이전트.',
      highlights: [
        'model: claude-opus-4-7',
        'thinking_enabled: true',
        'thinking_budget_tokens: 8000',
        'thinking_type: enabled',
      ],
    },
    {
      name: 'Haiku 4.5 — 저렴/빠른 루프',
      summary: '지연/비용이 중요한 고빈도 루틴 워크플로우.',
      highlights: [
        'model: claude-haiku-4-5',
        'temperature: 0.0',
        'max_tokens: 2048',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'thinking_enabled + 낮은 max_tokens → silent 잘림',
      body: '확장 사고는 visible 응답과 같은 max_tokens 예산을 공유합니다. thinking_budget_tokens 가 8000 이고 max_tokens 도 8192 이면 보이는 답변은 ~192 토큰만 — 답이 잘립니다. 권장: max_tokens ≥ thinking_budget_tokens × 2.',
    },
    {
      title: 'temperature 와 top_p 동시 설정',
      body: 'Anthropic API 는 둘을 동시 거부합니다. 하나만 고르세요. 프론트의 ModelConfigEditor 는 한 번에 하나만 활성화하지만 수동 편집한 매니페스트는 빠져나갈 수 있습니다.',
    },
    {
      title: '운영 환경에서 6단계 끄면 도구 호출 깨짐',
      body: '6단계가 LLM 호출입니다. 끄면 9단계 (parse) 는 응답을 못 보고, 10단계 (tools) 는 실행할 게 없어 루프가 즉시 종료됩니다. "루프 없는" 에이전트가 필요하면 single_turn 또는 stateless 플래그를 쓰세요.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / core/config.py',
      description: 'ModelConfig dataclass — ModelConfigEditor 에 노출되는 모든 필드.',
    },
    {
      label: 'geny-executor / stages/s06_api/strategy.py',
      description: 'LLMCaller 슬롯. 기본: AnthropicLLMCaller. 어떤 caller 가 발화할지 artifact 가 결정.',
    },
    {
      label: 'geny-executor / core/environment.py',
      description: 'StageManifestEntry.model_override — 단계별 ModelConfig 오버라이드.',
    },
  ],
  relatedStages: [
    {
      order: 2,
      reason: '2단계 (context) 도 model_override 를 가질 수 있어 (저렴한 요약 모델) 컨텍스트 압축 단계가 6단계 모델 비용을 지불하지 않게 할 수 있습니다.',
    },
    {
      order: 9,
      reason: '9단계 (parse) 는 6단계가 생산한 LLM 응답을 소비합니다.',
    },
    {
      order: 18,
      reason: '18단계 (memory) reflective 전략도 자체 model_override 를 가집니다 — 요약하는 역할이라 보통 저렴/빠른 모델을 씁니다.',
    },
  ],
};

export const stage06Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
