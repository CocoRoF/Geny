/**
 * Stage 1 (input) — supplementary detail content for the info modal.
 *
 * Sourced from geny-executor's
 *   src/geny_executor/stages/s01_input/{strategy.py, artifact/default/stage.py}
 * and how the Geny VTuber pipeline routes raw user / executor input
 * into the agent.
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default — Korean / English chat agents',
      body: 'Most agents leave Stage 1 on with the DefaultValidator + DefaultNormalizer combination. Plain-text chat, code questions, single-language conversations all fit here.',
    },
    {
      title: 'Multimodal agents (images, audio, mixed media)',
      body: 'Switch the Normalizer slot to MultimodalNormalizer. The stage will accept image attachments and audio blobs as part of the conversation history (as Anthropic API content blocks).',
    },
    {
      title: 'Strict tool-only API surface',
      body: 'For server-to-server agents that only accept structured JSON requests, switch the Validator slot to StrictValidator or SchemaValidator with a custom schema. Inputs that fail validation will be rejected before the LLM is ever called.',
    },
  ],
  configurations: [
    {
      name: 'Default chat',
      summary: 'No extra setup — just leave Stage 1 active.',
      highlights: ['Validator: DefaultValidator', 'Normalizer: DefaultNormalizer'],
    },
    {
      name: 'Multimodal capable',
      summary: 'Accept images / audio attachments alongside text.',
      highlights: [
        'Validator: DefaultValidator',
        'Normalizer: MultimodalNormalizer',
      ],
    },
    {
      name: 'Schema-locked API',
      summary: 'Only structured JSON requests pass.',
      highlights: [
        'Validator: SchemaValidator',
        'config.input_schema set to your JSON schema',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'Disabling Stage 1 hangs the pipeline',
      body: 'Stage 1 is responsible for adding the user message into state.messages. With it inactive, downstream stages (Stage 2 context, Stage 6 api) see an empty conversation and the LLM is called with no user turn.',
    },
    {
      title: 'Empty system prompts are easy to forget',
      body: 'Stage 1 also writes the system prompt into state.messages prelude. If config.system_prompt is empty, the LLM sees no persona and drifts — symptoms include unexpected language switches and over-apologetic tone.',
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
      reason: 'Stage 2 (context) reads the user message Stage 1 just appended to load history + memory around it.',
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
      title: '기본 — 한/영 채팅 에이전트',
      body: '대부분의 에이전트는 1단계를 켜둔 채 DefaultValidator + DefaultNormalizer 조합으로 사용합니다. 일반 텍스트 채팅, 코드 질문, 단일 언어 대화가 모두 여기에 해당합니다.',
    },
    {
      title: '멀티모달 에이전트 (이미지/오디오/혼합 미디어)',
      body: 'Normalizer 슬롯을 MultimodalNormalizer 로 변경하세요. 이미지 첨부와 오디오 blob 을 대화 히스토리에 그대로 받을 수 있습니다 (Anthropic API content block 형식).',
    },
    {
      title: '엄격한 tool-only API 진입점',
      body: '구조화된 JSON 요청만 받는 server-to-server 에이전트라면 Validator 슬롯을 StrictValidator 또는 SchemaValidator + 커스텀 스키마로 변경하세요. 검증 실패 시 LLM 호출 전에 거부됩니다.',
    },
  ],
  configurations: [
    {
      name: '기본 채팅',
      summary: '추가 설정 없이 1단계 활성만 유지.',
      highlights: ['Validator: DefaultValidator', 'Normalizer: DefaultNormalizer'],
    },
    {
      name: '멀티모달 지원',
      summary: '텍스트와 함께 이미지/오디오 첨부 수용.',
      highlights: [
        'Validator: DefaultValidator',
        'Normalizer: MultimodalNormalizer',
      ],
    },
    {
      name: '스키마 잠금 API',
      summary: '정해진 구조의 JSON 요청만 통과.',
      highlights: [
        'Validator: SchemaValidator',
        'config.input_schema 에 JSON 스키마 지정',
      ],
    },
  ],
  pitfalls: [
    {
      title: '1단계를 끄면 파이프라인이 멈춥니다',
      body: '1단계는 사용자 메시지를 state.messages 에 추가하는 책임이 있습니다. 비활성화하면 하위 단계들 (2단계 context, 6단계 api) 이 빈 대화를 보고 LLM 이 사용자 턴 없이 호출됩니다.',
    },
    {
      title: '빈 시스템 프롬프트는 잊기 쉬움',
      body: '1단계는 state.messages 의 prelude 에 시스템 프롬프트도 기록합니다. config.system_prompt 가 비어있으면 LLM 이 페르소나 없이 동작하여 — 뜻밖의 언어 전환, 과도한 사과 톤 등의 증상이 나타납니다.',
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
      reason: '2단계 (context) 가 1단계가 추가한 사용자 메시지 주변으로 history + memory 를 로드합니다.',
    },
    {
      order: 6,
      reason: '6단계 (api) 가 1단계가 준비한 메시지로 LLM 을 호출합니다.',
    },
  ],
};

export const stage01Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
