/**
 * Stage 12 (agent) — sub-agent orchestration. When the LLM invokes
 * the Agent / Task tool, this stage spins up a sub-pipeline with its
 * own scope, runs it, and surfaces the result back to the parent.
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default — sequential sub-agents',
      body: 'SequentialSpawner runs one sub-agent at a time. Predictable, easy to debug. Suitable for most "investigate then report" flows.',
    },
    {
      title: 'Parallel sub-agents',
      body: 'ParallelSpawner fires multiple sub-agents at once. Use when sub-tasks are independent (e.g. "summarise these 5 files in parallel"). Costs more LLM tokens up-front but cuts wall-clock latency.',
    },
    {
      title: 'No sub-agents (flat pipeline)',
      body: 'Disable Stage 12 to forbid the LLM from spawning sub-agents. Useful for tightly-scoped automations where you want a single linear conversation.',
    },
  ],
  configurations: [
    {
      name: 'Sequential — default',
      summary: 'One sub-agent at a time.',
      highlights: ['spawner: SequentialSpawner'],
    },
    {
      name: 'Parallel investigation',
      summary: 'Multiple sub-agents fire simultaneously.',
      highlights: [
        'spawner: ParallelSpawner',
        'config.max_parallel: 4',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'Sub-agent recursion explosion',
      body: 'A sub-agent can spawn its own sub-agents. Without max_recursion_depth (default 3), an unlucky LLM can spawn an unbounded tree. Set the depth conservatively.',
    },
    {
      title: 'Parallel sub-agents share state.shared',
      body: 'state.shared is the only cross-agent communication channel. Two parallel sub-agents writing to the same key race. Either keep them on disjoint keys or use SequentialSpawner.',
    },
    {
      title: 'Sub-agent cost not bounded',
      body: 'Each sub-agent runs its own pipeline with its own cost_budget_usd. The PARENT\'s budget doesn\'t cap the children. Pass a sub-agent budget explicitly via the Agent tool args.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s12_agent/strategy.py',
      description: 'Spawner slot + Sequential / Parallel implementations.',
    },
    {
      label: 'geny-executor / tools/built_in/agent.py',
      description: 'Agent tool — what the LLM calls to spawn a sub-agent.',
    },
  ],
  relatedStages: [
    {
      order: 10,
      reason: 'Stage 10 (tools) executes the Agent tool call which then hands off to Stage 12.',
    },
    {
      order: 13,
      reason: 'Stage 13 (task_registry) tracks the sub-agent invocation as a background task entry.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '기본 — 순차 서브 에이전트',
      body: 'SequentialSpawner 가 한 번에 하나씩 실행. 예측 가능하고 디버깅 쉬움. 대부분의 "조사 후 보고" 플로우에 적합.',
    },
    {
      title: '병렬 서브 에이전트',
      body: 'ParallelSpawner 가 여러 서브 에이전트를 동시 발화. 서브 작업이 독립적일 때 사용 (예: "이 5개 파일을 병렬로 요약"). LLM 토큰을 더 먼저 소모하지만 wall-clock 지연을 줄임.',
    },
    {
      title: '서브 에이전트 없음 (flat pipeline)',
      body: 'Stage 12 비활성화로 LLM 의 서브 에이전트 생성을 금지. 단일 선형 대화를 원하는 빡빡한 자동화에 유용.',
    },
  ],
  configurations: [
    {
      name: '순차 — 기본',
      summary: '한 번에 하나씩.',
      highlights: ['spawner: SequentialSpawner'],
    },
    {
      name: '병렬 조사',
      summary: '여러 서브 에이전트 동시 발화.',
      highlights: [
        'spawner: ParallelSpawner',
        'config.max_parallel: 4',
      ],
    },
  ],
  pitfalls: [
    {
      title: '서브 에이전트 재귀 폭발',
      body: '서브 에이전트가 자기 서브 에이전트를 생성 가능. max_recursion_depth (기본 3) 없으면 운 나쁜 LLM 이 무한 트리를 생성. 깊이를 보수적으로 설정.',
    },
    {
      title: '병렬 서브 에이전트가 state.shared 공유',
      body: 'state.shared 가 유일한 cross-agent 통신 채널. 같은 키를 쓰는 두 병렬 서브 에이전트가 race. 분리된 키를 쓰거나 SequentialSpawner 를 사용.',
    },
    {
      title: '서브 에이전트 비용 무제한',
      body: '각 서브 에이전트가 자기 cost_budget_usd 로 자기 파이프라인을 실행. 부모의 예산이 자식을 제한하지 않습니다. Agent 도구 인자로 서브 에이전트 예산을 명시적으로 전달.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s12_agent/strategy.py',
      description: 'Spawner 슬롯 + Sequential / Parallel 구현.',
    },
    {
      label: 'geny-executor / tools/built_in/agent.py',
      description: 'Agent 도구 — LLM 이 서브 에이전트 생성 시 호출.',
    },
  ],
  relatedStages: [
    {
      order: 10,
      reason: 'Stage 10 (tools) 가 Agent 도구 호출을 실행하면 Stage 12 로 핸드오프.',
    },
    {
      order: 13,
      reason: 'Stage 13 (task_registry) 가 서브 에이전트 호출을 백그라운드 태스크 항목으로 추적.',
    },
  ],
};

export const stage12Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
