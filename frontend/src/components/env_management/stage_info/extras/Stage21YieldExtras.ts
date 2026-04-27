/**
 * Stage 21 (yield) — produces the final return value the host caller
 * receives. Different shapes for different consumers (chat client,
 * structured API, sub-agent parent).
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default — chat response object',
      body: 'ChatYielder returns a ChatResponse with text + metadata (tool calls made, cost, turn count). Standard for chat agents.',
    },
    {
      title: 'Structured JSON yield',
      body: 'JsonYielder parses the final response as JSON against a schema and returns the typed object. Use for API endpoints that consume agent output programmatically.',
    },
    {
      title: 'Sub-agent yield',
      body: 'SubAgentYielder returns a compact result for the parent pipeline\'s Stage 12 — typically the final text + the most-relevant tool result. Avoids drowning the parent in subtask noise.',
    },
  ],
  configurations: [
    {
      name: 'Default chat',
      summary: 'ChatResponse with text + metadata.',
      highlights: ['yielder: ChatYielder'],
    },
    {
      name: 'API endpoint',
      summary: 'Typed JSON against a schema.',
      highlights: [
        'yielder: JsonYielder',
        'config.schema: {...}',
      ],
    },
    {
      name: 'Sub-agent result',
      summary: 'Compact summary for parent pipeline.',
      highlights: ['yielder: SubAgentYielder'],
    },
  ],
  pitfalls: [
    {
      title: 'Disabling Stage 21 returns nothing',
      body: 'Stage 21 is the only stage that produces the final return value. Without it, the caller sees a None / null result. Stage 17 (emit) still pushes to channels, but the caller-side return is empty.',
    },
    {
      title: 'JsonYielder schema mismatch',
      body: 'If the LLM\'s final text isn\'t valid JSON for the schema, JsonYielder either falls back to raw text (with a flag) or raises. Pick the failure mode explicitly via config.on_schema_fail.',
    },
    {
      title: 'SubAgentYielder loses detail',
      body: 'The parent pipeline only sees the compact summary, not the full sub-agent transcript. If the parent needs to inspect what the sub-agent did, switch to ChatYielder for the sub-agent too — but be ready for higher token spend on the parent side.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s21_yield/strategy.py',
      description: 'Yielder slot definitions.',
    },
    {
      label: 'geny-executor / core/state.py',
      description: 'state structure that Stage 21 packages into the return value.',
    },
  ],
  relatedStages: [
    {
      order: 17,
      reason: 'Stage 17 (emit) pushes to channels; Stage 21 returns to the caller. Two distinct exit paths.',
    },
    {
      order: 12,
      reason: 'Stage 12 (agent) of a parent pipeline consumes Stage 21\'s SubAgentYielder result.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '기본 — 채팅 응답 객체',
      body: 'ChatYielder 가 텍스트 + 메타데이터 (도구 호출 수, 비용, 턴 수) 의 ChatResponse 반환. 채팅 에이전트 표준.',
    },
    {
      title: '구조화 JSON yield',
      body: 'JsonYielder 가 최종 응답을 스키마에 맞춰 JSON 으로 파싱하고 타입드 객체 반환. 에이전트 출력을 프로그래밍 방식으로 소비하는 API 엔드포인트용.',
    },
    {
      title: '서브 에이전트 yield',
      body: 'SubAgentYielder 가 부모 파이프라인의 Stage 12 에 컴팩트 결과 반환 — 보통 최종 텍스트 + 가장 관련 있는 도구 결과. 부모를 서브태스크 잡음에 빠뜨리지 않음.',
    },
  ],
  configurations: [
    {
      name: '기본 채팅',
      summary: '텍스트 + 메타데이터의 ChatResponse.',
      highlights: ['yielder: ChatYielder'],
    },
    {
      name: 'API 엔드포인트',
      summary: '스키마에 맞는 타입드 JSON.',
      highlights: [
        'yielder: JsonYielder',
        'config.schema: {...}',
      ],
    },
    {
      name: '서브 에이전트 결과',
      summary: '부모 파이프라인용 컴팩트 요약.',
      highlights: ['yielder: SubAgentYielder'],
    },
  ],
  pitfalls: [
    {
      title: 'Stage 21 비활성화 시 아무것도 반환 안 함',
      body: 'Stage 21 이 최종 반환값을 생산하는 유일한 단계. 없으면 호출자는 None / null 결과. Stage 17 (emit) 은 여전히 채널에 push 하지만 호출자 측 반환은 비어있음.',
    },
    {
      title: 'JsonYielder 스키마 불일치',
      body: 'LLM 최종 텍스트가 스키마에 맞는 유효 JSON 이 아니면 JsonYielder 가 raw 텍스트로 fallback (flag 와 함께) 하거나 raise. config.on_schema_fail 로 실패 모드를 명시적으로 선택.',
    },
    {
      title: 'SubAgentYielder 디테일 손실',
      body: '부모 파이프라인은 컴팩트 요약만 보고 전체 서브 에이전트 transcript 는 못 봄. 부모가 서브 에이전트의 행동을 검사해야 한다면 서브 에이전트도 ChatYielder 로 — 하지만 부모 측 토큰 소모 증가에 대비.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s21_yield/strategy.py',
      description: 'Yielder 슬롯 정의.',
    },
    {
      label: 'geny-executor / core/state.py',
      description: 'Stage 21 이 반환값으로 패키징하는 state 구조.',
    },
  ],
  relatedStages: [
    {
      order: 17,
      reason: 'Stage 17 (emit) 이 채널에 push; Stage 21 이 호출자에 반환. 두 개의 별개 exit 경로.',
    },
    {
      order: 12,
      reason: '부모 파이프라인의 Stage 12 (agent) 가 Stage 21 의 SubAgentYielder 결과를 소비.',
    },
  ],
};

export const stage21Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
