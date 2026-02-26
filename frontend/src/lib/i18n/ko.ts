/**
 * Korean translations.
 *
 * Every key MUST mirror the English file. Missing keys fall back to English
 * automatically via the `t()` helper.
 */

import type { Translations } from './en';

const ko: Translations = {
  // ─── Global / Layout ───
  app: {
    title: 'Geny — Geny Execute, Not You',
    description: 'Geny: Geny Execute, Not You — 에이전트 세션 관리 및 3D 시티 플레이그라운드',
  },

  // ─── Header ───
  header: {
    subtitle: 'Geny Execute, Not You',
    sessions: '{count}개 세션',
    disconnected: '연결 끊김',
  },

  // ─── Tab Navigation ───
  tabs: {
    main: '메인',
    playground: '플레이그라운드',
    workflows: '워크플로우',
    settings: '설정',
    info: '정보',
    graph: '그래프',
    command: '명령',
    dashboard: '대시보드',
    storage: '스토리지',
    logs: '로그',
  },

  // ─── Sidebar ───
  sidebar: {
    sessions: '세션',
    newSession: '새 세션',
    total: '전체',
    running: '실행 중',
    errors: '오류',
    noSessions: '세션이 없습니다',
    deleteSession: '세션 삭제',
    deletedSessions: '삭제된 세션',
    restore: '복원',
    permanentDelete: '영구 삭제',
    sessionFallback: '세션 {id}',
  },

  // ─── Common ───
  common: {
    save: '저장',
    cancel: '취소',
    delete: '삭제',
    create: '생성',
    edit: '편집',
    close: '닫기',
    loading: '로딩 중...',
    refresh: '새로고침',
    yes: '예',
    no: '아니오',
    enabled: '활성화',
    disabled: '비활성화',
    export: '내보내기',
    import: '가져오기',
    view: '보기',
    clone: '복제',
    reset: '초기화',
    back: '뒤로',
    dismiss: '닫기',
    unknownTab: '알 수 없는 탭',
    selectOption: '-- 선택 --',
    noOutput: '아직 출력이 없습니다',
  },

  // ─── Main Tab ───
  main: {
    langLabel: '언어',
    heroTitle: 'Geny에 오신 것을 환영합니다',
    heroSubtitle: 'Geny Execute, Not You',
    heroTagline: '여러 AI 세션을 관리하고, 복잡한 작업을 오케스트레이션하며, 인터랙티브 3D 시티 플레이그라운드에서 모든 것을 시각화하는 자율 멀티 에이전트 시스템입니다.',
    sections: [
      {
        title: '🚀 시작하기',
        body: [
          '1. 세션 생성 — 사이드바의 "+ 새 세션" 버튼을 클릭하여 새 에이전트 세션을 만드세요. 역할(개발자, 연구원, 매니저, 워커)을 선택하고 이름을 지정하세요.',
          '2. 명령 전송 — 명령 탭으로 전환하여 지시사항을 입력하세요. 에이전트가 자율적으로 작업을 처리합니다.',
          '3. 작업 확인 — 플레이그라운드 탭을 열어 에이전트들이 3D 미니어처 도시를 돌아다니는 캐릭터로 활동하는 모습을 확인하세요!',
        ],
      },
      {
        title: '📂 세션 이해하기',
        body: [
          '각 세션은 독립적인 AI 에이전트로 자체 메모리와 작업 공간을 가집니다. 여러 세션을 동시에 실행할 수 있으며, 각 세션은 서로 간섭 없이 독립적으로 작업합니다.',
          '세션은 사이드바에서 언제든지 일시 중지, 재개 또는 삭제할 수 있습니다. 삭제된 세션은 휴지통으로 이동하며 필요시 복원할 수 있습니다.',
        ],
      },
      {
        title: '🧭 탭 네비게이션',
        body: [
          '• 메인 — 현재 페이지입니다! Geny 사용 가이드가 있는 홈 페이지입니다.',
          '• 플레이그라운드 — 활성 에이전트가 애니메이션 캐릭터로 나타나는 3D 도시 시각화입니다. 패닝, 회전, 줌으로 탐색하세요.',
          '• 설정 — 런타임 설정, 채널 통합 및 고급 옵션을 구성합니다.',
          '• 정보 — 선택한 세션의 상세 정보를 확인합니다.',
          '• 그래프 — 에이전트의 LangGraph 실행 흐름을 실시간으로 시각화합니다.',
          '• 명령 — 에이전트에 지시를 보내고 결과를 확인하는 기본 인터페이스입니다.',
          '• 대시보드 — (매니저 역할 전용) 하위 에이전트를 모니터링하고 조율합니다.',
          '• 스토리지 — 세션이 생성한 파일과 아티팩트를 탐색합니다.',
          '• 로그 — 디버깅 및 모니터링을 위한 실행 로그를 확인합니다.',
        ],
      },
      {
        title: '🎭 역할',
        body: [
          '• 개발자 — 코드 작성, 검토 및 리팩토링 등 코딩 작업에 최적화되어 있습니다.',
          '• 연구원 — 정보 수집, 분석 및 요약에 특화되어 있습니다.',
          '• 매니저 — 다른 세션을 조율하고 작업을 위임하며 진행 상황을 관리합니다.',
          '• 워커 — 다양한 작업을 위한 범용 실행자입니다.',
          '• 셀프 매니저 — 자체 워크플로우를 계획하고 관리하는 자율 에이전트입니다.',
        ],
      },
      {
        title: '🏙️ 3D 플레이그라운드',
        body: [
          '플레이그라운드 탭은 복셀 스타일 에셋으로 구성된 미니어처 도시를 렌더링합니다. 각 활성 세션은 A* 경로 탐색을 사용하여 도시를 돌아다니는 애니메이션 캐릭터로 표시됩니다.',
          '조작: 좌클릭 드래그로 패닝, 우클릭 드래그로 회전, 스크롤로 축소/확대합니다.',
        ],
      },
      {
        title: '🔌 MCP 및 커스텀 도구',
        body: [
          'Geny는 MCP(Model Context Protocol) 서버와 커스텀 도구를 지원합니다. 백엔드에 배치된 MCP 서버 설정은 모든 세션에서 자동으로 로드됩니다.',
          'tools 디렉토리에 배치된 커스텀 Python 도구는 자동으로 등록되어 모든 에이전트에서 사용할 수 있습니다.',
        ],
      },
    ],
    tipTitle: '💡 팁',
    tips: [
      '여러 세션을 병렬로 실행할 수 있습니다 — 각 에이전트는 독립적으로 작동합니다.',
      '매니저 역할을 사용하여 다른 세션에 작업을 배분하고 조율할 수 있습니다.',
      '사이드바에서 실행 중인 세션은 녹색 점으로 실시간 상태를 표시합니다.',
      '사이드바에서 세션을 클릭하면 즉시 해당 세션으로 전환됩니다.',
      '삭제된 세션은 사이드바 하단의 휴지통 섹션에서 복원할 수 있습니다.',
    ],
    footerNote: 'Geny는 활발히 개발 중입니다. 기능과 UI가 변경될 수 있습니다. 질문이나 문제가 있으면 프로젝트 저장소를 참조하세요.',
  },

  // ─── Command Tab ───
  commandTab: {
    selectSession: '세션을 선택하세요',
    selectSessionDesc: '명령을 실행할 세션을 목록에서 선택하세요',
    sessionFallback: '세션 {id}',
    single: '그래프',
    model: '모델',
    maxTurns: '최대 턴',
    placeholder: '명령 또는 프롬프트를 입력하세요...',
    skipPermissions: '권한 확인 건너뛰기',
    executingBtn: '⏳ 실행 중...',
    executeBtn: '▶ 실행',
    stopBtn: '⏹ 중지',
    output: '출력',
    statusExecuting: '실행 중...',
    statusComplete: '완료',
    iterations: '회 반복',
    statusFailed: '실패',
    requestFailed: '요청 실패',
    statusStopped: '중지됨',
    statusSuccess: '성공',
  },

  // ─── Settings Tab ───
  settings: {
    title: '설정',
    all: '전체',
    noConfigs: '설정을 찾을 수 없습니다',
    fieldsConfigured: '{count}/{total}개 필드 설정됨',
    issues: '{count}개 문제',
    editPrefix: '편집: ',
    resetToDefaults: '기본값으로 초기화',
    resetConfirm: '"{name}"을(를) 기본값으로 초기화하시겠습니까?',
    configSaved: '설정이 저장되었습니다',
    saveFailed: '저장 실패',
    resetSuccess: '기본값으로 초기화되었습니다',
    exported: '내보내기 완료',
    imported: '가져오기 완료',
    importFailed: '가져오기 실패',
    invalidJson: '유효하지 않은 JSON',
    importTitle: '설정 가져오기',
    importPlaceholder: '설정 JSON을 여기에 붙여넣으세요...',
    groupLabels: {
      connection: '연결',
      server: '서버 설정',
      workspace: '워크스페이스',
      teams: 'Teams',
      permissions: '권한',
      behavior: '동작',
      session: '세션 설정',
      commands: '명령',
      graph: 'Microsoft Graph',
      general: '일반',
      language: '언어',
      api: 'API 설정',
      redis: 'Redis',
      limits: '제한',
      telemetry: '텔레메트리',
      github: 'GitHub',
    } as Record<string, string>,
    hide: '숨기기',
    show: '표시',
  },

  // ─── Info Tab ───
  info: {
    selectSession: '세션을 선택하세요',
    selectSessionDesc: '상세 정보를 볼 세션을 선택하세요',
    loading: '로딩 중...',
    sessionDetails: '세션 상세 정보',
    unnamed: '(이름 없음)',
    deleted: '삭제됨',
    unknown: '알 수 없음',
    default: '기본값',
    worker: '워커',
    restoreSession: '세션 복원',
    permanentDelete: '영구 삭제',
    fields: {
      sessionId: '세션 ID',
      name: '이름',
      status: '상태',
      model: '모델',
      role: '역할',
      maxTurns: '최대 턴',
      timeout: '타임아웃',
      maxIterations: '최대 반복',
      storagePath: '스토리지 경로',
      created: '생성일',
      pid: 'PID',
      pod: 'Pod',
      managerId: '매니저 ID',
      deletedAt: '삭제일',
      graphName: '그래프 이름',
      workflowId: '워크플로우 ID',
    },
  },

  // ─── Dashboard Tab ───
  dashboardTab: {
    selectSession: '세션을 선택하세요',
    selectSessionDesc: '대시보드를 볼 세션을 선택하세요',
    managerOnly: '매니저 전용',
    managerOnlyDesc: '대시보드는 매니저 세션에서만 사용할 수 있습니다',
    title: '매니저 대시보드',
    workers: '워커',
    workersCount: '{count}개 워커',
    noWorkers: '할당된 워커 없음',
    working: '작업 중',
    idle: '대기 중',
    timeline: '활동 타임라인',
    noActivity: '아직 활동이 없습니다',
    workerPrefix: '워커: ',
    events: {
      task_delegated: '작업 위임',
      worker_started: '워커 시작',
      worker_completed: '워커 완료',
      worker_error: '워커 오류',
      worker_progress: '진행 상황 업데이트',
      plan_created: '계획 생성',
      plan_updated: '계획 업데이트',
      user_message: '사용자 메시지',
      manager_response: '매니저 응답',
    } as Record<string, string>,
  },

  // ─── Logs Tab ───
  logsTab: {
    selectSession: '세션을 선택하세요',
    selectSessionDesc: '로그를 볼 세션을 목록에서 선택하세요',
    title: '세션 로그',
    allLevels: '전체 레벨',
    autoRefresh: '자동 새로고침',
    refresh: '새로고침',
    noLogs: '로그 항목 없음',
    groupBrief: '간략',
    groupBriefDesc: '핵심 활동만',
    groupDefault: '기본',
    groupDefaultDesc: '도구 호출 & 반복',
    groupDetail: '상세',
    groupDetailDesc: '그래프 실행 흐름',
    groupAll: '전체',
    groupAllDesc: '모든 로그 (디버그 포함)',
  },

  // ─── Storage Tab ───
  storageTab: {
    selectSession: '세션을 선택하세요',
    selectSessionDesc: '스토리지를 볼 세션을 목록에서 선택하세요',
    title: '세션 스토리지',
    refresh: '새로고침',
    empty: '스토리지가 비어 있습니다',
    noFile: '선택된 파일 없음',
    loading: '로딩 중...',
    selectFile: '미리 볼 파일을 선택하세요',
    emptyFile: '(빈 파일)',
    loadError: '파일 로드 오류: {message}',
  },

  // ─── Playground Tab ───
  playground: {
    title: '시티 플레이그라운드',
    citizens: '{count}명의 시민',
    zoomIn: '확대',
    zoomOut: '축소',
    resetView: '뷰 초기화',
    building: '도시 생성 중...',
    emptyCta: '도시에서 시민을 보려면 세션을 생성하세요!',
  },

  // ─── Graph Tab ───
  graphTab: {
    selectSession: '세션을 선택하세요',
    selectSessionDesc: '그래프를 볼 세션을 선택하거나 ',
    workflowsLink: '워크플로우',
    selectSessionSuffix: '에서 그래프 워크플로우를 관리하세요',
    loadingGraph: '그래프 로딩 중...',
    title: '그래프',
    resetBtn: '초기화',
    hasPrompt: '프롬프트 있음',
    description: '설명',
    nodeId: '노드 ID',
    incoming: '들어오는 ({count})',
    outgoing: '나가는 ({count})',
    conditionalRouting: '조건부 라우팅',
    promptTemplate: '프롬프트 템플릿',
    metadata: '메타데이터',
    innerGraph: '내부 그래프',
    path: '{name} 경로',
  },

  // ─── Graph Workflows Tab ───
  workflowsTab: {
    title: '그래프 워크플로우',
    subtitle: '에이전트 세션을 위한 그래프 워크플로우를 관리합니다. 공식 템플릿은 항상 사용 가능하며, 맞춤 워크플로우를 생성하여 전문적인 동작을 구현할 수 있습니다.',
    openEditor: '편집기 열기',
    newWorkflow: '+ 새 워크플로우',
    loadingWorkflows: '워크플로우 로딩 중…',
    officialTemplates: '공식 템플릿',
    customWorkflows: '커스텀 워크플로우',
    noCustom: '아직 커스텀 워크플로우가 없습니다',
    createFirst: '+ 첫 번째 워크플로우 만들기',
    noDescription: '설명 없음',
    official: '공식',
    nodes: '{count}개 노드',
    edges: '{count}개 엣지',
    backToWorkflows: '← 워크플로우로 돌아가기',
    workflowEditor: '워크플로우 편집기',
    viewPrefix: '보기: ',
    readOnly: '읽기 전용',
    newWorkflowTitle: '새 워크플로우',
    nameLabel: '이름',
    namePlaceholder: '내 워크플로우',
    descriptionLabel: '설명',
    descriptionPlaceholder: '선택적 설명…',
  },

  // ─── Workflow Editor ───
  workflowEditor: {
    selectWorkflow: '워크플로우 선택…',
    templateSuffix: '(템플릿)',
    workflowName: '워크플로우 이름',
    new: '＋ 새로 만들기',
    confirm: '확인',
    newWorkflowTooltip: '새 워크플로우',
    loadTemplateTooltip: '템플릿 로드',
    saveTemplate: '📋 템플릿',
    save: '💾 저장',
    saveDirty: '💾 저장*',
    saveTooltip: '워크플로우 저장',
    clone: '📑 복제',
    cloneTooltip: '워크플로우 복제',
    deleteBtn: '🗑 삭제',
    deleteTooltip: '워크플로우 삭제',
    loading: '불러오는 중…',
    nodesEdges: '{nodes}개 노드 · {edges}개 엣지',
    designTitle: '워크플로우를 설계하세요',
    designSubtitle: '팔레트에서 노드를 드래그하거나 템플릿을 로드하여 시작하세요. 핸들에서 드래그하여 노드를 연결하세요.',
  },

  // ─── Node Palette ───
  nodePalette: {
    title: '노드 팔레트',
    search: '노드 검색…',
    noMatch: '일치하는 노드를 찾을 수 없습니다',
    dragTip: '캔버스에 노드를 드래그하여 워크플로우에 추가하세요.',
    loading: '노드 로딩 중…',
    startNode: '시작',
    startDesc: '워크플로우의 진입점',
    endNode: '종료',
    endDesc: '워크플로우의 종료점',
    output: '출력',
    categories: {
      special: '특수',
      model: '모델',
      task: '작업',
      logic: '로직',
      memory: '메모리',
      resilience: '복원력',
    } as Record<string, string>,
  },

  // ─── Property Panel ───
  propertyPanel: {
    title: '속성',
    selectNode: '속성을 편집할 노드를 선택하세요',
    nodeLabel: '노드 레이블',
    nodeId: '노드 ID',
    outputPorts: '출력 포트',
    deleteNode: '노드 삭제',
    promptPlaceholder: '프롬프트 템플릿을 입력하세요…',
    promptHelp: '상태 변수 치환을 위해 {field}를 사용하세요. 사용 가능: input, answer, review_feedback, last_output',
    invalidJson: '유효하지 않은 JSON',
    select: '선택…',
    helpTooltip: '상세 사용 가이드 보기',
  },

  // ─── Create Session Modal ───
  createSession: {
    title: '새 세션 만들기',
    sessionName: '세션 이름',
    sessionNamePlaceholder: '예: my-worker-1',
    role: '역할',
    roleWorker: '워커',
    roleManager: '매니저',
    model: '모델',
    modelDefault: '기본값',
    managerSession: '매니저 세션',
    noneStandalone: '없음 (독립 실행)',
    managerHelp: '이 워커를 제어할 매니저를 선택하세요',
    promptTemplate: '프롬프트 템플릿',
    customNone: '커스텀 / 없음',
    maxTurns: '최대 턴',
    timeout: '타임아웃 (초)',
    graphWorkflow: '그래프 워크플로우',
    officialTemplates: '공식 템플릿',
    customWorkflows: '커스텀 워크플로우',
    customHelp: '커스텀 워크플로우 그래프',
    maxIterations: '최대 반복',
    systemPrompt: '시스템 프롬프트',
    systemPromptPlaceholder: '선택적 시스템 프롬프트...',
    creating: '생성 중...',
    createSession: '세션 생성',
    failedToCreate: '세션 생성에 실패했습니다',
  },

  // ─── Delete Session Modal ───
  deleteSessionModal: {
    title: '세션 삭제',
    confirm: '정말로 삭제하시겠습니까: ',
    softDeleteNote: '세션이 소프트 삭제됩니다. 삭제된 세션 섹션에서 복원할 수 있습니다.',
    deleting: '삭제 중...',
  },

  // ─── Workflow Store (error messages) ───
  workflowStore: {
    deleteConfirm: '워크플로우 "{name}"을(를) 삭제하시겠습니까?',
    cannotSaveTemplate: '템플릿은 저장할 수 없습니다. 먼저 복제하세요.',
    failedSave: '워크플로우 저장 실패',
    untitled: '제목 없는 워크플로우',
    failedCreate: '워크플로우 생성 실패',
    failedLoad: '워크플로우 로드 실패',
    failedLoadSingle: '워크플로우 로드 실패',
    failedClone: '워크플로우 복제 실패',
    failedCatalog: '노드 카탈로그 로드 실패',
  },

  // ─── Accessibility ───
  a11y: {
    decrease: '감소',
    increase: '증가',
  },
};

export default ko;
