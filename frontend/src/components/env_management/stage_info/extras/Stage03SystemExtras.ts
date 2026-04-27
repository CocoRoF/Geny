/**
 * Stage 3 (system) — assembles the final system prompt the LLM sees.
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default — single static persona',
      body: 'Use DefaultBuilder. The system prompt set in Stage 1 (config.system_prompt) is what the LLM sees. Plain and predictable.',
    },
    {
      title: 'Persona blocks — composable persona',
      body: 'Use ComposingBuilder. Multiple persona blocks (defined in Geny\'s settings) are combined per the active role. Useful when one agent plays multiple roles (worker, planner, vtuber).',
    },
    {
      title: 'Tool-aware persona',
      body: 'When the agent has many custom tools, this stage can append a "Tools available" preamble so the LLM understands what tools exist and when to use each.',
    },
  ],
  configurations: [
    {
      name: 'Static persona',
      summary: 'Just the system_prompt in Stage 1 config.',
      highlights: ['builder: DefaultBuilder'],
    },
    {
      name: 'Role-aware composition',
      summary: 'Persona blocks chosen by role hint.',
      highlights: [
        'builder: ComposingBuilder',
        'Geny settings.persona.blocks_by_role',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'Long persona prompts eat context',
      body: 'A 4000-token persona prompt leaves only 196000 tokens for actual conversation in a 200k window. Keep personas tight, push instructions into per-tool prompts where possible.',
    },
    {
      title: 'Persona conflicts with tool descriptions',
      body: 'If your persona says "always be brief" but a tool description says "respond with verbose JSON", the LLM gets confused. Audit both surfaces together.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s03_system/strategy.py',
      description: 'Builder slot definitions.',
    },
    {
      label: 'Geny / backend/service/persona/dynamic_builder.py',
      description: 'Geny-side persona block selection by role.',
    },
  ],
  relatedStages: [
    {
      order: 1,
      reason: 'Stage 1 supplies the base system_prompt that Stage 3 may augment.',
    },
    {
      order: 6,
      reason: 'Stage 6 sends the assembled system prompt to the LLM as the system message.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '기본 — 단일 고정 페르소나',
      body: 'DefaultBuilder 사용. Stage 1 에서 설정한 system_prompt 가 그대로 LLM 에 전달됩니다. 단순하고 예측 가능.',
    },
    {
      title: '페르소나 블록 — 조합형 페르소나',
      body: 'ComposingBuilder 사용. Geny 설정에 정의된 여러 페르소나 블록이 활성 role 에 따라 조합됩니다. 한 에이전트가 worker/planner/vtuber 등 여러 역할을 할 때 유용합니다.',
    },
    {
      title: '도구 인식 페르소나',
      body: '커스텀 도구가 많을 때 이 단계가 "사용 가능한 도구" 서두를 붙여줄 수 있습니다. LLM 이 어떤 도구가 있고 언제 쓰는지 이해하기 쉬워집니다.',
    },
  ],
  configurations: [
    {
      name: '정적 페르소나',
      summary: 'Stage 1 config 의 system_prompt 만.',
      highlights: ['builder: DefaultBuilder'],
    },
    {
      name: '역할 기반 조합',
      summary: 'role 힌트로 페르소나 블록 선택.',
      highlights: [
        'builder: ComposingBuilder',
        'Geny settings.persona.blocks_by_role',
      ],
    },
  ],
  pitfalls: [
    {
      title: '긴 페르소나 프롬프트는 컨텍스트를 잡아먹습니다',
      body: '4000 토큰 페르소나는 200k 창에서 196000 만 실제 대화에 남깁니다. 페르소나는 빡빡하게 유지하고, 가능한 지침은 도구별 프롬프트에 넣으세요.',
    },
    {
      title: '페르소나와 도구 설명 충돌',
      body: '페르소나가 "항상 간결하게" 라고 하는데 어떤 도구가 "verbose JSON 으로 응답하라" 고 하면 LLM 이 혼란스러워집니다. 두 표면을 함께 검토하세요.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s03_system/strategy.py',
      description: 'Builder 슬롯 정의.',
    },
    {
      label: 'Geny / backend/service/persona/dynamic_builder.py',
      description: 'Geny 측 role 기반 페르소나 블록 선택.',
    },
  ],
  relatedStages: [
    {
      order: 1,
      reason: 'Stage 1 이 베이스 system_prompt 를 제공하면 Stage 3 가 보강합니다.',
    },
    {
      order: 6,
      reason: 'Stage 6 이 조립된 시스템 프롬프트를 LLM 에 system 메시지로 보냅니다.',
    },
  ],
};

export const stage03Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
