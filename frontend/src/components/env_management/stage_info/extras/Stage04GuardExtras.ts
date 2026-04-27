/**
 * Stage 4 (guard) — pre-flight safety check on the assembled request.
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default — light heuristic guard',
      body: 'DefaultGuard runs cheap regex / size checks (no prompt-injection markers, request not absurdly large). Catches obvious failure modes before paying the LLM.',
    },
    {
      title: 'Strict production gate',
      body: 'StrictGuard adds dictionary-based content filtering and forbidden-phrase lists. Use for customer-facing agents where reputation risk matters.',
    },
    {
      title: 'No guard',
      body: 'Disable Stage 4 (or pick PassthroughGuard) for trusted internal pipelines where adding latency to every turn isn\'t worth it.',
    },
  ],
  configurations: [
    {
      name: 'Default — recommended',
      summary: 'Light heuristics, no extra setup.',
      highlights: ['guard: DefaultGuard'],
    },
    {
      name: 'Strict customer-facing',
      summary: 'Dictionary filter + size cap.',
      highlights: [
        'guard: StrictGuard',
        'config.forbidden_phrases: [...]',
        'config.max_request_chars: 32000',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'False positives on legitimate inputs',
      body: 'Strict guards can reject legitimate code snippets that look like prompt injection. Track rejections via state.shared and tune the dictionary; never silently drop turns.',
    },
    {
      title: 'Disabling Stage 4 in tool-using agents',
      body: 'Without Stage 4 a malicious user can attempt prompt injection via tool outputs. Stage 11 (tool_review) catches some of that, but Stage 4 is your first line of defence on input.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s04_guard/strategy.py',
      description: 'Guard slot + DefaultGuard / StrictGuard / PassthroughGuard.',
    },
  ],
  relatedStages: [
    {
      order: 11,
      reason: 'Stage 11 (tool_review) is the symmetric guard on the output side — Stage 4 vets input, Stage 11 vets tool calls.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '기본 — 가벼운 휴리스틱 가드',
      body: 'DefaultGuard 는 저렴한 regex / 크기 검사를 합니다 (prompt injection 마커 없음, 요청이 비정상적으로 크지 않음). LLM 비용 지불 전에 명백한 실패 모드를 잡습니다.',
    },
    {
      title: '엄격한 프로덕션 게이트',
      body: 'StrictGuard 는 사전 기반 콘텐츠 필터와 금지 문구 목록을 추가합니다. 평판 리스크가 중요한 고객 대면 에이전트에 사용하세요.',
    },
    {
      title: '가드 없음',
      body: '신뢰된 내부 파이프라인에서 매 턴 지연을 감수할 가치가 없다면 Stage 4 비활성화 (또는 PassthroughGuard).',
    },
  ],
  configurations: [
    {
      name: '기본 — 권장',
      summary: '가벼운 휴리스틱, 추가 설정 없음.',
      highlights: ['guard: DefaultGuard'],
    },
    {
      name: '엄격한 고객 대면',
      summary: '사전 필터 + 크기 상한.',
      highlights: [
        'guard: StrictGuard',
        'config.forbidden_phrases: [...]',
        'config.max_request_chars: 32000',
      ],
    },
  ],
  pitfalls: [
    {
      title: '정상 입력에 대한 false positive',
      body: '엄격한 가드는 prompt injection 처럼 보이는 정상 코드 스니펫을 거부할 수 있습니다. state.shared 로 거부를 추적하고 사전을 조정하세요; 절대 silent 하게 턴을 버리지 마세요.',
    },
    {
      title: '도구 사용 에이전트에서 Stage 4 비활성화',
      body: 'Stage 4 없이는 악의적 사용자가 도구 출력으로 prompt injection 을 시도할 수 있습니다. Stage 11 (tool_review) 가 일부 잡지만, Stage 4 가 입력 측 첫 번째 방어선입니다.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s04_guard/strategy.py',
      description: 'Guard 슬롯 + DefaultGuard / StrictGuard / PassthroughGuard.',
    },
  ],
  relatedStages: [
    {
      order: 11,
      reason: 'Stage 11 (tool_review) 는 출력 측 대칭 가드 — Stage 4 가 입력 검토, Stage 11 이 도구 호출 검토.',
    },
  ],
};

export const stage04Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
