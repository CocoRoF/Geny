/**
 * Stage 3 (system) — assembles the system prompt the LLM sees.
 *
 * IMPORTANT: this is THE stage that owns the system prompt. An earlier
 * version of Stage 1's UI mistakenly hosted a system_prompt textarea
 * — that bug was fixed in cycle 20260427_3. Stage 1 only validates
 * and normalizes the user's input.
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default — single static persona',
      body: 'Use StaticPromptBuilder. Type your persona / instructions into the prompt field and that exact text becomes the LLM\'s system message every turn. Plain and predictable.',
    },
    {
      title: 'Composable — multi-role agent',
      body: 'Use ComposablePromptBuilder when one agent needs to play multiple roles (worker / planner / vtuber). Persona blocks defined in your settings are stitched together based on the active role hint.',
    },
    {
      title: 'Tool-aware persona',
      body: 'When the agent has many custom tools, the prompt builder can append a "Tools available" preamble so the LLM understands what tools exist and when to use each. Stage 3 emits this automatically when tool_registry is populated.',
    },
  ],
  configurations: [
    {
      name: 'Static — recommended starting point',
      summary: 'One textarea, sent verbatim every turn.',
      highlights: [
        'builder: StaticPromptBuilder',
        'config.prompt: "You are a helpful assistant…"',
      ],
    },
    {
      name: 'Persona blocks via composable',
      summary: 'Role-aware composition from settings.persona.blocks_by_role.',
      highlights: [
        'builder: ComposablePromptBuilder',
        'Geny settings.persona.blocks_by_role.<role>: ["base", "tools_aware", "concise"]',
      ],
    },
    {
      name: 'Templated prompt',
      summary: 'Static prompt with template variable interpolation.',
      highlights: [
        'builder: StaticPromptBuilder',
        'config.prompt: "You are {persona_name}…"',
        'config.template_vars: { persona_name: "Ellen" }',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'Empty prompt → bland agent',
      body: 'If config.prompt is empty (and no composable blocks selected), the LLM gets no persona and answers blandly without context about its role. Symptoms: unexpected language switches, over-apologetic tone, refusal to commit to a personality. Always supply at least a one-line system prompt.',
    },
    {
      title: 'Long persona prompts eat context',
      body: 'A 4000-token persona leaves only 196000 tokens for actual conversation in a 200k window. Keep personas tight; push instructions into per-tool prompts where possible.',
    },
    {
      title: 'Persona conflicts with tool descriptions',
      body: 'If your persona says "always be brief" but a tool description says "respond with verbose JSON", the LLM gets confused. Audit persona + tool descriptions together.',
    },
    {
      title: 'Disabling Stage 3 ships the agent into the LLM with no system message',
      body: 'The LLM gets the conversation history but no system prompt at all. The model defaults to its trained persona. For most agents this means the carefully-crafted persona is silently dropped. Keep Stage 3 active.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s03_system/strategy.py',
      description: 'StaticPromptBuilder + ComposablePromptBuilder slot definitions.',
    },
    {
      label: 'geny-executor / stages/s03_system/artifact/default/stage.py',
      description: 'Builds prompt → registers tools → emits system.built event.',
    },
    {
      label: 'Geny / backend/service/persona/dynamic_builder.py',
      description: 'Geny-side persona block selection by role (consumed by ComposablePromptBuilder).',
    },
  ],
  relatedStages: [
    {
      order: 1,
      reason: 'Stage 1 validates the USER input. Stage 3 builds the SYSTEM prompt. They are separate concerns — don\'t mix them.',
    },
    {
      order: 6,
      reason: 'Stage 6 (api) sends the prompt Stage 3 assembled to the LLM as the system message on every call.',
    },
    {
      order: 10,
      reason: 'Stage 3 also registers the tool definitions Stage 10 will execute. If tool_registry is set but state.tools is empty, Stage 3 populates it.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '기본 — 단일 고정 페르소나',
      body: 'StaticPromptBuilder 사용. 프롬프트 필드에 페르소나/지침을 입력하면 그 텍스트가 매 턴 LLM 의 system 메시지로 그대로 전달됩니다. 단순하고 예측 가능.',
    },
    {
      title: 'Composable — 다역할 에이전트',
      body: '한 에이전트가 여러 역할 (worker / planner / vtuber) 을 해야 할 때 ComposablePromptBuilder. 설정에 정의된 페르소나 블록이 활성 role 힌트에 따라 조합됩니다.',
    },
    {
      title: '도구 인식 페르소나',
      body: '커스텀 도구가 많을 때 prompt builder 가 "사용 가능한 도구" 서두를 자동 부착하여 LLM 이 어떤 도구가 있고 언제 쓰는지 이해할 수 있게 합니다. tool_registry 가 채워졌을 때 Stage 3 가 자동으로 emit.',
    },
  ],
  configurations: [
    {
      name: 'Static — 권장 시작점',
      summary: 'textarea 하나, 매 턴 그대로 전달.',
      highlights: [
        'builder: StaticPromptBuilder',
        'config.prompt: "당신은 도움이 되는 어시스턴트…"',
      ],
    },
    {
      name: 'Composable 페르소나 블록',
      summary: 'settings.persona.blocks_by_role 에서 role 기반 조합.',
      highlights: [
        'builder: ComposablePromptBuilder',
        'Geny settings.persona.blocks_by_role.<role>: ["base", "tools_aware", "concise"]',
      ],
    },
    {
      name: '템플릿 프롬프트',
      summary: '템플릿 변수 보간이 있는 정적 프롬프트.',
      highlights: [
        'builder: StaticPromptBuilder',
        'config.prompt: "당신은 {persona_name}…"',
        'config.template_vars: { persona_name: "Ellen" }',
      ],
    },
  ],
  pitfalls: [
    {
      title: '빈 프롬프트 → 무미건조한 에이전트',
      body: 'config.prompt 가 비어있고 composable 블록도 없으면 LLM 이 페르소나를 못 받고 자기 역할 맥락 없이 답합니다. 증상: 뜻밖의 언어 전환, 과도한 사과 톤, 인격 정착 거부. 최소 한 줄 시스템 프롬프트는 항상 제공하세요.',
    },
    {
      title: '긴 페르소나 프롬프트는 컨텍스트를 잡아먹습니다',
      body: '4000 토큰 페르소나는 200k 창에서 196000 만 실제 대화에 남깁니다. 페르소나는 빡빡하게, 가능한 지침은 도구별 프롬프트에 넣으세요.',
    },
    {
      title: '페르소나 vs 도구 설명 충돌',
      body: '페르소나가 "항상 간결하게" 라는데 어떤 도구가 "verbose JSON 으로 응답" 이라고 하면 LLM 이 혼란스러워집니다. 페르소나 + 도구 설명을 함께 검토하세요.',
    },
    {
      title: 'Stage 3 비활성화 → 시스템 메시지 없이 LLM 호출',
      body: 'LLM 이 대화 히스토리는 받지만 시스템 프롬프트는 전혀 못 받습니다. 모델은 학습된 기본 페르소나로 fallback. 대부분의 에이전트에선 정성껏 만든 페르소나가 silent 드롭. Stage 3 는 켜두세요.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s03_system/strategy.py',
      description: 'StaticPromptBuilder + ComposablePromptBuilder 슬롯 정의.',
    },
    {
      label: 'geny-executor / stages/s03_system/artifact/default/stage.py',
      description: '프롬프트 빌드 → 도구 등록 → system.built 이벤트 emit.',
    },
    {
      label: 'Geny / backend/service/persona/dynamic_builder.py',
      description: 'Geny 측 role 기반 페르소나 블록 선택 (ComposablePromptBuilder 가 소비).',
    },
  ],
  relatedStages: [
    {
      order: 1,
      reason: '1단계는 사용자 입력 검증. Stage 3 는 시스템 프롬프트 빌드. 별개의 관심사 — 섞지 마세요.',
    },
    {
      order: 6,
      reason: '6단계 (api) 가 매 호출마다 Stage 3 가 조립한 프롬프트를 LLM 에 system 메시지로 전송.',
    },
    {
      order: 10,
      reason: 'Stage 3 가 Stage 10 이 실행할 도구 정의도 등록합니다. tool_registry 가 설정됐는데 state.tools 가 비어있으면 Stage 3 가 채웁니다.',
    },
  ],
};

export const stage03Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
