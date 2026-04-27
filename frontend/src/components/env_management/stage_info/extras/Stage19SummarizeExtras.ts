/**
 * Stage 19 (summarize) — produces a digest of the conversation /
 * memory snapshot for downstream context. Implementation is partial
 * in geny-executor at the time of writing; the curated content
 * below describes the intended contract.
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default off — short conversations',
      body: 'For short chat agents (≤ 20 turns) summarisation usually adds cost without benefit. Stage 19 stays inactive.',
    },
    {
      title: 'Long-running agent compression',
      body: 'For agents that stay alive for hundreds of turns, enable Stage 19 with a periodic cadence (every N turns) to fold older history into a digest. Pair with Stage 18 (memory) so the digest is persisted alongside raw transcripts.',
    },
    {
      title: 'Per-session journaling',
      body: 'At session end, run a one-shot summary of "what happened this session" into a journal file the next session can load via Stage 2 retriever.',
    },
  ],
  configurations: [
    {
      name: 'Off',
      summary: 'Short chats — no summarisation needed.',
      highlights: ['active: false'],
    },
    {
      name: 'Periodic compression',
      summary: 'Summarise every N turns.',
      highlights: [
        'active: true',
        'config.cadence_turns: 10',
        'model_override: claude-haiku-4-5',
      ],
    },
    {
      name: 'End-of-session journal',
      summary: 'Single summary at run end.',
      highlights: [
        'active: true',
        'config.run_at: end_of_session',
        'config.output_path: .geny/sessions/{sid}/journal.md',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'Summarising the same content repeatedly',
      body: 'If cadence is too frequent (every turn) the summarizer keeps re-summarising the same digest. Set cadence_turns ≥ 5 so each invocation has new content to add.',
    },
    {
      title: 'Summary model = main model',
      body: 'Without a model_override, the summarizer uses pipeline.model — usually expensive. Always pin a cheap haiku as the summarizer model.',
    },
    {
      title: 'Implementation status',
      body: 'Stage 19 has a defined manifest contract but the executor reference implementation may be partial. Verify the strategies you select are actually available in your build of geny-executor.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s19_summarize/strategy.py',
      description: 'Summarizer slot definitions (where shipped).',
    },
  ],
  relatedStages: [
    {
      order: 2,
      reason: 'Stage 2 (context) reads the digests Stage 19 produces to keep context window pressure low.',
    },
    {
      order: 18,
      reason: 'Stage 18 (memory) persists the raw turns; Stage 19 is the optional compressor on top.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '기본 끄기 — 짧은 대화',
      body: '짧은 채팅 에이전트 (≤ 20턴) 는 요약이 보통 이득 없이 비용만 추가. Stage 19 비활성 유지.',
    },
    {
      title: '장기 실행 에이전트 압축',
      body: '수백 턴 동안 살아있는 에이전트는 주기적 cadence (N턴마다) 로 Stage 19 를 활성화해서 오래된 히스토리를 digest 로 접음. Stage 18 (memory) 와 페어링해서 digest 를 raw transcript 와 함께 영속화.',
    },
    {
      title: '세션별 저널링',
      body: '세션 종료 시 "이번 세션에서 무슨 일이 있었나" 의 일회성 요약을 저널 파일로 → 다음 세션이 Stage 2 retriever 로 로드 가능.',
    },
  ],
  configurations: [
    {
      name: '끔',
      summary: '짧은 채팅 — 요약 불필요.',
      highlights: ['active: false'],
    },
    {
      name: '주기적 압축',
      summary: 'N턴마다 요약.',
      highlights: [
        'active: true',
        'config.cadence_turns: 10',
        'model_override: claude-haiku-4-5',
      ],
    },
    {
      name: '세션 종료 저널',
      summary: '실행 종료 시 단일 요약.',
      highlights: [
        'active: true',
        'config.run_at: end_of_session',
        'config.output_path: .geny/sessions/{sid}/journal.md',
      ],
    },
  ],
  pitfalls: [
    {
      title: '같은 내용을 반복 요약',
      body: 'cadence 가 너무 잦으면 (매 턴) summarizer 가 같은 digest 를 반복 재요약. cadence_turns ≥ 5 로 설정해서 각 호출이 새 콘텐츠를 추가하도록.',
    },
    {
      title: '요약 모델 = 메인 모델',
      body: 'model_override 없으면 summarizer 가 pipeline.model 사용 — 보통 비쌈. 항상 저렴한 haiku 를 summarizer 모델로 지정.',
    },
    {
      title: '구현 상태',
      body: 'Stage 19 는 매니페스트 계약은 정의됐지만 실행기 참조 구현이 부분적일 수 있음. 선택한 전략이 사용 중인 geny-executor 빌드에 실제로 있는지 확인하세요.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s19_summarize/strategy.py',
      description: 'Summarizer 슬롯 정의 (제공되는 경우).',
    },
  ],
  relatedStages: [
    {
      order: 2,
      reason: 'Stage 2 (context) 가 Stage 19 가 생산한 digest 를 읽어 컨텍스트 창 압력을 낮춤.',
    },
    {
      order: 18,
      reason: 'Stage 18 (memory) 가 raw 턴을 영속화; Stage 19 는 그 위의 선택적 압축기.',
    },
  ],
};

export const stage19Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
