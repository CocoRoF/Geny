/**
 * Stage 10 (tools) — actually executes the tool calls the LLM made.
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default — full tool access',
      body: 'tool_binding=null lets the stage call ANY tool registered in manifest.tools.built_in (or its * wildcard). Standard for general-purpose agents.',
    },
    {
      title: 'Tightly-scoped helper agent',
      body: 'tool_binding.allowed = ["Read", "Grep"] limits the agent to a tiny read-only toolset. Useful for sub-agents (Stage 12) that should only investigate and report back.',
    },
    {
      title: 'Block dangerous tools',
      body: 'tool_binding.blocked = ["Bash", "Write"] keeps the rest of the catalogue available but blocks specific destructive ones — quick win for safety without rebuilding the full allowlist.',
    },
  ],
  configurations: [
    {
      name: 'General assistant',
      summary: 'All tools available.',
      highlights: ['tool_binding: null', 'manifest.tools.built_in: ["*"]'],
    },
    {
      name: 'Code reviewer',
      summary: 'Read + Grep + Glob only.',
      highlights: [
        'tool_binding.allowed: ["Read", "Grep", "Glob"]',
      ],
    },
    {
      name: 'No-shell agent',
      summary: 'Block Bash + Write everywhere.',
      highlights: [
        'tool_binding.blocked: ["Bash", "Write", "Edit"]',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'allowlist + blocklist set together',
      body: 'StageToolBinding accepts both, but allowed wins — anything not in allowed is implicitly blocked. Setting both is redundant and confusing. Pick one mode.',
    },
    {
      title: 'Tool not in manifest.tools.built_in',
      body: 'If the LLM tries to call a tool that isn\'t registered globally, Stage 10 raises ToolNotFound and the loop ends in error. Stage 1 (input) won\'t catch this — only Stage 10 enforces the registry.',
    },
    {
      title: 'Wildcard with strict permissions',
      body: 'manifest.tools.built_in=["*"] grants every tool but the per-tool permission rules in Library / Permissions still apply. A tool can be "registered" yet "blocked" — read your permissions.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / tools/stage_binding.py',
      description: 'StageToolBinding allowed / blocked / extra_context dataclass.',
    },
    {
      label: 'geny-executor / tools/built_in/__init__.py',
      description: 'BUILT_IN_TOOL_CLASSES — the master registry of every tool name accepted by the executor.',
    },
    {
      label: 'geny-executor / permission/types.py',
      description: 'PermissionRule + PermissionMatrix — Stage 10 calls into this before each tool execution.',
    },
  ],
  relatedStages: [
    {
      order: 9,
      reason: 'Stage 9 (parse) extracts the tool_use blocks Stage 10 then executes.',
    },
    {
      order: 11,
      reason: 'Stage 11 (tool_review) inspects each tool call BEFORE Stage 10 runs it. Reviewers can flag the call but Stage 10 is the last line of defence — it enforces the binding.',
    },
    {
      order: 14,
      reason: 'Stage 14 (evaluate) reads tool result counts to decide whether the agent has made enough progress.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '기본 — 전체 도구 접근',
      body: 'tool_binding=null 이면 manifest.tools.built_in 에 등록된 모든 도구 (또는 * 와일드카드) 를 호출 가능. 범용 에이전트 표준.',
    },
    {
      title: '범위 좁힌 헬퍼 에이전트',
      body: 'tool_binding.allowed = ["Read", "Grep"] 으로 작은 read-only 도구셋만 허용. 조사하고 보고만 해야 하는 서브 에이전트 (Stage 12) 에 유용.',
    },
    {
      title: '위험한 도구 차단',
      body: 'tool_binding.blocked = ["Bash", "Write"] 는 나머지 카탈로그는 두고 특정 파괴적 도구만 차단 — 전체 allowlist 재구축 없이 안전성을 빠르게 확보.',
    },
  ],
  configurations: [
    {
      name: '범용 비서',
      summary: '모든 도구 사용 가능.',
      highlights: ['tool_binding: null', 'manifest.tools.built_in: ["*"]'],
    },
    {
      name: '코드 리뷰어',
      summary: 'Read + Grep + Glob 만.',
      highlights: [
        'tool_binding.allowed: ["Read", "Grep", "Glob"]',
      ],
    },
    {
      name: 'No-shell 에이전트',
      summary: 'Bash + Write 차단.',
      highlights: [
        'tool_binding.blocked: ["Bash", "Write", "Edit"]',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'allowlist + blocklist 동시 설정',
      body: 'StageToolBinding 은 둘 다 받지만 allowed 가 우선 — allowed 에 없는 것은 암묵적 차단. 둘 다 설정하면 중복이고 헷갈림. 하나만 고르세요.',
    },
    {
      title: 'manifest.tools.built_in 에 없는 도구',
      body: 'LLM 이 전역 등록되지 않은 도구를 호출하면 Stage 10 이 ToolNotFound 를 던지고 루프가 에러로 종료. Stage 1 은 이를 못 잡습니다 — 레지스트리는 Stage 10 만 강제합니다.',
    },
    {
      title: '와일드카드 + 엄격한 권한',
      body: 'manifest.tools.built_in=["*"] 가 모든 도구를 허용하지만 Library / Permissions 의 도구별 권한 규칙은 여전히 적용. 도구가 "등록" 됐어도 "차단" 될 수 있음 — 권한을 확인하세요.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / tools/stage_binding.py',
      description: 'StageToolBinding allowed / blocked / extra_context dataclass.',
    },
    {
      label: 'geny-executor / tools/built_in/__init__.py',
      description: 'BUILT_IN_TOOL_CLASSES — 실행기가 받아들이는 모든 도구 이름의 마스터 레지스트리.',
    },
    {
      label: 'geny-executor / permission/types.py',
      description: 'PermissionRule + PermissionMatrix — Stage 10 이 각 도구 실행 전에 호출.',
    },
  ],
  relatedStages: [
    {
      order: 9,
      reason: 'Stage 9 (parse) 가 추출한 tool_use 블록을 Stage 10 이 실행.',
    },
    {
      order: 11,
      reason: 'Stage 11 (tool_review) 가 Stage 10 실행 전 각 도구 호출을 검토. 리뷰어가 플래그 가능하지만 Stage 10 이 최종 방어선 — 바인딩 강제.',
    },
    {
      order: 14,
      reason: 'Stage 14 (evaluate) 가 도구 결과 수를 읽어 에이전트가 충분한 진척을 냈는지 판단.',
    },
  ],
};

export const stage10Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
