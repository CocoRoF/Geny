'use client';

import { useState } from 'react';
import Image from 'next/image';

type Lang = 'en' | 'ko';

const content: Record<Lang, {
  langLabel: string;
  heroTitle: string;
  heroSubtitle: string;
  heroTagline: string;
  sections: { title: string; body: string | string[] }[];
  tipTitle: string;
  tips: string[];
  footerNote: string;
}> = {
  en: {
    langLabel: 'Language',
    heroTitle: 'Welcome to Geny',
    heroSubtitle: 'Geny Execute, Not You',
    heroTagline:
      'An autonomous multi-agent system that manages multiple AI sessions, orchestrates complex tasks, and visualizes everything in an interactive 3D city playground.',
    sections: [
      {
        title: '🚀 Getting Started',
        body: [
          '1. Create a Session — Click the "+ New Session" button in the sidebar to create a new agent session. Choose a role (Developer, Researcher, Manager, or Worker) and give it a name.',
          '2. Send a Command — Switch to the Command tab and type your instruction. The agent will autonomously handle the task.',
          '3. Watch it Work — Open the Playground tab to see your agents come alive as characters wandering a 3D miniature city!',
        ],
      },
      {
        title: '📂 Understanding Sessions',
        body: [
          'Each session is an independent AI agent with its own memory and workspace. You can run multiple sessions at the same time — each one works on its own task without interfering with the others.',
          'Sessions can be paused, resumed, or deleted at any time from the sidebar. Deleted sessions go to the trash and can be restored if needed.',
        ],
      },
      {
        title: '🧭 Navigating the Tabs',
        body: [
          '• Main — You are here! This is the home page with a guide on how to use Geny.',
          '• Playground — A 3D city visualization where your active agents appear as animated characters. Pan, rotate, and zoom to explore.',
          '• Settings — Configure runtime settings, channel integrations, and advanced options.',
          '• Info — View detailed information about the selected session.',
          '• Graph — Visualize the agent\'s LangGraph execution flow in real time.',
          '• Command — The primary interface to send instructions to your agent and see results.',
          '• Dashboard — (Manager role only) Monitor and coordinate subordinate agents.',
          '• Storage — Browse files and artifacts produced by the session.',
          '• Logs — View raw execution logs for debugging and monitoring.',
        ],
      },
      {
        title: '🎭 Roles',
        body: [
          '• Developer — Optimized for coding tasks: writing, reviewing, and refactoring code.',
          '• Researcher — Focused on information gathering, analysis, and summarization.',
          '• Manager — Coordinates other sessions, delegates tasks, and oversees progress.',
          '• Worker — A general-purpose executor for miscellaneous tasks.',
          '• Self-Manager — Autonomous agent that plans and manages its own workflow.',
        ],
      },
      {
        title: '🏙️ The 3D Playground',
        body: [
          'The Playground tab renders a miniature city built from voxel-style assets. Each active session shows up as an animated character that wanders around the city using A* pathfinding.',
          'Controls: Left-click drag to pan, right-click drag to rotate, scroll to zoom in/out.',
        ],
      },
      {
        title: '🔌 MCP & Custom Tools',
        body: [
          'Geny supports MCP (Model Context Protocol) servers and custom tools. MCP server configurations placed in the backend are automatically loaded for all sessions.',
          'Custom Python tools placed in the tools directory are auto-registered and available to every agent.',
        ],
      },
    ],
    tipTitle: '💡 Tips',
    tips: [
      'You can run multiple sessions in parallel — each agent works independently.',
      'Use the Manager role to orchestrate and delegate tasks across other sessions.',
      'The sidebar shows real-time session status with a green dot for running sessions.',
      'Click on any session in the sidebar to instantly switch to it.',
      'Deleted sessions can be restored from the trash section at the bottom of the sidebar.',
    ],
    footerNote:
      'Geny is under active development. Features and UI may change. For questions or issues, please refer to the project repository.',
  },
  ko: {
    langLabel: '언어',
    heroTitle: 'Geny에 오신 것을 환영합니다',
    heroSubtitle: 'Geny Execute, Not You (지니가 할게, 넌 가만히 있어)',
    heroTagline:
      '여러 AI 세션을 관리하고, 복잡한 작업을 조율하며, 인터랙티브한 3D 시티 플레이그라운드에서 모든 것을 시각화하는 자율 멀티 에이전트 시스템.',
    sections: [
      {
        title: '🚀 시작하기',
        body: [
          '1. 세션 생성 — 사이드바의 "+ New Session" 버튼을 클릭하여 새 에이전트 세션을 생성하세요. 역할(Developer, Researcher, Manager, Worker)을 선택하고 이름을 지정합니다.',
          '2. 명령 보내기 — Command 탭으로 전환한 후 지시사항을 입력하세요. 에이전트가 자율적으로 작업을 처리합니다.',
          '3. 작업 관찰 — Playground 탭을 열어 에이전트들이 3D 미니어처 도시를 돌아다니는 캐릭터로 활동하는 모습을 확인하세요!',
        ],
      },
      {
        title: '📂 세션 이해하기',
        body: [
          '각 세션은 고유한 메모리와 작업 공간을 갖는 독립적인 AI 에이전트입니다. 여러 세션을 동시에 실행할 수 있으며, 각 세션은 서로 간섭 없이 독립적으로 작업합니다.',
          '세션은 사이드바에서 언제든 일시 중지, 재개, 삭제할 수 있습니다. 삭제된 세션은 휴지통으로 이동하며 필요 시 복원할 수 있습니다.',
        ],
      },
      {
        title: '🧭 탭 안내',
        body: [
          '• Main — 지금 이 페이지입니다! Geny 사용법을 안내하는 홈 페이지입니다.',
          '• Playground — 활성 에이전트가 애니메이션 캐릭터로 등장하는 3D 도시 시각화입니다. 패닝, 회전, 줌으로 탐색하세요.',
          '• Settings — 런타임 설정, 채널 연동, 고급 옵션을 설정할 수 있습니다.',
          '• Info — 선택한 세션의 상세 정보를 확인합니다.',
          '• Graph — 에이전트의 LangGraph 실행 흐름을 실시간으로 시각화합니다.',
          '• Command — 에이전트에게 지시를 보내고 결과를 확인하는 기본 인터페이스입니다.',
          '• Dashboard — (Manager 역할 전용) 하위 에이전트를 모니터링하고 조율합니다.',
          '• Storage — 세션에서 생성된 파일 및 아티팩트를 탐색합니다.',
          '• Logs — 디버깅 및 모니터링을 위한 실행 로그를 확인합니다.',
        ],
      },
      {
        title: '🎭 역할',
        body: [
          '• Developer — 코드 작성, 리뷰, 리팩토링 등 코딩 작업에 최적화되어 있습니다.',
          '• Researcher — 정보 수집, 분석, 요약에 집중합니다.',
          '• Manager — 다른 세션을 조율하고, 작업을 위임하며, 진행 상황을 감독합니다.',
          '• Worker — 다양한 작업을 수행하는 범용 에이전트입니다.',
          '• Self-Manager — 스스로 워크플로우를 계획하고 관리하는 자율 에이전트입니다.',
        ],
      },
      {
        title: '🏙️ 3D 플레이그라운드',
        body: [
          'Playground 탭은 복셀 스타일 자산으로 구축된 미니어처 도시를 렌더링합니다. 각 활성 세션은 A* 길찾기 알고리즘을 사용하여 도시를 돌아다니는 애니메이션 캐릭터로 표시됩니다.',
          '조작: 왼쪽 클릭 드래그로 패닝, 오른쪽 클릭 드래그로 회전, 스크롤로 확대/축소합니다.',
        ],
      },
      {
        title: '🔌 MCP & 커스텀 도구',
        body: [
          'Geny는 MCP(Model Context Protocol) 서버와 커스텀 도구를 지원합니다. 백엔드에 배치된 MCP 서버 설정은 모든 세션에서 자동으로 로드됩니다.',
          'tools 디렉토리에 배치된 커스텀 Python 도구는 자동으로 등록되어 모든 에이전트에서 사용할 수 있습니다.',
        ],
      },
    ],
    tipTitle: '💡 팁',
    tips: [
      '여러 세션을 병렬로 실행할 수 있습니다 — 각 에이전트는 독립적으로 작업합니다.',
      'Manager 역할을 사용하여 다른 세션들의 작업을 조율하고 위임하세요.',
      '사이드바에서 실행 중인 세션은 초록색 점으로 실시간 상태를 표시합니다.',
      '사이드바의 세션을 클릭하면 즉시 해당 세션으로 전환됩니다.',
      '삭제된 세션은 사이드바 하단의 휴지통에서 복원할 수 있습니다.',
    ],
    footerNote:
      'Geny는 활발히 개발 중입니다. 기능 및 UI가 변경될 수 있습니다. 질문이나 문제가 있으면 프로젝트 리포지토리를 참고해 주세요.',
  },
};

export default function MainTab() {
  const [lang, setLang] = useState<Lang>('en');
  const t = content[lang];

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-[1000px] mx-auto px-6 py-8">
        {/* ── Language Toggle ── */}
        <div className="flex justify-end mb-6">
          <div className="inline-flex items-center gap-1 p-0.5 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border-color)]">
            <button
              onClick={() => setLang('en')}
              className={`px-3 py-1 text-xs font-medium rounded-md transition-all duration-150 border-none cursor-pointer ${
                lang === 'en'
                  ? 'bg-[var(--primary-color)] text-white shadow-sm'
                  : 'bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              ENG
            </button>
            <button
              onClick={() => setLang('ko')}
              className={`px-3 py-1 text-xs font-medium rounded-md transition-all duration-150 border-none cursor-pointer ${
                lang === 'ko'
                  ? 'bg-[var(--primary-color)] text-white shadow-sm'
                  : 'bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              KOR
            </button>
          </div>
        </div>

        {/* ── Logo ── */}
        <div className="flex justify-center mb-8">
          <Image
            src="/geny_full_logo_middle.png"
            alt="Geny Logo"
            width={420}
            height={160}
            priority
            className="object-contain"
          />
        </div>

        {/* ── Hero ── */}
        <div className="text-center mb-10">
          <h1 className="text-2xl font-bold text-[var(--text-primary)] mb-2">{t.heroTitle}</h1>
          <p className="text-base italic text-[var(--primary-color)] mb-3">{t.heroSubtitle}</p>
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed max-w-[640px] mx-auto">
            {t.heroTagline}
          </p>
        </div>

        {/* ── Sections ── */}
        <div className="flex flex-col gap-6">
          {t.sections.map((section, i) => (
            <section
              key={i}
              className="rounded-xl border border-[var(--border-color)] bg-[var(--bg-secondary)] p-5"
            >
              <h2 className="text-base font-semibold text-[var(--text-primary)] mb-3">
                {section.title}
              </h2>
              <div className="flex flex-col gap-2">
                {(Array.isArray(section.body) ? section.body : [section.body]).map((line, j) => (
                  <p key={j} className="text-[0.8125rem] text-[var(--text-secondary)] leading-[1.7]">
                    {line}
                  </p>
                ))}
              </div>
            </section>
          ))}

          {/* ── Tips ── */}
          <section className="rounded-xl border border-[rgba(59,130,246,0.2)] bg-[rgba(59,130,246,0.04)] p-5">
            <h2 className="text-base font-semibold text-[var(--primary-color)] mb-3">
              {t.tipTitle}
            </h2>
            <ul className="flex flex-col gap-1.5 list-none p-0 m-0">
              {t.tips.map((tip, i) => (
                <li
                  key={i}
                  className="text-[0.8125rem] text-[var(--text-secondary)] leading-[1.7] pl-4 relative before:content-['▸'] before:absolute before:left-0 before:text-[var(--primary-color)]"
                >
                  {tip}
                </li>
              ))}
            </ul>
          </section>
        </div>

        {/* ── Footer ── */}
        <p className="text-center text-xs text-[var(--text-muted)] mt-10 mb-4">
          {t.footerNote}
        </p>
      </div>
    </div>
  );
}
