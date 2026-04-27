/**
 * Stage 2 (context) — supplementary detail content for the info modal.
 *
 * Sourced from
 *   src/geny_executor/stages/s02_context/{strategy.py, retriever.py, artifact/default/stage.py}
 *   src/geny_executor/core/state.py (memory_refs, metadata['memory_context'])
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default — short / medium chats',
      body: 'Use SimpleLoadStrategy. The agent reads back whatever conversation lives in state.messages without any external retrieval. Fast, cheap, predictable.',
    },
    {
      title: 'Long-running agent with memory',
      body: 'Use HybridStrategy. Keeps the last N turns verbatim and pulls in relevant memory chunks (via the retriever) for older context. Pair with Stage 18 memory persistence so memory grows usefully over time.',
    },
    {
      title: 'Token-tight agents (small Haiku models)',
      body: 'Use ProgressiveDisclosureStrategy + a low context_window_budget. Older turns get summarised aggressively so the LLM input stays small and predictable.',
    },
  ],
  configurations: [
    {
      name: 'Stateless / single-turn',
      summary: 'No history, no memory.',
      highlights: ['strategy: SimpleLoadStrategy', 'pipeline.stateless: true'],
    },
    {
      name: 'Standard chat',
      summary: 'Recent messages, no external memory.',
      highlights: [
        'strategy: SimpleLoadStrategy',
        'context_window_budget: 200000 (default)',
      ],
    },
    {
      name: 'VTuber / personal assistant',
      summary: 'Recent N turns + retrieved memory chunks.',
      highlights: [
        'strategy: HybridStrategy',
        'retriever: vector / file',
        'context_window_budget: 200000',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'Compaction kicks in too late',
      body: 'Compaction triggers at 80% of context_window_budget. If your budget is 200k but a single tool result returns 100k tokens, you can blow past the threshold in one step. Lower the budget or use a chunking tool wrapper.',
    },
    {
      title: 'Memory retriever returning duplicates',
      body: 'Stage 2 deduplicates memory_refs by key, but if the retriever returns the same chunk under different keys (e.g. timestamped variants) duplicates leak through. Normalise keys in your retriever.',
    },
    {
      title: 'Disabling Stage 2 in a multi-turn agent',
      body: 'Without Stage 2 the LLM only sees Stage 1\'s freshly normalised input — no past conversation. Multi-turn agents become amnesiac. Only disable for genuinely single-turn workflows.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s02_context/strategy.py',
      description: 'Context strategy + retriever slot definitions.',
    },
    {
      label: 'geny-executor / stages/s02_context/artifact/default/stage.py',
      description: 'Token estimation + 80% compaction trigger logic.',
    },
  ],
  relatedStages: [
    {
      order: 1,
      reason: 'Stage 1 puts the new user message into state.messages; Stage 2 reads back the full thread including that message.',
    },
    {
      order: 18,
      reason: 'Stage 18 (memory) is the writer; Stage 2 is the reader. Configure them as a pair.',
    },
    {
      order: 19,
      reason: 'Stage 19 (summarize) helps Stage 2 by collapsing old turns into compact digests so the context stays small.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '기본 — 짧거나 중간 길이 채팅',
      body: 'SimpleLoadStrategy 사용. 외부 retrieval 없이 state.messages 의 대화 내역 그대로 읽습니다. 빠르고 저렴하고 예측 가능합니다.',
    },
    {
      title: '메모리를 가진 장기 에이전트',
      body: 'HybridStrategy 사용. 최근 N개 턴은 그대로 유지하고 retriever 가 오래된 맥락에 해당하는 메모리 청크를 가져옵니다. Stage 18 메모리 영속화와 페어링하면 시간이 갈수록 의미 있게 메모리가 쌓입니다.',
    },
    {
      title: '토큰 빡빡한 에이전트 (작은 Haiku 모델)',
      body: 'ProgressiveDisclosureStrategy + 낮은 context_window_budget. 오래된 턴이 적극적으로 요약되어 LLM 입력 크기가 작고 예측 가능하게 유지됩니다.',
    },
  ],
  configurations: [
    {
      name: 'Stateless / 단일 턴',
      summary: '히스토리 없음, 메모리 없음.',
      highlights: ['strategy: SimpleLoadStrategy', 'pipeline.stateless: true'],
    },
    {
      name: '표준 채팅',
      summary: '최근 메시지만, 외부 메모리 없음.',
      highlights: [
        'strategy: SimpleLoadStrategy',
        'context_window_budget: 200000 (기본값)',
      ],
    },
    {
      name: 'VTuber / 개인 비서',
      summary: '최근 N개 턴 + 검색된 메모리 청크.',
      highlights: [
        'strategy: HybridStrategy',
        'retriever: vector / file',
        'context_window_budget: 200000',
      ],
    },
  ],
  pitfalls: [
    {
      title: '압축이 너무 늦게 발동',
      body: '압축은 context_window_budget 의 80% 에서 트리거됩니다. 예산이 200k 인데 도구 결과 하나가 100k 토큰을 반환하면 한 번에 임계값을 넘을 수 있습니다. 예산을 낮추거나 청크 단위로 자르는 도구 래퍼를 사용하세요.',
    },
    {
      title: 'Memory retriever 중복 결과',
      body: 'Stage 2 는 키 기준으로 memory_refs 를 중복 제거하지만, retriever 가 같은 청크를 다른 키 (예: 타임스탬프 변형) 로 반환하면 중복이 새어 들어옵니다. retriever 에서 키를 정규화하세요.',
    },
    {
      title: '다중 턴 에이전트에서 Stage 2 비활성화',
      body: 'Stage 2 없으면 LLM 은 Stage 1 의 새 입력만 봅니다 — 과거 대화가 안 보입니다. 다중 턴 에이전트가 기억상실이 됩니다. 진짜 단일 턴 워크플로우에서만 끄세요.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s02_context/strategy.py',
      description: 'Context 전략 + retriever 슬롯 정의.',
    },
    {
      label: 'geny-executor / stages/s02_context/artifact/default/stage.py',
      description: '토큰 추정 + 80% 압축 트리거 로직.',
    },
  ],
  relatedStages: [
    {
      order: 1,
      reason: 'Stage 1 이 새 사용자 메시지를 state.messages 에 넣으면 Stage 2 가 그 메시지를 포함한 전체 스레드를 읽습니다.',
    },
    {
      order: 18,
      reason: 'Stage 18 (memory) 가 writer, Stage 2 가 reader. 둘을 한 쌍으로 설정하세요.',
    },
    {
      order: 19,
      reason: 'Stage 19 (summarize) 가 오래된 턴을 압축한 digest 로 만들어줘서 Stage 2 가 컨텍스트를 작게 유지하도록 도와줍니다.',
    },
  ],
};

export const stage02Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
