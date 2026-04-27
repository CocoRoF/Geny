/**
 * Stage 5 (cache) — Anthropic prompt caching + replay cache.
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default — Anthropic prompt cache',
      body: 'PromptCache marks long, stable prefixes (system prompt, tools manifest) for Anthropic\'s 5-minute prompt cache. Hit rate above ~50% can cut LLM cost in half on multi-turn agents.',
    },
    {
      title: 'Replay cache for testing',
      body: 'ReplayCache stores LLM responses keyed by full request hash. On hit, the cached response is replayed instantly — invaluable for testing downstream stages without burning tokens.',
    },
    {
      title: 'Cache off',
      body: 'For stateless one-off requests where the same prompt won\'t repeat within 5 minutes, the cache adds overhead without benefit. Disable to save the bookkeeping.',
    },
  ],
  configurations: [
    {
      name: 'Production — prompt cache on',
      summary: 'Default. Anthropic cache markers added to stable prefixes.',
      highlights: ['cache: PromptCache'],
    },
    {
      name: 'Test fixtures',
      summary: 'Replay cache for deterministic tests.',
      highlights: [
        'cache: ReplayCache',
        'config.replay.fixtures_dir: tests/fixtures/llm',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'Cache markers on volatile content',
      body: 'Prompt cache only helps when the cached prefix actually stays stable. If you mark the conversation history (which changes every turn) you get worse hit rates than no cache at all.',
    },
    {
      title: 'Replay cache key drift',
      body: 'ReplayCache keys on the full request hash. Adding a new tool or changing a system prompt invalidates every fixture. Plan re-record cycles.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s05_cache/strategy.py',
      description: 'PromptCache vs ReplayCache slot definitions.',
    },
  ],
  relatedStages: [
    {
      order: 6,
      reason: 'Stage 6 receives the cache-marked request and submits it to the Anthropic API.',
    },
    {
      order: 7,
      reason: 'Stage 7 (token) reads the cache decision when computing token spend.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '기본 — Anthropic prompt cache',
      body: 'PromptCache 가 길고 안정적인 prefix (시스템 프롬프트, 도구 매니페스트) 를 Anthropic 5분 prompt cache 로 표시합니다. ~50% 이상의 적중률이면 다중 턴 에이전트의 LLM 비용을 절반으로 줄일 수 있습니다.',
    },
    {
      title: '테스트용 Replay cache',
      body: 'ReplayCache 가 전체 요청 해시 기준으로 LLM 응답을 저장합니다. 적중 시 캐시된 응답이 즉시 재생됩니다 — 토큰 소모 없이 하위 단계 테스트에 유용합니다.',
    },
    {
      title: '캐시 끄기',
      body: '5분 안에 같은 프롬프트가 반복되지 않는 stateless 일회성 요청이라면 캐시는 이득 없이 오버헤드만 추가합니다. 끄세요.',
    },
  ],
  configurations: [
    {
      name: '프로덕션 — prompt cache 켜기',
      summary: '기본값. 안정적 prefix 에 Anthropic cache 마커 추가.',
      highlights: ['cache: PromptCache'],
    },
    {
      name: '테스트 fixture',
      summary: '결정론적 테스트를 위한 replay cache.',
      highlights: [
        'cache: ReplayCache',
        'config.replay.fixtures_dir: tests/fixtures/llm',
      ],
    },
  ],
  pitfalls: [
    {
      title: '변동성 콘텐츠에 캐시 마커',
      body: 'Prompt cache 는 캐시된 prefix 가 실제로 안정적일 때만 도움이 됩니다. 매 턴 바뀌는 대화 히스토리에 마커를 표시하면 캐시 없는 것보다 적중률이 떨어집니다.',
    },
    {
      title: 'Replay cache 키 drift',
      body: 'ReplayCache 는 전체 요청 해시로 키를 만듭니다. 새 도구 추가나 시스템 프롬프트 변경이 모든 fixture 를 무효화합니다. 재녹화 주기를 계획하세요.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s05_cache/strategy.py',
      description: 'PromptCache vs ReplayCache 슬롯 정의.',
    },
  ],
  relatedStages: [
    {
      order: 6,
      reason: 'Stage 6 가 캐시 마커가 붙은 요청을 받아 Anthropic API 에 제출.',
    },
    {
      order: 7,
      reason: 'Stage 7 (token) 가 토큰 소모 계산 시 캐시 결정을 참조.',
    },
  ],
};

export const stage05Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
