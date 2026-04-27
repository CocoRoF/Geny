/**
 * Stage 15 (hitl) — human-in-the-loop. Pauses the pipeline when a
 * tool call (or other event) requires human approval before proceeding.
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Auto-approve — fully autonomous',
      body: 'requester=null + timeout=indefinite. Every HITL request is auto-approved. Use for headless / CI runs where there is no human listener.',
    },
    {
      title: 'Pipeline-resume — UI-driven approval',
      body: 'requester=pipeline_resume. The pipeline pauses; an external API (e.g. Geny\'s WebSocket panel) presents the request to a human and posts the decision back. Standard for interactive deployments.',
    },
    {
      title: 'Auto-reject after timeout',
      body: 'timeout=auto_reject + timeout_seconds=60. If a human doesn\'t respond within 60s, the request is rejected — safe default for production agents that should never act without explicit approval.',
    },
  ],
  configurations: [
    {
      name: 'Headless / CI',
      summary: 'No human, everything passes.',
      highlights: [
        'requester: null',
        'timeout: indefinite',
      ],
    },
    {
      name: 'Production interactive',
      summary: 'Human approval, fail-safe on timeout.',
      highlights: [
        'requester: pipeline_resume',
        'timeout: auto_reject',
        'config.auto_reject.timeout_seconds: 120',
      ],
    },
    {
      name: 'Trusted operator (auto-approve on timeout)',
      summary: 'Human can approve faster but absent → continue.',
      highlights: [
        'requester: pipeline_resume',
        'timeout: auto_approve',
        'config.auto_approve.timeout_seconds: 30',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'pipeline_resume without an external listener',
      body: 'requester=pipeline_resume waits forever for an external API call. If no UI / API is wired up, the agent hangs indefinitely. Always pair with a timeout strategy.',
    },
    {
      title: 'auto_approve as default',
      body: 'auto_approve effectively turns HITL into a no-op for cases the human ignored. Use auto_reject as your safe default and only auto_approve in trusted internal flows.',
    },
    {
      title: 'HITL invoked from a tool inside a sub-agent',
      body: 'The HITL request travels up through Stage 12 to the parent pipeline. If the parent has Stage 15 disabled, the request is silently dropped — the sub-agent then sees a synthetic "approved" response. Audit Stage 15 across parent + child pipelines.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s15_hitl/strategy.py',
      description: 'requester + timeout slot definitions.',
    },
    {
      label: 'geny-executor / stages/s15_hitl/types.py',
      description: 'HITLRequest / HITLDecision / HITLEntry dataclasses.',
    },
    {
      label: 'Geny / backend/ws/hitl_stream.py',
      description: 'Geny-side WebSocket bridge for pipeline_resume requests.',
    },
  ],
  relatedStages: [
    {
      order: 11,
      reason: 'Stage 11 (tool_review) flags can route into Stage 15 — a flagged tool call asks for human approval before Stage 10 fires it.',
    },
    {
      order: 14,
      reason: 'Stage 14 (evaluate) sees HITL outcomes in state.shared[\'hitl_history\'] and can decide whether to terminate based on rejections.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '자동 승인 — 완전 자율',
      body: 'requester=null + timeout=indefinite. 모든 HITL 요청이 자동 승인. 헤드리스 / CI 실행에 사용 — 사람 청취자가 없을 때.',
    },
    {
      title: 'Pipeline-resume — UI 기반 승인',
      body: 'requester=pipeline_resume. 파이프라인 일시정지; 외부 API (예: Geny WebSocket 패널) 가 요청을 사람에게 제시하고 결정을 다시 POST. 인터랙티브 배포 표준.',
    },
    {
      title: '타임아웃 후 자동 거부',
      body: 'timeout=auto_reject + timeout_seconds=60. 사람이 60초 안에 응답 안 하면 거부 — 명시적 승인 없이 절대 행동해선 안 되는 프로덕션 에이전트의 안전 기본값.',
    },
  ],
  configurations: [
    {
      name: '헤드리스 / CI',
      summary: '사람 없음, 모두 통과.',
      highlights: [
        'requester: null',
        'timeout: indefinite',
      ],
    },
    {
      name: '프로덕션 인터랙티브',
      summary: '사람 승인, 타임아웃 시 안전 거부.',
      highlights: [
        'requester: pipeline_resume',
        'timeout: auto_reject',
        'config.auto_reject.timeout_seconds: 120',
      ],
    },
    {
      name: '신뢰된 운영자 (타임아웃 시 자동 승인)',
      summary: '사람이 빨리 승인 가능하지만 부재 시 → 계속.',
      highlights: [
        'requester: pipeline_resume',
        'timeout: auto_approve',
        'config.auto_approve.timeout_seconds: 30',
      ],
    },
  ],
  pitfalls: [
    {
      title: '외부 청취자 없는 pipeline_resume',
      body: 'requester=pipeline_resume 가 외부 API 호출을 영원히 기다림. UI / API 가 wire up 안 됐으면 에이전트가 무한 hang. 반드시 timeout 전략과 페어링.',
    },
    {
      title: 'auto_approve 를 기본으로',
      body: 'auto_approve 는 사람이 무시한 케이스에서 HITL 을 사실상 no-op 으로 만듦. 안전 기본값은 auto_reject, 신뢰된 내부 플로우에서만 auto_approve.',
    },
    {
      title: '서브 에이전트 내부 도구의 HITL 호출',
      body: 'HITL 요청은 Stage 12 를 통해 부모 파이프라인까지 올라감. 부모가 Stage 15 비활성화면 silent 드롭 — 서브 에이전트는 합성된 "승인됨" 응답을 봄. 부모 + 자식 파이프라인 양쪽에서 Stage 15 를 감사하세요.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s15_hitl/strategy.py',
      description: 'requester + timeout 슬롯 정의.',
    },
    {
      label: 'geny-executor / stages/s15_hitl/types.py',
      description: 'HITLRequest / HITLDecision / HITLEntry dataclasses.',
    },
    {
      label: 'Geny / backend/ws/hitl_stream.py',
      description: 'pipeline_resume 요청을 위한 Geny 측 WebSocket 브리지.',
    },
  ],
  relatedStages: [
    {
      order: 11,
      reason: 'Stage 11 (tool_review) flag 가 Stage 15 로 라우팅 가능 — flag 된 도구 호출이 Stage 10 발화 전에 사람 승인 요청.',
    },
    {
      order: 14,
      reason: 'Stage 14 (evaluate) 가 state.shared[\'hitl_history\'] 의 HITL 결과를 보고 거부 기반으로 종료 결정.',
    },
  ],
};

export const stage15Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
