/**
 * Stage 18 (memory) — supplementary detail content for the info modal.
 *
 * Sourced from
 *   src/geny_executor/stages/s18_memory/{strategy.py, persistence.py, artifact/default/stage.py}
 *   Geny's `service/memory/*` integration layer (per-session file
 *   directories, opsidian sync, etc.)
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Stateless agent (single-turn)',
      body: 'Pick `no_memory` strategy + `null` persistence. The agent will treat every turn as a fresh conversation. Useful for retrieval bots, classification endpoints, or agents that intentionally forget for privacy reasons.',
    },
    {
      title: 'Long-running personal assistant',
      body: 'Pick `structured_reflective` strategy + `file` persistence. Each turn the LLM extracts typed insights (entities, projects, decisions) into JSON files under `.geny/memory/`. Costs ~1 cheap LLM call per turn but the agent gains real long-term recall.',
    },
    {
      title: 'Full transcript preservation',
      body: 'Pick `append_only` strategy + `file` persistence. Every message is saved verbatim. Memory grows unbounded — pair with Stage 19 (summarize) or aggressive context pruning in Stage 2 to control token spend.',
    },
  ],
  configurations: [
    {
      name: 'Quick stateless',
      summary: 'Truly forgetful — no LLM calls, no disk writes.',
      highlights: ['strategy: no_memory', 'persistence: null'],
    },
    {
      name: 'Production VTuber persona',
      summary: 'Remembers viewer context across streams without exploding cost.',
      highlights: [
        'strategy: structured_reflective',
        'persistence: file',
        'config.file.base_dir: .geny/memory',
        'model_override: claude-haiku-4-5 (cheap reflector)',
      ],
    },
    {
      name: 'Debug transcript',
      summary: 'Keep everything in memory, no disk writes — for development only.',
      highlights: ['strategy: append_only', 'persistence: in_memory'],
    },
  ],
  pitfalls: [
    {
      title: 'Reflective without a model_override hits the main API model',
      body: 'If `strategy = reflective` and `model_override = null`, the reflector reuses pipeline.model — usually the same expensive model your Stage 6 uses. Drop in a cheap haiku as model_override to slash memory-stage cost ~5×.',
    },
    {
      title: 'File persistence on a read-only filesystem',
      body: 'Container deployments often mount the working directory read-only. file persistence will silently fail — memory writes succeed in-memory then disappear at process end. Either pick `in_memory` deliberately, or bind-mount a writable volume to base_dir.',
    },
    {
      title: 'append_only without Stage 19 summarize',
      body: 'append_only with no summarisation step will eventually overflow context window. Either enable Stage 19 (summarize) or let Stage 2 (context) compact aggressively (lower context_window_budget).',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s18_memory/strategy.py',
      description: 'Strategy + persistence slot definitions.',
    },
    {
      label: 'geny-executor / stages/s18_memory/persistence.py',
      description: 'NullPersistence / InMemoryPersistence / FilePersistence implementations.',
    },
    {
      label: 'geny-executor / stages/s18_memory/artifact/default/stage.py',
      description: 'Default artifact: build memory snapshot from state.messages, run strategy, hand to persistence.',
    },
    {
      label: 'Geny / backend/service/memory/*',
      description: 'Geny-side bindings: per-session memory directories under .geny/sessions/<sid>/memory/, opsidian sync hooks.',
    },
  ],
  relatedStages: [
    {
      order: 2,
      reason: 'Stage 2 (context) reads back the persisted memory chunks via its retriever — Stage 18 is the writer, Stage 2 is the reader.',
    },
    {
      order: 19,
      reason: 'Stage 19 (summarize) runs after Stage 18 to produce a condensed digest of what was just persisted, keeping context window pressure low.',
    },
    {
      order: 20,
      reason: 'Stage 20 (persist) flushes any other run-end artifacts; Stage 18 specifically owns memory files.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Stateless 에이전트 (single-turn)',
      body: '`no_memory` 전략 + `null` persistence 선택. 에이전트는 매 턴을 새로운 대화로 취급합니다. retrieval 봇, 분류 엔드포인트, 프라이버시상 의도적으로 잊어야 하는 에이전트에 유용합니다.',
    },
    {
      title: '장기 개인 비서',
      body: '`structured_reflective` 전략 + `file` persistence 선택. 매 턴 LLM 이 타입드 인사이트 (엔티티, 프로젝트, 결정사항) 를 `.geny/memory/` 의 JSON 파일에 추출합니다. 턴당 저렴한 LLM 호출 ~1회 비용으로 진짜 장기 기억을 얻습니다.',
    },
    {
      title: '전체 대화 보존',
      body: '`append_only` 전략 + `file` persistence 선택. 모든 메시지가 그대로 저장됩니다. 메모리가 무한 증가 — Stage 19 (summarize) 와 페어링하거나 Stage 2 의 적극적인 context 가지치기로 토큰 소모를 통제하세요.',
    },
  ],
  configurations: [
    {
      name: '빠른 stateless',
      summary: '진짜 망각형 — LLM 호출 없음, 디스크 쓰기 없음.',
      highlights: ['strategy: no_memory', 'persistence: null'],
    },
    {
      name: '프로덕션 VTuber 페르소나',
      summary: '비용 폭발 없이 시청자 컨텍스트를 스트림 간 기억.',
      highlights: [
        'strategy: structured_reflective',
        'persistence: file',
        'config.file.base_dir: .geny/memory',
        'model_override: claude-haiku-4-5 (저렴한 reflector)',
      ],
    },
    {
      name: '디버그 대화록',
      summary: '모두 인메모리에 보관, 디스크 쓰기 없음 — 개발 전용.',
      highlights: ['strategy: append_only', 'persistence: in_memory'],
    },
  ],
  pitfalls: [
    {
      title: 'model_override 없는 reflective 는 메인 API 모델 사용',
      body: '`strategy = reflective` 인데 `model_override = null` 이면 reflector 가 pipeline.model 을 재사용 — 대개 Stage 6 에서 쓰는 비싼 모델과 동일합니다. model_override 에 저렴한 haiku 를 넣으면 메모리 단계 비용을 약 5배 절감할 수 있습니다.',
    },
    {
      title: '읽기 전용 파일시스템에서 file persistence',
      body: '컨테이너 배포는 작업 디렉토리를 read-only 로 마운트하는 경우가 많습니다. file persistence 가 silently 실패 — 메모리 쓰기는 인메모리에서 성공한 척하다 프로세스 종료 시 사라집니다. 의도적으로 `in_memory` 를 선택하거나, 쓰기 가능한 볼륨을 base_dir 에 bind-mount 하세요.',
    },
    {
      title: 'Stage 19 summarize 없이 append_only',
      body: '요약 단계 없는 append_only 는 결국 context window 를 넘칩니다. Stage 19 (summarize) 를 활성화하거나 Stage 2 (context) 가 적극적으로 압축하게 (context_window_budget 낮추기) 하세요.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s18_memory/strategy.py',
      description: '전략 + persistence 슬롯 정의.',
    },
    {
      label: 'geny-executor / stages/s18_memory/persistence.py',
      description: 'NullPersistence / InMemoryPersistence / FilePersistence 구현.',
    },
    {
      label: 'geny-executor / stages/s18_memory/artifact/default/stage.py',
      description: '기본 아티팩트: state.messages 에서 memory snapshot 빌드 → 전략 실행 → persistence 로 전달.',
    },
    {
      label: 'Geny / backend/service/memory/*',
      description: 'Geny 측 바인딩: .geny/sessions/<sid>/memory/ 의 세션별 메모리 디렉토리, opsidian sync 훅.',
    },
  ],
  relatedStages: [
    {
      order: 2,
      reason: 'Stage 2 (context) 의 retriever 가 영속화된 메모리 청크를 다시 읽습니다 — Stage 18 이 writer, Stage 2 가 reader.',
    },
    {
      order: 19,
      reason: 'Stage 19 (summarize) 가 Stage 18 직후 실행되어 방금 영속화된 내용의 요약본을 생산, context window 압력을 낮춥니다.',
    },
    {
      order: 20,
      reason: 'Stage 20 (persist) 는 다른 run-end 아티팩트를 flush 합니다; Stage 18 은 specifically 메모리 파일을 담당합니다.',
    },
  ],
};

export const stage18Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
