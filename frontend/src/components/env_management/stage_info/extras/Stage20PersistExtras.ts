/**
 * Stage 20 (persist) — flushes any non-memory artifacts at run end.
 * State snapshot, checkpoint files, telemetry uploads. Distinct from
 * Stage 18 (memory) which owns memory snapshots specifically.
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default — local checkpoint',
      body: 'LocalCheckpoint writes the final state.metadata + run summary to .geny/sessions/<sid>/checkpoint.json. Useful for debugging "what was the agent thinking at the end" days later.',
    },
    {
      title: 'Telemetry upload',
      body: 'TelemetryUpload sends anonymised metrics (turns, cost, tool counts, error rates) to a configured collector. Use for production agents where you want fleet-level dashboards.',
    },
    {
      title: 'Off — ephemeral runs',
      body: 'For one-off scripted invocations where nothing needs to persist beyond the return value, disable Stage 20 entirely.',
    },
  ],
  configurations: [
    {
      name: 'Default — local checkpoint',
      summary: 'Per-session JSON snapshot.',
      highlights: [
        'persister: LocalCheckpoint',
        'config.local.path: .geny/sessions/{sid}/checkpoint.json',
      ],
    },
    {
      name: 'Production telemetry',
      summary: 'Local + telemetry upload.',
      highlights: [
        'persister: ChainPersister',
        'config.chain: [LocalCheckpoint, TelemetryUpload]',
        'config.telemetry.endpoint: https://...',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'Persist failures crash the pipeline',
      body: 'A failed persist (disk full, network error to telemetry endpoint) can throw before Stage 21 returns the response. Wrap external calls in best-effort persisters that swallow errors and log instead.',
    },
    {
      title: 'PII in checkpoints',
      body: 'state.messages may contain user PII. Local checkpoints landing on a shared volume can leak PII to other operators. Either redact before persisting or restrict the path to a per-user directory.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s20_persist/strategy.py',
      description: 'Persister slot definitions.',
    },
  ],
  relatedStages: [
    {
      order: 18,
      reason: 'Stage 18 (memory) persists memory snapshots; Stage 20 persists everything else (checkpoints, telemetry).',
    },
    {
      order: 21,
      reason: 'Stage 21 (yield) returns AFTER Stage 20 finishes — the checkpoint is on disk before the caller gets the response.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '기본 — 로컬 체크포인트',
      body: 'LocalCheckpoint 가 최종 state.metadata + 실행 요약을 .geny/sessions/<sid>/checkpoint.json 에 작성. 며칠 후 "에이전트가 종료 시 무슨 생각이었나" 디버깅에 유용.',
    },
    {
      title: '텔레메트리 업로드',
      body: 'TelemetryUpload 가 익명 지표 (턴, 비용, 도구 호출 수, 오류율) 를 구성된 collector 에 전송. 플릿 레벨 대시보드를 원하는 프로덕션 에이전트용.',
    },
    {
      title: '끔 — 일회성 실행',
      body: '반환값 외에 영속할 게 없는 일회성 스크립트 호출은 Stage 20 완전히 비활성화.',
    },
  ],
  configurations: [
    {
      name: '기본 — 로컬 체크포인트',
      summary: '세션별 JSON 스냅샷.',
      highlights: [
        'persister: LocalCheckpoint',
        'config.local.path: .geny/sessions/{sid}/checkpoint.json',
      ],
    },
    {
      name: '프로덕션 텔레메트리',
      summary: '로컬 + 텔레메트리 업로드.',
      highlights: [
        'persister: ChainPersister',
        'config.chain: [LocalCheckpoint, TelemetryUpload]',
        'config.telemetry.endpoint: https://...',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'Persist 실패가 파이프라인을 크래시',
      body: '실패한 persist (디스크 풀, 텔레메트리 엔드포인트 네트워크 오류) 가 Stage 21 응답 반환 전에 throw 가능. 외부 호출은 오류를 삼키고 로그하는 best-effort persister 로 감싸세요.',
    },
    {
      title: '체크포인트의 PII',
      body: 'state.messages 에 사용자 PII 가 있을 수 있음. 공유 볼륨에 떨어지는 로컬 체크포인트는 다른 운영자에게 PII 누설. 영속 전 redact 하거나 사용자별 디렉토리로 경로 제한.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s20_persist/strategy.py',
      description: 'Persister 슬롯 정의.',
    },
  ],
  relatedStages: [
    {
      order: 18,
      reason: 'Stage 18 (memory) 가 메모리 스냅샷 영속화; Stage 20 이 그 외 모든 것 (체크포인트, 텔레메트리).',
    },
    {
      order: 21,
      reason: 'Stage 21 (yield) 가 Stage 20 완료 후 반환 — 호출자가 응답 받기 전에 체크포인트가 디스크에 있음.',
    },
  ],
};

export const stage20Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
