/**
 * stage_locale — Korean translation layer for the catalog
 * introspection strings that geny-executor returns (slot descriptions,
 * impl descriptions, chain descriptions, config field titles +
 * descriptions).
 *
 * Why this exists:
 *   geny-executor surfaces SlotIntrospection / ChainIntrospection /
 *   config_schema fields as English strings. The Geny frontend wants
 *   to render those in Korean for KO-locale users without touching
 *   the executor (which is shared across multiple consumers).
 *
 * Approach:
 *   `localizeIntrospection(intro, locale)` takes the English intro
 *   straight from `catalogApi.stage(order)` and returns a deep-cloned
 *   copy with all human-facing strings swapped to KO when the locale
 *   is 'ko'. EN locale is a no-op (passthrough).
 *
 * Maintenance:
 *   The KO map covers every slot / impl / chain / config field
 *   geny-executor 1.x ships. New executor releases that add new keys
 *   should add entries here in the same PR — missing keys fall
 *   through to the original English string (graceful degradation,
 *   not a crash).
 */

import type { Locale } from '@/lib/i18n';
import type {
  ChainIntrospection,
  SlotIntrospection,
  StageIntrospection,
} from '@/types/environment';

interface SlotLocaleEntry {
  description?: string;
  impls?: Record<string, string>;
}

interface ChainLocaleEntry {
  description?: string;
  impls?: Record<string, string>;
}

interface ConfigFieldLocaleEntry {
  title?: string;
  description?: string;
}

interface StageLocaleEntry {
  slots?: Record<string, SlotLocaleEntry>;
  chains?: Record<string, ChainLocaleEntry>;
  configFields?: Record<string, ConfigFieldLocaleEntry>;
}

// ───────────────────────────────────────────────────────────
// Korean translations per stage
// ───────────────────────────────────────────────────────────

const STAGE_KO: Record<number, StageLocaleEntry> = {
  1: {
    slots: {
      validator: {
        description: '원시 입력 검증 전략',
        impls: {
          default: '표준 길이/타입 검증',
          passthrough: '검증 없음, 모든 입력 수용',
          schema: 'JSON 스키마 기반 검증',
          strict: '패턴 차단 포함 엄격한 검증',
        },
      },
      normalizer: {
        description: '입력 정규화 전략',
        impls: {
          default: '표준 trim + 유니코드 정규화 (멀티모달 인식)',
          multimodal: '텍스트, 이미지, 파일 첨부 처리',
        },
      },
    },
  },

  2: {
    slots: {
      strategy: {
        description: '컨텍스트 수집 전략',
        impls: {
          hybrid: '최근 20턴 + 메모리 주입',
          progressive_disclosure: '요약으로 시작, 관련 부분만 확장',
          simple_load: '기존 메시지 그대로 사용',
        },
      },
      compactor: {
        description: '히스토리 압축 전략',
        impls: {
          sliding_window: '30개 메시지 고정 윈도우',
          summary: '오래된 메시지를 요약으로 교체',
          truncate: '최근 20개 메시지 유지, 나머지 제거',
        },
      },
      retriever: {
        description: '메모리 검색 전략',
        impls: {
          null: '메모리 검색 없음',
          static: '고정 메모리 청크 반환',
        },
      },
    },
    configFields: {
      stateless: {
        title: 'Stateless',
        description: '컨텍스트 조립 우회 (대화 히스토리 없음).',
      },
    },
  },

  3: {
    slots: {
      builder: {
        description: '시스템 프롬프트 빌더 전략',
        impls: {
          static: '고정 시스템 프롬프트',
          composable: '조합형 블록',
          dynamic_persona: '호스트 제공자에서 동적 페르소나 해석',
        },
      },
    },
    configFields: {
      prompt: {
        title: '시스템 프롬프트',
        description: '대화 전에 주입되는 정적 시스템 프롬프트.',
      },
      template_vars: {
        title: '템플릿 변수',
        description: '조합형 프롬프트 빌더가 사용 가능한 키-값 쌍.',
      },
    },
  },

  4: {
    chains: {
      guards: {
        description: '사전 점검 가드 체인 (순서 있음)',
        impls: {
          cost_budget: '세션 예산을 초과하지 않도록 보장',
          iteration: '무한 루프 방지',
          permission: '도구 실행 권한 검증',
          token_budget: '최소 10000 토큰 잔량 확보',
        },
      },
    },
    configFields: {
      max_chain_length: {
        title: '최대 체인 길이',
        description: '이 수치를 초과하는 가드 구성을 거부합니다.',
      },
      fail_fast: {
        title: 'Fail Fast',
        description: '모든 실패를 모으는 대신 첫 실패에서 중단.',
      },
    },
  },

  5: {
    slots: {
      strategy: {
        description: '프롬프트 캐싱 전략',
        impls: {
          aggressive_cache: '시스템 + 도구 + 안정된 히스토리 캐시',
          no_cache: '프롬프트 캐싱 없음',
          system_cache: '시스템 프롬프트만 캐시',
        },
      },
    },
    configFields: {
      cache_prefix: {
        title: '캐시 접두사',
        description: '네임스페이스 격리를 위해 캐시 키에 붙는 접두사.',
      },
    },
  },

  6: {
    slots: {
      provider: {
        description: 'API 제공자 (legacy 슬롯 — 실행은 state.llm_client 로 라우팅)',
        impls: {
          anthropic: '공식 SDK 통한 Anthropic Messages API',
          mock: '테스트용 mock 제공자',
        },
      },
      retry: {
        description: 'API 오류 시 재시도 전략',
        impls: {
          exponential_backoff: '지수 백오프 (최대 3회)',
          no_retry: '재시도 없음, 즉시 실패',
          rate_limit_aware: 'rate limit retry-after 헤더 준수',
        },
      },
      router: {
        description: '호출별 적응형 모델 선택 (passthrough = override 없음)',
        impls: {
          adaptive: '복잡도 기반 적응형 모델 선택',
          passthrough: '라우팅 override 없음 — 요청된 모델 그대로 사용',
        },
      },
    },
    configFields: {
      provider: {
        title: '제공자',
        description: '이 단계에서 사용할 LLM 제공자.',
      },
      base_url: {
        title: '기본 URL',
        description: 'API 엔드포인트 override (vLLM / 프록시 / mock 서버).',
      },
      stream: {
        title: '스트림',
        description: '지원되는 경우 SSE 스트리밍 사용.',
      },
      timeout_ms: {
        title: '타임아웃 (ms)',
        description: '요청당 타임아웃 (밀리초). 비워두면 제공자 기본값.',
      },
    },
  },

  7: {
    slots: {
      tracker: {
        description: '토큰 사용량 추적 전략',
        impls: {
          default: 'API 응답의 usage 필드에서 토큰 추적',
          detailed: '턴별, 단계별 상세 토큰 추적',
        },
      },
      calculator: {
        description: '비용 계산 전략',
        impls: {
          anthropic_pricing: 'Anthropic 공식 가격 계산기',
          custom_pricing: '커스텀 균일 가격',
          unified_pricing: '다중 제공자 가격 (Anthropic + OpenAI + Google)',
        },
      },
    },
  },

  8: {
    slots: {
      processor: {
        description: '사고 (thinking) 블록 처리 전략',
        impls: {
          extract_and_store: '사고 내용 추출 후 state.thinking_history 에 저장',
          filter: '패턴으로 사고 블록 필터링 — 예: 민감한 추론 제거',
          passthrough: '사고 블록을 그대로 보존 (분리만)',
        },
      },
      budget_planner: {
        description:
          '턴당 thinking_budget_tokens 플래너 — API 호출 전 apply_planned_budget(state) 로 호출',
        impls: {
          static: '항상 단일 고정 예산 반환 — 현재 동작',
          adaptive: '메시지 크기 + 도구 존재 여부에서 휴리스틱 예산 계산',
        },
      },
    },
  },

  9: {
    slots: {
      parser: {
        description: '응답 파싱 전략',
        impls: {
          default: '표준 텍스트/도구/사고 추출',
          structured_output: 'JSON 구조화 출력 파서 (스키마 없음)',
        },
      },
      signal_detector: {
        description: '완료 신호 감지 전략',
        impls: {
          regex: 'Regex 기반 [SIGNAL: detail] 패턴 매칭',
          hybrid: 'Regex + JSON 하이브리드 감지',
          structured: 'JSON 기반 구조화 신호 감지',
        },
      },
    },
  },

  10: {
    slots: {
      executor: {
        description: '도구 실행 전략',
        impls: {
          sequential: '순차 실행',
          parallel: '병렬 실행 (최대 5개)',
          partition:
            'concurrency_safe 능력 기준 도구 호출 분할 (최대 병렬: 10개)',
        },
      },
      router: {
        description: '도구 디스패치 전략',
        impls: {
          registry: 'ToolRegistry 조회로 라우팅',
        },
      },
    },
    configFields: {
      max_concurrency: {
        title: '최대 동시성',
        description:
          '병렬 실행 가능한 도구 호출 최대 수. ParallelExecutor / PartitionExecutor / StreamingToolExecutor 에 적용. SequentialExecutor 는 무시합니다.',
      },
    },
  },

  11: {
    chains: {
      reviewers: {
        description: '도구 호출 리뷰어 체인 (순서 있음)',
        impls: {
          schema: '입력에 필수 필드가 빠진 도구 호출에 플래그',
          sensitive: '시크릿 같은 입력에 플래그',
          destructive: '상태를 변경하는 도구의 결과에 플래그',
          network: '네트워크 egress 가 있는 도구 호출 감사',
          size: '직렬화 크기가 한도를 초과한 도구 결과에 플래그',
        },
      },
    },
  },

  12: {
    slots: {
      orchestrator: {
        description: '에이전트 오케스트레이션 전략',
        impls: {
          single_agent: '위임 없이 단일 에이전트 실행',
          delegate: '필요 시 서브 에이전트로 위임',
          evaluator: '언제 어느 에이전트로 위임할지 평가',
          subagent_type: '위임마다 서브 에이전트 타입 선택',
        },
      },
    },
    configFields: {
      max_delegations: {
        title: '최대 위임 수',
        description: '턴당 최대 서브 에이전트 위임 수.',
      },
    },
  },

  13: {
    slots: {
      registry: {
        description: 'TaskRecord 인스턴스의 백엔드 저장소',
        impls: {
          in_memory: '인메모리 태스크 레지스트리 (프로세스 수명)',
        },
      },
      policy: {
        description: '새로 드레인된 태스크 처리 정책',
        impls: {
          fire_and_forget: '태스크 등록 후 즉시 반환',
          eager_wait: '새 태스크를 동기적으로 완료까지 실행',
          timed_wait: '제한 대기: eager 이지만 timeout_seconds 로 상한',
        },
      },
    },
  },

  14: {
    slots: {
      strategy: {
        description: '평가 전략',
        impls: {
          signal_based: '파싱된 신호 기반 완료 평가',
          agent_evaluation: 'Stage 11 의 evaluator 에이전트 결과 사용',
          binary_classify: '첫 턴에 easy/not_easy 자동 분류, 이후 신호 기반',
          criteria_based: '사용자 제공 성공 기준 평가',
          evaluation_chain: '순차 체인: (비어 있음)',
        },
      },
      scorer: {
        description: '품질 채점 전략',
        impls: {
          no_scorer: '품질 채점 없음 — 완료 결정만',
          weighted: '여러 품질 차원의 가중 채점',
        },
      },
    },
  },

  15: {
    slots: {
      requester: {
        description: 'HITL 요청을 결정으로 변환',
        impls: {
          null: '항상 승인 — 사람 개입 없음',
          callback: '호스트 제공 async callable 로 위임',
          pipeline_resume: 'HITL gate 승인 후 파이프라인 재개',
        },
      },
      timeout: {
        description: 'requester 타임아웃 시 적용할 결정',
        impls: {
          indefinite: 'requester 가 반환할 때까지 무한 대기',
          auto_approve: 'timeout_seconds 후 자동 승인',
          auto_reject: 'timeout_seconds 후 자동 거부',
        },
      },
    },
  },

  16: {
    slots: {
      controller: {
        description: '루프 결정 전략',
        impls: {
          standard: '표준 루프: tool_use 는 계속, signal 이 결정',
          budget_aware: '예산 한도 접근 시 중단',
          single_turn: '한 턴 후 항상 완료 (루프 없음)',
          multi_dim_budget: '다차원 예산 (등록된 차원 없음)',
        },
      },
    },
    configFields: {
      max_turns: {
        title: '최대 턴',
        description: '루프 반복의 hard cap. 비워두면 state.max_iterations 따름.',
      },
      early_stop_on: {
        title: '조기 중단 신호',
        description: '루프를 즉시 중단해야 하는 완료 신호 목록.',
      },
    },
  },

  17: {
    chains: {
      emitters: {
        description: '출력 emitter 체인 (순서 있음)',
        impls: {
          text: '콜백을 통한 최종 텍스트 출력',
          callback: '호스트 제공 콜백 함수로 emit',
          tts: '음성 합성 (TTS) 출력',
          vtuber: 'VTuber 아바타 애니메이션 + 음성',
        },
      },
    },
  },

  18: {
    slots: {
      strategy: {
        description: '메모리 갱신 전략',
        impls: {
          append_only: '대화를 히스토리에 추가만',
          no_memory: '메모리 갱신 없음 (stateless)',
          reflective: '대화에서 핵심 정보 추출 후 저장',
          structured_reflective:
            '큐된 InsightRecord 검증 후 state.metadata 에 추가',
        },
      },
      persistence: {
        description: '대화 영속화 백엔드',
        impls: {
          null: 'no-op persistence (메모리 영속화 비활성 시 기본)',
          in_memory: '인메모리 대화 저장',
          file: '파일 기반 대화 영속화',
        },
      },
    },
    configFields: {
      stateless: {
        title: 'Stateless',
        description: '영속화 + 메모리 갱신 건너뜀 (일회성 세션).',
      },
      persistence_path: {
        title: '영속화 경로',
        description: 'FilePersistence 가 사용하는 디렉토리.',
      },
    },
  },

  19: {
    slots: {
      summarizer: {
        description: '이번 턴의 SummaryRecord 를 생산',
        impls: {
          no_summary: '이번 턴 요약 건너뜀',
          rule_based: '문장 분할 + 대문자 토큰 추출',
        },
      },
      importance: {
        description: '생산된 레코드에 Importance 등급 부여',
        impls: {
          fixed: '항상 단일 고정 importance 등급',
          heuristic: '키워드 + 크기 휴리스틱으로 importance 결정',
        },
      },
    },
  },

  20: {
    slots: {
      persister: {
        description: '체크포인트 쓰기 백엔드',
        impls: {
          no_persist: 'no-op persister',
          file: '파일 기반 체크포인트 영속화',
        },
      },
      frequency: {
        description: '체크포인트 쓰기 빈도 정책',
        impls: {
          every_turn: '매 턴마다 체크포인트 작성',
          every_n_turns: 'N 회 반복마다 체크포인트 작성',
          on_significant: '이번 턴에 significant signal 이 발생했을 때 체크포인트 작성',
        },
      },
    },
  },

  21: {
    slots: {
      formatter: {
        description: '최종 결과 포맷팅 전략',
        impls: {
          default: '텍스트 출력을 그대로 전달',
          structured: '결과를 메타데이터 포함 구조화 dict 로 패키징',
          multi_format: '텍스트 + 구조화 + 마크다운 형식 동시 emit',
          streaming: '스트리밍 완료 요약 emit',
        },
      },
    },
  },
};

// ───────────────────────────────────────────────────────────
// Localizer
// ───────────────────────────────────────────────────────────

function localizeSlot(
  slot: SlotIntrospection,
  loc: SlotLocaleEntry | undefined,
): SlotIntrospection {
  if (!loc) return slot;
  const next: SlotIntrospection = {
    ...slot,
    description: loc.description ?? slot.description,
  };
  if (loc.impls && slot.impl_descriptions) {
    next.impl_descriptions = { ...slot.impl_descriptions };
    for (const [impl, ko] of Object.entries(loc.impls)) {
      if (impl in next.impl_descriptions) {
        next.impl_descriptions[impl] = ko;
      } else {
        // KO available even if executor build doesn't ship that impl;
        // still register so the dropdown legacy entry would localize.
        next.impl_descriptions[impl] = ko;
      }
    }
  }
  return next;
}

function localizeChain(
  chain: ChainIntrospection,
  loc: ChainLocaleEntry | undefined,
): ChainIntrospection {
  if (!loc) return chain;
  const next: ChainIntrospection = {
    ...chain,
    description: loc.description ?? chain.description,
  };
  if (loc.impls && chain.impl_descriptions) {
    next.impl_descriptions = { ...chain.impl_descriptions };
    for (const [impl, ko] of Object.entries(loc.impls)) {
      next.impl_descriptions[impl] = ko;
    }
  }
  return next;
}

function localizeConfigSchema(
  schema: Record<string, unknown> | null | undefined,
  fields: Record<string, ConfigFieldLocaleEntry> | undefined,
): Record<string, unknown> | null | undefined {
  if (!schema || !fields) return schema;
  const cloned = JSON.parse(JSON.stringify(schema)) as Record<string, unknown>;
  const props = (cloned.properties ?? {}) as Record<string, Record<string, unknown>>;
  for (const [key, locale] of Object.entries(fields)) {
    const prop = props[key];
    if (!prop) continue;
    if (locale.title !== undefined) prop.title = locale.title;
    if (locale.description !== undefined) prop.description = locale.description;
  }
  cloned.properties = props;
  return cloned;
}

/**
 * Run a StageIntrospection through the locale layer. EN locale and
 * stages without a translation entry pass through unchanged.
 */
export function localizeIntrospection(
  intro: StageIntrospection,
  locale: Locale,
): StageIntrospection {
  if (locale !== 'ko') return intro;
  const entry = STAGE_KO[intro.order];
  if (!entry) return intro;

  const next: StageIntrospection = { ...intro };

  if (entry.slots) {
    next.strategy_slots = { ...intro.strategy_slots };
    for (const [slotKey, slot] of Object.entries(intro.strategy_slots)) {
      next.strategy_slots[slotKey] = localizeSlot(slot, entry.slots[slotKey]);
    }
  }

  if (entry.chains) {
    next.strategy_chains = { ...intro.strategy_chains };
    for (const [chainKey, chain] of Object.entries(intro.strategy_chains)) {
      next.strategy_chains[chainKey] = localizeChain(
        chain,
        entry.chains[chainKey],
      );
    }
  }

  if (entry.configFields) {
    next.config_schema = localizeConfigSchema(
      intro.config_schema,
      entry.configFields,
    );
  }

  return next;
}
