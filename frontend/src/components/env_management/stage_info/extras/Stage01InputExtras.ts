/**
 * Stage 1 (input) — supplementary detail content for the info modal.
 *
 * NOTE: Stage 1 is about validation + normalization. The system
 * prompt lives in Stage 3. An earlier version of this file conflated
 * the two — corrected in cycle 20260427_3.
 *
 * Sourced from geny-executor's
 *   src/geny_executor/stages/s01_input/{strategy.py, artifact/default/stage.py}
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default — text chat agents',
      body: 'Most agents leave Stage 1 with the DefaultValidator + DefaultNormalizer pair. Plain-text questions, code snippets, single-language conversation all fit here.',
    },
    {
      title: 'Multimodal agents (images / audio)',
      body: 'Switch the Normalizer to MultimodalNormalizer. The stage will accept image attachments and audio blobs as part of the conversation history (Anthropic API content blocks).',
    },
    {
      title: 'Schema-locked API agent',
      body: 'For server-to-server agents that should only accept structured JSON requests, switch the Validator to SchemaValidator and put your JSON schema in stage config. Inputs that fail validation are rejected before any LLM is called.',
    },
  ],
  configurations: [
    {
      name: 'Default chat',
      summary: 'No extra setup — leave Stage 1 active.',
      highlights: [
        'validator: DefaultValidator',
        'normalizer: DefaultNormalizer',
      ],
    },
    {
      name: 'Multimodal capable',
      summary: 'Accept images / audio attachments alongside text.',
      highlights: [
        'validator: DefaultValidator',
        'normalizer: MultimodalNormalizer',
      ],
    },
    {
      name: 'Schema-locked API',
      summary: 'Only structured JSON requests pass.',
      highlights: [
        'validator: SchemaValidator',
        'config.input_schema: { ...your JSON schema... }',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'Disabling Stage 1 stops the agent',
      body: 'Stage 1 is responsible for putting the user message into state.messages. With it inactive, downstream stages (Stage 2 context, Stage 6 api) see an empty conversation and the LLM is called with no user turn.',
    },
    {
      title: 'Looking for the system prompt? Wrong stage',
      body: 'The system prompt does NOT live in Stage 1. It belongs to Stage 3 (System). If you need to set persona / instructions, drill into Stage 3 instead.',
    },
    {
      title: 'StrictValidator false positives on legitimate code',
      body: 'StrictValidator can reject code-like inputs that look adversarial. Track rejection counts and tune accordingly — never silently drop turns.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s01_input/strategy.py',
      description: 'Validator + Normalizer slot definitions.',
    },
    {
      label: 'geny-executor / stages/s01_input/artifact/default/stage.py',
      description: 'Default artifact: validate → normalize → state.messages.append.',
    },
  ],
  relatedStages: [
    {
      order: 2,
      reason: 'Stage 2 (context) reads back the user message Stage 1 just appended, plus the rest of the history.',
    },
    {
      order: 3,
      reason: 'Stage 3 (system) — THIS is where the system prompt actually lives. Stage 1 only validates and normalizes the user input.',
    },
    {
      order: 6,
      reason: 'Stage 6 (api) ultimately calls the LLM with the messages Stage 1 has primed.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '기본 — 텍스트 채팅 에이전트',
      body: '대부분의 에이전트는 1단계를 DefaultValidator + DefaultNormalizer 조합으로 둡니다. 일반 텍스트 질문, 코드 스니펫, 단일 언어 대화가 모두 여기에 해당.',
    },
    {
      title: '멀티모달 에이전트 (이미지/오디오)',
      body: 'Normalizer 를 MultimodalNormalizer 로 변경. 이미지 첨부와 오디오 blob 을 대화 히스토리에 그대로 받을 수 있습니다 (Anthropic API content block).',
    },
    {
      title: '스키마 잠금 API 에이전트',
      body: '구조화된 JSON 요청만 받는 server-to-server 에이전트는 Validator 를 SchemaValidator 로 변경하고 단계 config 에 JSON 스키마를 넣으세요. 검증 실패 시 LLM 호출 전에 거부됩니다.',
    },
  ],
  configurations: [
    {
      name: '기본 채팅',
      summary: '추가 설정 없이 1단계 활성만 유지.',
      highlights: [
        'validator: DefaultValidator',
        'normalizer: DefaultNormalizer',
      ],
    },
    {
      name: '멀티모달 지원',
      summary: '텍스트와 함께 이미지/오디오 첨부 수용.',
      highlights: [
        'validator: DefaultValidator',
        'normalizer: MultimodalNormalizer',
      ],
    },
    {
      name: '스키마 잠금 API',
      summary: '정해진 구조의 JSON 요청만 통과.',
      highlights: [
        'validator: SchemaValidator',
        'config.input_schema: { ...JSON 스키마... }',
      ],
    },
  ],
  pitfalls: [
    {
      title: '1단계 비활성화 시 에이전트가 멈춤',
      body: '1단계가 사용자 메시지를 state.messages 에 추가하는 책임을 집니다. 비활성화하면 하위 단계 (2단계 context, 6단계 api) 가 빈 대화를 보고 LLM 이 사용자 턴 없이 호출됩니다.',
    },
    {
      title: '시스템 프롬프트를 찾고 있다면 — 잘못된 단계',
      body: '시스템 프롬프트는 1단계에 없습니다. 3단계 (System) 에 있습니다. 페르소나/지침을 설정하려면 3단계로 가세요.',
    },
    {
      title: 'StrictValidator 가 정상 코드에 false positive',
      body: 'StrictValidator 는 적대적으로 보이는 코드 같은 입력을 거부할 수 있음. 거부 횟수를 추적하고 조정하세요 — 절대 silent 하게 턴을 버리지 마세요.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s01_input/strategy.py',
      description: 'Validator + Normalizer 슬롯 정의.',
    },
    {
      label: 'geny-executor / stages/s01_input/artifact/default/stage.py',
      description: '기본 아티팩트: validate → normalize → state.messages.append.',
    },
  ],
  relatedStages: [
    {
      order: 2,
      reason: '2단계 (context) 가 1단계가 추가한 사용자 메시지와 나머지 히스토리를 읽습니다.',
    },
    {
      order: 3,
      reason: '3단계 (system) — 시스템 프롬프트가 실제로 있는 곳. 1단계는 사용자 입력의 검증과 정형화만 담당.',
    },
    {
      order: 6,
      reason: '6단계 (api) 가 1단계가 준비한 메시지로 LLM 을 호출.',
    },
  ],
};

export const stage01Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
