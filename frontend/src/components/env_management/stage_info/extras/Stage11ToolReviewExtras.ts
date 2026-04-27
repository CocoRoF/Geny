/**
 * Stage 11 (tool_review) — chain of reviewers that inspect each tool
 * call BEFORE Stage 10 actually executes it.
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default — full review chain',
      body: 'All five reviewers run in order: Schema → SensitivePattern → DestructiveResult → NetworkAudit → Size. Catches schema drift, secrets in tool args, dangerous shell verbs, network egress, and oversized payloads.',
    },
    {
      title: 'Schema-only (lightweight CI)',
      body: 'Drop everything except SchemaReviewer for fast pipelines that only need to catch malformed tool args. Saves ~100ms / turn but loses the safety net.',
    },
    {
      title: 'Maximum paranoia',
      body: 'Add custom reviewers via the chain. Order matters: cheap regex-based reviewers (SensitivePattern) before LLM-based ones (a hypothetical SemanticReviewer) so cheap rejects fire fast.',
    },
  ],
  configurations: [
    {
      name: 'Default — production',
      summary: 'All five reviewers, default order.',
      highlights: [
        'chain: [SchemaReviewer, SensitivePatternReviewer, DestructiveResultReviewer, NetworkAuditReviewer, SizeReviewer]',
      ],
    },
    {
      name: 'CI fast path',
      summary: 'Schema only.',
      highlights: ['chain: [SchemaReviewer]'],
    },
    {
      name: 'Tighter sensitive-pattern config',
      summary: 'Custom regex list for company-specific secrets.',
      highlights: [
        'chain: default',
        'strategy_configs.SensitivePatternReviewer.patterns: [".*GENY_TOKEN_.*", ".*-api-key=.*"]',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'Empty chain on active stage',
      body: 'If active=true and the chain has zero entries, every tool call passes unchecked. The frontend warns about this — the warning is your last line of defence.',
    },
    {
      title: 'Reviewer order matters',
      body: 'Reviewers can short-circuit on hard flags. Cheap regex reviewers should fire FIRST so a sensitive-data hit doesn\'t pay for an expensive subsequent reviewer.',
    },
    {
      title: 'Flag != block',
      body: 'Reviewers append flags to state.shared[\'tool_review_flags\']. They don\'t block tool calls themselves — Stage 14 (evaluate) decides what to do with flags. Configure Stage 14 to actually halt on flag severity.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s11_tool_review/strategy.py',
      description: 'Reviewer chain definition.',
    },
    {
      label: 'geny-executor / stages/s11_tool_review/artifact/default/stage.py',
      description: 'Default chain wiring + flag accumulation.',
    },
  ],
  relatedStages: [
    {
      order: 4,
      reason: 'Stage 4 (guard) is the symmetric input-side guard. Stage 11 reviews tool calls; Stage 4 reviews the user input.',
    },
    {
      order: 10,
      reason: 'Stage 10 (tools) executes the call after Stage 11 reviews it. Reviewers run BEFORE the tool fires.',
    },
    {
      order: 14,
      reason: 'Stage 14 (evaluate) reads tool_review_flags from state.shared and decides loop fate.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '기본 — 전체 리뷰 체인',
      body: '5개 리뷰어가 순서대로 실행: Schema → SensitivePattern → DestructiveResult → NetworkAudit → Size. 스키마 drift, 도구 인자의 시크릿, 위험한 shell 동사, 네트워크 egress, 과대 페이로드를 잡습니다.',
    },
    {
      title: 'Schema-only (가벼운 CI)',
      body: '잘못된 도구 인자만 빠르게 잡으면 되는 파이프라인은 SchemaReviewer 외에 모두 제거. 턴당 ~100ms 절약하지만 안전망을 잃습니다.',
    },
    {
      title: '최대 편집증',
      body: '체인에 커스텀 리뷰어 추가. 순서가 중요: 저렴한 regex 기반 리뷰어 (SensitivePattern) 가 LLM 기반 (가상의 SemanticReviewer) 앞에 와야 저렴한 거부가 빠르게 발화.',
    },
  ],
  configurations: [
    {
      name: '기본 — 프로덕션',
      summary: '5개 리뷰어, 기본 순서.',
      highlights: [
        'chain: [SchemaReviewer, SensitivePatternReviewer, DestructiveResultReviewer, NetworkAuditReviewer, SizeReviewer]',
      ],
    },
    {
      name: 'CI 빠른 경로',
      summary: 'Schema 만.',
      highlights: ['chain: [SchemaReviewer]'],
    },
    {
      name: '엄격한 sensitive-pattern 설정',
      summary: '회사별 시크릿용 커스텀 regex 목록.',
      highlights: [
        'chain: default',
        'strategy_configs.SensitivePatternReviewer.patterns: [".*GENY_TOKEN_.*", ".*-api-key=.*"]',
      ],
    },
  ],
  pitfalls: [
    {
      title: '활성 단계인데 빈 체인',
      body: 'active=true 인데 체인이 비어 있으면 모든 도구 호출이 검사 없이 통과. 프론트가 경고 — 그 경고가 마지막 방어선입니다.',
    },
    {
      title: '리뷰어 순서가 중요',
      body: '리뷰어는 hard flag 에 단락 (short-circuit) 가능. 저렴한 regex 리뷰어가 먼저 발화하도록 — 민감 데이터 적중이 비싼 후속 리뷰어 비용을 지불하지 않게.',
    },
    {
      title: 'Flag != 차단',
      body: '리뷰어는 state.shared[\'tool_review_flags\'] 에 flag 를 추가. 도구 호출 자체를 차단하지는 않습니다 — Stage 14 (evaluate) 가 flag 처리를 결정. Stage 14 가 flag 심각도에 따라 실제 중단하도록 설정하세요.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s11_tool_review/strategy.py',
      description: '리뷰어 체인 정의.',
    },
    {
      label: 'geny-executor / stages/s11_tool_review/artifact/default/stage.py',
      description: '기본 체인 wiring + flag 누적.',
    },
  ],
  relatedStages: [
    {
      order: 4,
      reason: 'Stage 4 (guard) 는 입력 측 대칭 가드. Stage 11 이 도구 호출 검토, Stage 4 가 사용자 입력 검토.',
    },
    {
      order: 10,
      reason: 'Stage 11 검토 후 Stage 10 (tools) 가 호출 실행. 리뷰어는 도구 실행 전에 발화.',
    },
    {
      order: 14,
      reason: 'Stage 14 (evaluate) 가 state.shared 의 tool_review_flags 를 읽어 루프 운명을 결정.',
    },
  ],
};

export const stage11Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
