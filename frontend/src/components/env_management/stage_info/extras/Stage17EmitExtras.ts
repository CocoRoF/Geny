/**
 * Stage 17 (emit) — pushes the assembled response to output channels
 * (chat panel, websocket stream, log file).
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default — chat + log',
      body: 'DefaultEmitter writes the final response to the chat channel (visible to the user) and to the structured log (visible to Geny\'s log viewer). Suitable for almost every agent.',
    },
    {
      title: 'Streaming chunks',
      body: 'StreamingEmitter pushes incremental text chunks as the LLM generates them — for VTuber TTS pipelines that need to start speaking before the full response lands.',
    },
    {
      title: 'Silent / log-only',
      body: 'LogOnlyEmitter writes to the log but emits nothing to the chat channel — useful for "background" agents that observe but should not interrupt.',
    },
  ],
  configurations: [
    {
      name: 'Standard chat',
      summary: 'Chat + log channels.',
      highlights: ['emitter: DefaultEmitter'],
    },
    {
      name: 'VTuber streaming',
      summary: 'Chunk-by-chunk to TTS pipeline.',
      highlights: ['emitter: StreamingEmitter'],
    },
    {
      name: 'Background observer',
      summary: 'No chat output, log only.',
      highlights: ['emitter: LogOnlyEmitter'],
    },
  ],
  pitfalls: [
    {
      title: 'StreamingEmitter without a streaming client',
      body: 'If the consuming WebSocket / SSE channel can\'t handle partial chunks, you get a flood of incomplete fragments. Make sure the front-end consumer is chunk-aware before flipping this.',
    },
    {
      title: 'LogOnlyEmitter on a user-facing agent',
      body: 'Disabling chat output silently can confuse users — they ask a question and see no response. Combine with a metadata channel ("agent processed in background") if you go this route.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s17_emit/strategy.py',
      description: 'Emitter slot definitions.',
    },
    {
      label: 'Geny / backend/ws/execute_stream.py',
      description: 'Geny-side WebSocket bridge consumed by StreamingEmitter.',
    },
  ],
  relatedStages: [
    {
      order: 14,
      reason: 'Stage 14 (evaluate) decides termination; Stage 17 only fires once Stage 14 has signed off.',
    },
    {
      order: 21,
      reason: 'Stage 21 (yield) returns the same response value to the caller; Stage 17 emits to channels, Stage 21 returns programmatically.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '기본 — 채팅 + 로그',
      body: 'DefaultEmitter 가 최종 응답을 채팅 채널 (사용자에게 표시) 과 구조화된 로그 (Geny 로그 뷰어에 표시) 에 작성. 거의 모든 에이전트에 적합.',
    },
    {
      title: '스트리밍 청크',
      body: 'StreamingEmitter 가 LLM 생성 즉시 점진적 텍스트 청크를 push — 전체 응답 도착 전에 말하기를 시작해야 하는 VTuber TTS 파이프라인용.',
    },
    {
      title: 'Silent / log-only',
      body: 'LogOnlyEmitter 가 로그에만 기록하고 채팅 채널엔 emit 하지 않음 — 관찰만 하고 방해하면 안 되는 "백그라운드" 에이전트에 유용.',
    },
  ],
  configurations: [
    {
      name: '표준 채팅',
      summary: '채팅 + 로그 채널.',
      highlights: ['emitter: DefaultEmitter'],
    },
    {
      name: 'VTuber 스트리밍',
      summary: '청크 단위로 TTS 파이프라인에.',
      highlights: ['emitter: StreamingEmitter'],
    },
    {
      name: '백그라운드 관찰자',
      summary: '채팅 출력 없음, 로그만.',
      highlights: ['emitter: LogOnlyEmitter'],
    },
  ],
  pitfalls: [
    {
      title: '스트리밍 클라이언트 없는 StreamingEmitter',
      body: '소비하는 WebSocket / SSE 채널이 부분 청크를 처리 못 하면 미완성 fragment 가 쏟아짐. 켜기 전에 프론트 소비자가 chunk-aware 인지 확인하세요.',
    },
    {
      title: '사용자 대면 에이전트의 LogOnlyEmitter',
      body: '채팅 출력을 silent 로 끄면 사용자가 혼란스러워함 — 질문했는데 응답이 안 보임. 이 경로 가려면 메타데이터 채널 ("에이전트가 백그라운드에서 처리") 과 결합.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s17_emit/strategy.py',
      description: 'Emitter 슬롯 정의.',
    },
    {
      label: 'Geny / backend/ws/execute_stream.py',
      description: 'StreamingEmitter 가 소비하는 Geny 측 WebSocket 브리지.',
    },
  ],
  relatedStages: [
    {
      order: 14,
      reason: 'Stage 14 (evaluate) 가 종료 결정; Stage 17 은 Stage 14 승인 후에만 발화.',
    },
    {
      order: 21,
      reason: 'Stage 21 (yield) 가 호출자에게 같은 응답 값을 반환; Stage 17 은 채널에 emit, Stage 21 은 프로그래밍 방식 반환.',
    },
  ],
};

export const stage17Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
