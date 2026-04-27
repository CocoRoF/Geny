/**
 * Stage 13 (task_registry) — long-running background task tracking.
 * The TaskCreate tool registers entries here; the BackgroundTaskRunner
 * polls the registry to drive each task forward.
 */

import type {
  StageInfoExtrasContent,
  StageInfoExtrasFactory,
} from '../types';

const en: StageInfoExtrasContent = {
  useCases: [
    {
      title: 'Default — in-process registry',
      body: 'InProcessRegistry holds tasks in memory for the current pipeline run. Tasks vanish at process end. Suitable for short investigative agents.',
    },
    {
      title: 'Persistent registry (file-backed)',
      body: 'FileRegistry keeps task state under .geny/sessions/<sid>/tasks/. Tasks survive process restarts — necessary for long-running cron / scheduled agents.',
    },
    {
      title: 'Disabled — no background tasks',
      body: 'Disable Stage 13 if your agent never uses TaskCreate. The TaskCreate tool then becomes a no-op (it logs a warning and returns success without queueing).',
    },
  ],
  configurations: [
    {
      name: 'Default',
      summary: 'In-process tasks, lost on restart.',
      highlights: ['registry: InProcessRegistry'],
    },
    {
      name: 'Production scheduled agent',
      summary: 'File-backed, survives restarts.',
      highlights: [
        'registry: FileRegistry',
        'config.file.base_dir: .geny/sessions/{sid}/tasks',
      ],
    },
  ],
  pitfalls: [
    {
      title: 'Agent loops while waiting for tasks',
      body: 'If a task is "in flight" but Stage 14 (evaluate) doesn\'t know to wait for it, the loop terminates before the task finishes. Configure Stage 14 to check task_registry status when deciding to terminate.',
    },
    {
      title: 'File registry on shared volumes',
      body: 'Multiple agents writing to the same FileRegistry directory race on file locks. Either give each agent its own dir or switch to a database-backed registry (custom).',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s13_task_registry/strategy.py',
      description: 'Registry slot definitions.',
    },
    {
      label: 'geny-executor / tools/built_in/task.py',
      description: 'TaskCreate / TaskGet / TaskList / TaskUpdate tools wired to this stage.',
    },
    {
      label: 'Geny / backend/service/tasks/runner.py',
      description: 'BackgroundTaskRunner — Geny-side polling driver.',
    },
  ],
  relatedStages: [
    {
      order: 10,
      reason: 'Stage 10 (tools) routes TaskCreate / TaskGet calls into Stage 13.',
    },
    {
      order: 14,
      reason: 'Stage 14 (evaluate) can be configured to keep the loop alive while pending tasks exist.',
    },
  ],
};

const ko: StageInfoExtrasContent = {
  useCases: [
    {
      title: '기본 — 인프로세스 레지스트리',
      body: 'InProcessRegistry 가 현재 파이프라인 실행의 메모리에 태스크 보관. 프로세스 종료 시 사라짐. 짧은 조사 에이전트에 적합.',
    },
    {
      title: '영속 레지스트리 (파일 기반)',
      body: 'FileRegistry 가 .geny/sessions/<sid>/tasks/ 에 태스크 상태 보관. 프로세스 재시작 후에도 유지 — 장기 cron / 스케줄 에이전트에 필수.',
    },
    {
      title: '비활성화 — 백그라운드 태스크 없음',
      body: '에이전트가 TaskCreate 를 절대 안 쓴다면 Stage 13 비활성화. TaskCreate 도구가 no-op 이 됨 (warning 로그 후 큐잉 없이 성공 반환).',
    },
  ],
  configurations: [
    {
      name: '기본',
      summary: '인프로세스 태스크, 재시작 시 손실.',
      highlights: ['registry: InProcessRegistry'],
    },
    {
      name: '프로덕션 스케줄 에이전트',
      summary: '파일 기반, 재시작 후에도 유지.',
      highlights: [
        'registry: FileRegistry',
        'config.file.base_dir: .geny/sessions/{sid}/tasks',
      ],
    },
  ],
  pitfalls: [
    {
      title: '태스크 대기 중 에이전트 루프 종료',
      body: '태스크가 "in flight" 인데 Stage 14 (evaluate) 가 그걸 모르면 태스크 완료 전에 루프 종료. Stage 14 가 종료 결정 시 task_registry 상태를 확인하도록 설정.',
    },
    {
      title: '공유 볼륨의 파일 레지스트리',
      body: '같은 FileRegistry 디렉토리에 여러 에이전트가 쓰면 파일 락 race. 각 에이전트에 자기 디렉토리를 주거나 DB 기반 레지스트리 (커스텀) 로 전환.',
    },
  ],
  codeReferences: [
    {
      label: 'geny-executor / stages/s13_task_registry/strategy.py',
      description: 'Registry 슬롯 정의.',
    },
    {
      label: 'geny-executor / tools/built_in/task.py',
      description: '이 단계에 wired 된 TaskCreate / TaskGet / TaskList / TaskUpdate 도구.',
    },
    {
      label: 'Geny / backend/service/tasks/runner.py',
      description: 'BackgroundTaskRunner — Geny 측 폴링 드라이버.',
    },
  ],
  relatedStages: [
    {
      order: 10,
      reason: 'Stage 10 (tools) 이 TaskCreate / TaskGet 호출을 Stage 13 으로 라우팅.',
    },
    {
      order: 14,
      reason: 'Stage 14 (evaluate) 가 pending 태스크가 있을 동안 루프를 유지하도록 설정 가능.',
    },
  ],
};

export const stage13Extras: StageInfoExtrasFactory = (locale) =>
  locale === 'ko' ? ko : en;
