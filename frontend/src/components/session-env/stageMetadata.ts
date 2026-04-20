/**
 * Stage metadata for the 16-stage pipeline.
 *
 * Ported from geny-executor-web's
 *   - src/utils/stageMetadata.ts (EN)
 *   - src/locales/ko.ts         (KO)
 *
 * Kept self-contained to the Geny frontend so we don't introduce
 * a runtime dependency on the executor-web package. The shape is
 * intentionally identical so a future shared package is trivial.
 */
import type { Locale } from '@/lib/i18n';

export type StagePhase = 'A' | 'B' | 'C';
export type StageCategory = 'ingress' | 'pre_flight' | 'execution' | 'decision' | 'egress';

export interface StrategySlotMeta {
  slot: string;
  options: { name: string; description: string }[];
}

export interface StageMetaBase {
  order: number;
  name: string;
  phase: StagePhase;
  category: StageCategory;
  canBypass: boolean;
}

export interface StageMetaLocalized extends StageMetaBase {
  displayName: string;
  categoryLabel: string;
  description: string;
  detailedDescription: string;
  technicalBehavior: string[];
  strategies: StrategySlotMeta[];
  architectureNotes: string;
  bypassCondition?: string;
}

/* ═══ English source of truth ═══════════════════════════ */
const STAGES_EN: StageMetaLocalized[] = [
  {
    order: 1,
    name: 'input',
    phase: 'A',
    category: 'ingress',
    canBypass: false,
    displayName: 'Input',
    categoryLabel: 'Ingress',
    description: 'Validate and normalize user input',
    detailedDescription:
      'The entry point of the entire pipeline. Receives raw user input of any type — text, multimodal content, or structured data — validates it against schema constraints, and normalizes it into a standardized NormalizedInput format. The normalized message is added to the conversation history in Anthropic API format, with session tracking metadata attached.',
    technicalBehavior: [
      'Receives raw input of any type (text, multimodal, structured)',
      'Runs validation against configured validator strategy',
      'Transforms input to NormalizedInput with normalized text',
      'Adds user message to state.messages in Anthropic API format',
      'Attaches session_id to the normalized input',
      "Emits 'input.normalized' event with text length",
    ],
    strategies: [
      {
        slot: 'Validator',
        options: [
          { name: 'DefaultValidator', description: 'Accepts most inputs with basic type checking' },
          { name: 'PassthroughValidator', description: 'No validation — accept everything' },
          { name: 'StrictValidator', description: 'Enforces rigid schema constraints' },
          { name: 'SchemaValidator', description: 'Custom JSON schema validation' },
        ],
      },
      {
        slot: 'Normalizer',
        options: [
          { name: 'DefaultNormalizer', description: 'Text-only normalization' },
          { name: 'MultimodalNormalizer', description: 'Handles images, audio, and mixed content' },
        ],
      },
    ],
    architectureNotes:
      'Input is the only stage in Phase A. It runs once per pipeline invocation and cannot be bypassed. All downstream stages depend on the NormalizedInput it produces.',
  },
  {
    order: 2,
    name: 'context',
    phase: 'B',
    category: 'ingress',
    canBypass: true,
    bypassCondition: 'stateless=True (single-turn agents with no history)',
    displayName: 'Context',
    categoryLabel: 'Ingress',
    description: 'Load conversation history and memory',
    detailedDescription:
      'Collects and assembles context for the current API call. Loads conversation history already in state, retrieves relevant memory chunks from external stores (vector DB, file system), and monitors context size against budget. When context exceeds 80% of the context window budget, triggers automatic compaction — removing or summarizing older messages to stay within limits.',
    technicalBehavior: [
      'Extracts query from last user message (supports multimodal extraction)',
      'Calls retriever strategy to fetch relevant memory chunks',
      'Deduplicates memory references by key',
      'Estimates token count (4 chars ≈ 1 token heuristic)',
      'Triggers compaction if estimated_tokens > context_window_budget × 0.8',
      "Updates state.memory_refs and state.metadata['memory_context']",
      "Emits 'context.built' and optionally 'context.compacted' events",
    ],
    strategies: [
      {
        slot: 'Context Strategy',
        options: [
          { name: 'SimpleLoadStrategy', description: 'Uses messages already in state — no external retrieval' },
          { name: 'HybridStrategy', description: 'Keeps last N recent turns + injects relevant memory' },
          { name: 'ProgressiveDisclosureStrategy', description: 'Start with summaries, expand details on demand' },
        ],
      },
      {
        slot: 'Compactor',
        options: [
          { name: 'TruncateCompactor', description: 'Remove oldest messages when over budget' },
          { name: 'SummaryCompactor', description: 'Replace old messages with AI-generated summaries' },
          { name: 'SlidingWindowCompactor', description: 'Maintain a fixed N-message sliding window' },
        ],
      },
      {
        slot: 'Retriever',
        options: [
          { name: 'NullRetriever', description: 'No external memory retrieval' },
          { name: 'StaticRetriever', description: 'Fixed memory base loaded at initialization' },
        ],
      },
    ],
    architectureNotes:
      'Context is the first stage of every agent loop iteration. It bridges stateful memory management with token budget constraints, ensuring the API call stays within the context window.',
  },
  {
    order: 3,
    name: 'system',
    phase: 'B',
    category: 'ingress',
    canBypass: false,
    displayName: 'System',
    categoryLabel: 'Ingress',
    description: 'Build system prompt with persona and rules',
    detailedDescription:
      "Assembles the system prompt that defines the AI's behavior, constraints, personality, and operational rules. The system prompt can be a simple string or a rich list of content blocks (supporting images, cached sections, and structured instructions). If a tool registry is provided and tools haven't been registered yet, this stage also populates the tool definitions in state.",
    technicalBehavior: [
      'Calls builder strategy to construct system prompt',
      'Supports both string and content block list formats',
      'If tool_registry provided and state.tools empty, registers all tools',
      'System prompt is immutable after this stage — used in all subsequent API calls',
      "Emits 'system.built' event with prompt type, length, and tool count",
    ],
    strategies: [
      {
        slot: 'Prompt Builder',
        options: [
          { name: 'StaticPromptBuilder', description: 'Returns a fixed, preconfigured prompt' },
          { name: 'ComposablePromptBuilder', description: 'Builds from composable blocks: role, constraints, examples, instructions' },
        ],
      },
    ],
    architectureNotes:
      'The system prompt is foundational — it shapes all downstream AI behavior. Once built, it remains constant across loop iterations, providing consistent behavioral anchoring.',
  },
  {
    order: 4,
    name: 'guard',
    phase: 'B',
    category: 'pre_flight',
    canBypass: false,
    displayName: 'Guard',
    categoryLabel: 'Pre-Flight',
    description: 'Safety checks, budget enforcement, permission gates',
    detailedDescription:
      'Pre-flight safety and budget enforcement checkpoint. Runs an ordered chain of Guard validators that can reject execution, emit warnings, or allow continuation. This is the last gate before expensive API calls — checking token budget exhaustion, cost limits, iteration caps, and user permissions. Guards run in fail-fast chain order: the first failure aborts the entire pipeline.',
    technicalBehavior: [
      'Runs GuardChain with all registered guard validators in order',
      'Each guard returns GuardResult(passed, action, message)',
      'Chain stops at first failure (fail-fast pattern)',
      "action='warn': log warning event but continue execution",
      "action='reject': raise GuardRejectError and abort pipeline",
      "Emits 'guard.check' event and optionally 'guard.warn' events",
    ],
    strategies: [
      {
        slot: 'Guard Chain',
        options: [
          { name: 'TokenBudgetGuard', description: 'Fails if remaining tokens < threshold (default 10k)' },
          { name: 'CostBudgetGuard', description: 'Fails if cumulative cost exceeds USD budget' },
          { name: 'IterationGuard', description: 'Fails if iteration count >= max_iterations' },
          { name: 'PermissionGuard', description: 'Fails if user lacks required permissions' },
        ],
      },
    ],
    architectureNotes:
      "Guards provide defense-in-depth before committing tokens and cost. The chain can mix 'warn' (informational) and 'reject' (blocking) actions, allowing progressive alerting before hard stops.",
  },
  {
    order: 5,
    name: 'cache',
    phase: 'B',
    category: 'pre_flight',
    canBypass: true,
    bypassCondition: 'NoCacheStrategy configured (no markers to apply)',
    displayName: 'Cache',
    categoryLabel: 'Pre-Flight',
    description: 'Optimize prompt caching for cost efficiency',
    detailedDescription:
      "Applies Anthropic's ephemeral prompt caching markers to system prompts and message history. These markers tell the API which parts are 'stable' and can be cached across requests, reducing input token cost by up to 90%. The aggressive strategy can mark system instructions, tool definitions, and the stable prefix of conversation history.",
    technicalBehavior: [
      "Inserts cache_control: {type: 'ephemeral'} metadata on content blocks",
      'System prompt converted to content blocks if using system caching',
      'Aggressive strategy marks: system, tools, last N-4 stable message prefixes',
      'Cache is request-level (ephemeral), not persisted across sessions',
      "Emits 'cache.applied' event with strategy name",
      'Bypasses automatically if NoCacheStrategy is configured',
    ],
    strategies: [
      {
        slot: 'Cache Strategy',
        options: [
          { name: 'NoCacheStrategy', description: 'No caching applied (default for simple pipelines)' },
          { name: 'SystemCacheStrategy', description: 'Cache system prompt only — minimal optimization' },
          { name: 'AggressiveCacheStrategy', description: 'Cache system + tools + stable history prefix — maximum savings' },
        ],
      },
    ],
    architectureNotes:
      'Prompt caching is a major cost optimization lever. Cached input tokens cost ~10% of regular tokens. Particularly impactful for long system prompts, large tool registries, and multi-turn conversations.',
  },
  {
    order: 6,
    name: 'api',
    phase: 'B',
    category: 'execution',
    canBypass: false,
    displayName: 'API',
    categoryLabel: 'Execution',
    description: 'Call Anthropic Messages API',
    detailedDescription:
      'The core execution stage — calls the Anthropic Messages API with fully assembled messages, system prompt, tool definitions, and thinking configuration. Handles transient errors with configurable retry strategies (exponential backoff, rate-limit awareness). Returns an APIResponse containing content blocks, token usage, stop_reason, and model metadata. This is typically the most expensive stage in terms of token cost.',
    technicalBehavior: [
      'Builds APIRequest from state (model, messages, max_tokens, system, tools, thinking config)',
      'Calls provider strategy (AnthropicProvider for real API, MockProvider for testing)',
      'Retries on transient errors (rate limit, timeout) with exponential backoff',
      'Adds assistant message to state.messages from response content blocks',
      'Stores raw response in state.last_api_response for downstream stages',
      'Tracks token usage: input_tokens, output_tokens, cache_creation/read tokens',
      "Emits 'api.request' (before call) and 'api.response' (after call) events",
    ],
    strategies: [
      {
        slot: 'Provider',
        options: [
          { name: 'AnthropicProvider', description: 'Real API calls to Claude (production)' },
          { name: 'MockProvider', description: 'Fake deterministic responses (testing)' },
          { name: 'RecordingProvider', description: 'Records and replays API interactions' },
        ],
      },
      {
        slot: 'Retry',
        options: [
          { name: 'ExponentialBackoffRetry', description: 'Exponential backoff with jitter (default)' },
          { name: 'NoRetry', description: 'Fail immediately on error' },
          { name: 'RateLimitAwareRetry', description: 'Special handling for Anthropic rate limits' },
        ],
      },
    ],
    architectureNotes:
      'API stage bridges human intent to AI reasoning. Response content can include: text blocks (the answer), tool_use blocks (function call requests), and thinking blocks (internal reasoning with extended thinking). This is the only stage that calls an external service.',
  },
  {
    order: 7,
    name: 'token',
    phase: 'B',
    category: 'execution',
    canBypass: false,
    displayName: 'Token',
    categoryLabel: 'Execution',
    description: 'Track token usage and calculate costs',
    detailedDescription:
      "Tracks token consumption and calculates real-time USD cost. Pulls usage data from the last API response, accumulates it into the pipeline's running total, and applies model-specific pricing. Also updates cache hit/miss metrics when prompt caching is active, enabling cost optimization visibility.",
    technicalBehavior: [
      'Extracts usage from state.last_api_response (input, output, cache tokens)',
      'Tracker strategy decomposes usage by token type',
      'Calculator strategy computes cost using model-specific pricing rates',
      'Accumulates totals into state.total_cost_usd (running sum)',
      'Updates state.cache_metrics on cache_creation or cache_read tokens',
      "Emits 'token.tracked' event with detailed breakdown",
    ],
    strategies: [
      {
        slot: 'Tracker',
        options: [
          { name: 'DefaultTracker', description: 'Basic token counting (input + output)' },
          { name: 'DetailedTracker', description: 'Detailed breakdown by content type (text, tool, thinking)' },
        ],
      },
      {
        slot: 'Calculator',
        options: [
          { name: 'AnthropicPricingCalculator', description: 'Uses official Anthropic pricing table' },
          { name: 'CustomPricingCalculator', description: 'User-defined per-token rates' },
        ],
      },
    ],
    architectureNotes:
      'Cost tracking enables budget-aware execution. The token data feeds into the Guard stage (Stage 4) on subsequent iterations, allowing budget guards to halt execution before overspending.',
  },
  {
    order: 8,
    name: 'think',
    phase: 'B',
    category: 'execution',
    canBypass: true,
    bypassCondition: 'thinking_enabled=False or no thinking blocks in API response',
    displayName: 'Think',
    categoryLabel: 'Execution',
    description: 'Process extended thinking blocks',
    detailedDescription:
      "Processes Claude's extended thinking — the long-form internal reasoning that improves response quality. Separates thinking blocks from response blocks, runs processor strategy on thinking content (extraction, storage, or filtering), and passes non-thinking blocks downstream. Thinking content is internal to the AI and not returned to the user.",
    technicalBehavior: [
      'Bypasses if thinking_enabled=False OR no thinking blocks in response',
      "Extracts all blocks with type='thinking' from API response content",
      'Creates ThinkingBlock objects with text and budget_tokens_used',
      'Calls processor strategy to handle thinking content',
      'Separates response blocks (text, tool_use) from thinking blocks',
      'Sums total_thinking_tokens across all thinking blocks',
      "Emits 'think.processed' event with block count and token usage",
    ],
    strategies: [
      {
        slot: 'Thinking Processor',
        options: [
          { name: 'PassthroughProcessor', description: 'Store thinking content unchanged' },
          { name: 'ExtractAndStoreProcessor', description: 'Extract key insights from thinking and store them (default)' },
          { name: 'ThinkingFilterProcessor', description: 'Filter and summarize thinking before storage' },
        ],
      },
    ],
    architectureNotes:
      'Extended thinking is a Claude feature that allows the model to reason deeply before answering. Thinking tokens are separate from output tokens and consume the thinking_budget. This stage makes the internal reasoning auditable and processable.',
  },
  {
    order: 9,
    name: 'parse',
    phase: 'B',
    category: 'execution',
    canBypass: false,
    displayName: 'Parse',
    categoryLabel: 'Execution',
    description: 'Parse response and detect completion signals',
    detailedDescription:
      "Extracts structured information from the raw API response. Parses text content, tool calls, and thinking content into a unified ParsedResponse. Also runs signal detection — scanning response text for special patterns that indicate task completion, errors, blocked status, or continuation requests. These signals drive the agent's self-termination logic.",
    technicalBehavior: [
      'Accepts APIResponse from Stage 6 or retrieves from state.last_api_response',
      'Parser strategy extracts: text, tool_calls (id, name, input), thinking_texts',
      "Signal detector scans text for completion patterns: 'complete', 'blocked', 'error', 'continue'",
      'Stores tool calls in state.pending_tool_calls (consumed by Stage 10)',
      'Stores thinking in state.thinking_history (audit trail)',
      'Updates state.final_text with parsed response text',
      "Emits 'parse.complete' event with text length, tool call count, signal detected",
    ],
    strategies: [
      {
        slot: 'Response Parser',
        options: [
          { name: 'DefaultParser', description: 'Standard Anthropic API response parsing' },
          { name: 'StructuredOutputParser', description: 'For structured output mode (JSON schemas)' },
        ],
      },
      {
        slot: 'Signal Detector',
        options: [
          { name: 'RegexDetector', description: 'Uses regex patterns for fast signal detection (default)' },
          { name: 'StructuredDetector', description: 'JSON-based signal detection for structured output' },
          { name: 'HybridDetector', description: 'Combines multiple detection methods' },
        ],
      },
    ],
    architectureNotes:
      "Completion signals enable self-termination: the agent can declare 'I'm done' without tool calls. Example: response text ends with [COMPLETE] → detected as signal → evaluation stage completes the loop.",
  },
  {
    order: 10,
    name: 'tool',
    phase: 'B',
    category: 'execution',
    canBypass: true,
    bypassCondition: "No pending tool calls (AI didn't request any tools)",
    displayName: 'Tool',
    categoryLabel: 'Execution',
    description: 'Execute tool calls (sequential or parallel)',
    detailedDescription:
      'Executes function (tool) calls requested by the AI. Each tool_use block from the API response is dispatched to its registered implementation, executed either sequentially or in parallel, and results are collected and appended to the message history as user-role tool_result messages (per Anthropic API format). After execution, the loop is forced to continue so the AI can process tool results.',
    technicalBehavior: [
      'Bypasses if state.pending_tool_calls is empty (no tools requested)',
      'Router strategy dispatches each call to registered tool implementation',
      'Executor strategy runs tools: SequentialExecutor (one at a time) or ParallelExecutor (concurrent)',
      'Collects results: [{tool_use_id, content, is_error}, ...]',
      'Adds tool results to state.messages as user role message',
      "Forces state.loop_decision = 'continue' (ensures another API call for tool results)",
      "Emits 'tool.execute_start' and 'tool.execute_complete' events per tool",
    ],
    strategies: [
      {
        slot: 'Executor',
        options: [
          { name: 'SequentialExecutor', description: 'Run tools one by one — safer, predictable (default)' },
          { name: 'ParallelExecutor', description: 'Run tools concurrently — faster for independent calls' },
        ],
      },
      {
        slot: 'Router',
        options: [
          { name: 'RegistryRouter', description: 'Looks up tool implementation in state.tools registry' },
        ],
      },
    ],
    architectureNotes:
      "Tool execution is the mechanism that makes agents agentic. After tools run, loop_decision is forced to 'continue' regardless of evaluation, ensuring the AI sees and processes tool results in the next iteration. This creates the tool-use → API → tool-use cycle.",
  },
  {
    order: 11,
    name: 'agent',
    phase: 'B',
    category: 'execution',
    canBypass: true,
    bypassCondition: 'SingleAgentOrchestrator mode with no delegation requests',
    displayName: 'Agent',
    categoryLabel: 'Execution',
    description: 'Multi-agent orchestration and delegation',
    detailedDescription:
      'Multi-agent orchestration hub. Delegates specialized tasks to sub-pipelines (sub-agents) when the orchestrator strategy determines delegation is appropriate. Each sub-agent is an independent Pipeline instance with its own stages, budgets, and state. Results from sub-agents are collected, summarized, and integrated back into the main conversation, enabling hierarchical task decomposition.',
    technicalBehavior: [
      'Bypasses if SingleAgentOrchestrator AND no state.delegate_requests',
      'Orchestrator decides delegation based on state.delegate_requests',
      'Each delegation spawns a separate Pipeline instance (sub-agent)',
      'Sub-agents run independently with their own configuration and budget',
      'Collects sub-results and stores in state.agent_results',
      "If sub-results exist: adds summary to state.messages, forces loop_decision = 'continue'",
      "Emits 'agent.orchestrate_start' and 'agent.orchestrate_complete' events",
    ],
    strategies: [
      {
        slot: 'Orchestrator',
        options: [
          { name: 'SingleAgentOrchestrator', description: 'No delegation — pass-through (default)' },
          { name: 'DelegateOrchestrator', description: 'Delegate to specialized sub-agents' },
          { name: 'EvaluatorOrchestrator', description: 'Delegate to evaluator agents for quality checks' },
        ],
      },
    ],
    architectureNotes:
      'Sub-agents are fully isolated Pipeline instances. This enables divide-and-conquer architectures where a manager agent decomposes a complex task and delegates parts to expert agents. Each sub-agent can use a different preset and model.',
  },
  {
    order: 12,
    name: 'evaluate',
    phase: 'B',
    category: 'decision',
    canBypass: false,
    displayName: 'Evaluate',
    categoryLabel: 'Decision',
    description: 'Judge response quality and completeness',
    detailedDescription:
      "Critical decision point that evaluates whether the current response is 'good enough' to complete, or if the loop should continue, retry, or escalate. Combines strategy-based evaluation (signal detection, criteria matching, or secondary agent judgment) with optional quality scoring (0.0–1.0). The evaluation decision maps directly to the loop decision that determines pipeline control flow.",
    technicalBehavior: [
      'Runs evaluation strategy: analyzes state and returns EvaluationResult',
      'Optionally runs quality scorer for numerical score (0.0–1.0)',
      'Maps evaluation decision to loop_decision: complete, continue, retry, escalate, error',
      'Stores score in state.evaluation_score, feedback in state.evaluation_feedback',
      'Evaluation decision can override tool-use continuation',
      "Emits 'evaluate.complete' event with score, decision, and feedback",
    ],
    strategies: [
      {
        slot: 'Evaluation Strategy',
        options: [
          { name: 'SignalBasedEvaluation', description: 'Uses completion_signal from Parse stage (default)' },
          { name: 'CriteriaBasedEvaluation', description: 'Checks custom criteria: word count, format, content rules' },
          { name: 'AgentEvaluation', description: 'Calls a secondary agent to evaluate response quality' },
        ],
      },
      {
        slot: 'Scorer',
        options: [
          { name: 'NoScorer', description: 'No numerical quality scoring (default)' },
          { name: 'WeightedScorer', description: 'Multi-criteria scoring: relevance, completeness, format' },
        ],
      },
    ],
    architectureNotes:
      'Evaluation can override tool-use continuation — even with pending tools, evaluation can force completion or escalation. This prevents infinite loops and enables policy-driven early exits.',
  },
  {
    order: 13,
    name: 'loop',
    phase: 'B',
    category: 'decision',
    canBypass: false,
    displayName: 'Loop',
    categoryLabel: 'Decision',
    description: 'Decide whether to continue or finish the loop',
    detailedDescription:
      "Final loop control decision — the fork point of the pipeline. Respects terminal upstream decisions from Evaluate (complete, error, escalate) but applies its own controller strategy when upstream says 'continue'. The controller checks: are there pending tool results? was a completion signal detected? has the max iteration count been reached? is the budget nearly exhausted? Sets the final loop_decision that determines whether execution returns to Stage 2 or exits to Phase C.",
    technicalBehavior: [
      'Respects upstream loop_decision from Evaluate stage',
      'Terminal decisions (complete, error, escalate) pass through unchanged',
      "For 'continue' decisions: calls controller strategy for final verdict",
      'Controller checks: tool_results pending, completion signals, max iterations, budget',
      'Sets final state.loop_decision',
      'Clears state.tool_results (consumed for this iteration)',
      "Emits event: 'loop.{decision}' (e.g., 'loop.complete', 'loop.continue')",
    ],
    strategies: [
      {
        slot: 'Loop Controller',
        options: [
          { name: 'StandardLoopController', description: 'Tool results → continue, signals decide, end_turn → complete' },
          { name: 'SingleTurnController', description: 'Always complete immediately — no loop (single-turn mode)' },
          { name: 'BudgetAwareLoopController', description: 'Stops if cost/token budget ratio exceeds threshold' },
        ],
      },
    ],
    architectureNotes:
      "If loop_decision == 'continue': increment state.iteration and jump back to Stage 2 (Context). Otherwise: break out of Phase B and proceed to Phase C (Finalize). This is the only stage that controls the loop boundary.",
  },
  {
    order: 14,
    name: 'emit',
    phase: 'C',
    category: 'egress',
    canBypass: true,
    bypassCondition: 'No emitters registered in the chain',
    displayName: 'Emit',
    categoryLabel: 'Egress',
    description: 'Output results (text, callback, VTuber, TTS)',
    detailedDescription:
      'Delivers the final response to external consumers through multiple output channels simultaneously. The emitter chain fans out the result to registered destinations: text buffer for API responses, webhooks for callbacks, VTuber animation systems, TTS (text-to-speech) engines, and more. Emitters can fail independently without blocking others.',
    technicalBehavior: [
      'Bypasses if no emitters are registered in the chain',
      'Calls each emitter in the configured chain',
      'Each emitter customizes delivery: format, channel, filtering',
      'Collects results from all emitters',
      'Emitters can fail independently without blocking others (configurable)',
      "Emits 'emit.start' and 'emit.complete' events",
    ],
    strategies: [
      {
        slot: 'Emitter Chain',
        options: [
          { name: 'TextEmitter', description: 'Output to text buffer / API response' },
          { name: 'CallbackEmitter', description: 'Call webhook or callback function' },
          { name: 'VTuberEmitter', description: 'Output to VTuber animation system (Live2D/AIRI)' },
          { name: 'TTSEmitter', description: 'Output to text-to-speech engine' },
        ],
      },
    ],
    architectureNotes:
      'Emitters run conceptually in parallel — response fans out to multiple consumers. This enables multi-channel scenarios: chat UI + voice synthesis + logging, all from the same pipeline result.',
  },
  {
    order: 15,
    name: 'memory',
    phase: 'C',
    category: 'egress',
    canBypass: true,
    bypassCondition: 'stateless=True or NoMemoryStrategy configured',
    displayName: 'Memory',
    categoryLabel: 'Egress',
    description: 'Persist conversation memory',
    detailedDescription:
      'Persists conversation history and updates long-term memory stores. Applies the memory update strategy — determining what to save (everything, nothing, summaries) — and calls the persistence backend to write it (file, database, vector store). Essential for stateful agents that learn and remember across conversations.',
    technicalBehavior: [
      'Bypasses if stateless=True OR NoMemoryStrategy configured',
      'Calls memory update strategy to transform state.messages for storage',
      'If persistence configured and session_id present: calls persistence.save()',
      'Persistence writes to configured backend (RAM, file, database)',
      "Emits 'memory.updated' and optionally 'memory.persisted' events",
    ],
    strategies: [
      {
        slot: 'Update Strategy',
        options: [
          { name: 'AppendOnlyStrategy', description: 'Save all messages as-is (default)' },
          { name: 'NoMemoryStrategy', description: "Don't save anything — ephemeral execution" },
          { name: 'ReflectiveStrategy', description: 'Summarize and reflect on conversation before saving' },
        ],
      },
      {
        slot: 'Persistence',
        options: [
          { name: 'InMemoryPersistence', description: 'Store in RAM — session-scoped, lost on restart' },
          { name: 'FilePersistence', description: 'Store on disk — survives restarts' },
        ],
      },
    ],
    architectureNotes:
      "Memory separates 'what to save' (strategy) from 'where to save' (persistence). This decoupling allows the same conversation data to be stored in files, vector databases, or discarded entirely, depending on configuration.",
  },
  {
    order: 16,
    name: 'yield',
    phase: 'C',
    category: 'egress',
    canBypass: false,
    displayName: 'Yield',
    categoryLabel: 'Egress',
    description: 'Format and return final result',
    detailedDescription:
      "The terminal stage. Transforms the pipeline's accumulated state into the caller's expected output format: plain text, structured JSON with metadata, or a streaming iterator. Returns a PipelineResult containing the response text, total cost, iteration count, and any metadata. After this stage, pipeline execution is complete.",
    technicalBehavior: [
      'Calls formatter strategy to transform state into output format',
      'Formatter customizes: structure, metadata inclusion, serialization',
      'Returns state.final_output if set, otherwise state.final_text',
      "Emits 'yield.complete' event with text length, iteration count, total cost",
      'Pipeline execution ends here — result returned to caller',
    ],
    strategies: [
      {
        slot: 'Formatter',
        options: [
          { name: 'DefaultFormatter', description: 'Returns plain text response' },
          { name: 'StructuredFormatter', description: 'Returns JSON with metadata: cost, iterations, events' },
          { name: 'StreamingFormatter', description: 'Returns streaming iterator for real-time output' },
        ],
      },
    ],
    architectureNotes:
      'Final stage decouples pipeline logic from output format. The same pipeline can serve REST API, streaming WebSocket, batch job, or CLI — each needing different output shape — by swapping the formatter strategy.',
  },
];

/* ═══ Korean override — only text fields, strategy option
   names stay in English (they match backend identifiers) ═ */
type StageKo = {
  displayName: string;
  categoryLabel: string;
  description: string;
  detailedDescription: string;
  technicalBehavior: string[];
  strategies: StrategySlotMeta[];
  architectureNotes: string;
  bypassCondition?: string;
};

const STAGES_KO: Record<number, StageKo> = {
  1: {
    displayName: '입력',
    categoryLabel: '인그레스',
    description: '사용자 입력 검증 및 정규화',
    detailedDescription:
      '파이프라인의 진입점입니다. 텍스트, 멀티모달 콘텐츠, 구조화된 데이터 등 모든 형태의 원시 사용자 입력을 받아 스키마 제약 조건에 따라 검증하고, 표준화된 NormalizedInput 형식으로 변환합니다. 정규화된 메시지는 세션 추적 메타데이터와 함께 Anthropic API 형식의 대화 기록에 추가됩니다.',
    technicalBehavior: [
      '모든 형태의 원시 입력 수신 (텍스트, 멀티모달, 구조화 데이터)',
      '구성된 Validator 전략에 따라 유효성 검사 실행',
      'NormalizedInput으로 변환하여 텍스트 정규화',
      'Anthropic API 형식으로 state.messages에 사용자 메시지 추가',
      '정규화된 입력에 session_id 부착',
      "'input.normalized' 이벤트 발행 (텍스트 길이 포함)",
    ],
    strategies: [
      {
        slot: '검증기 (Validator)',
        options: [
          { name: 'DefaultValidator', description: '기본 타입 체크를 통한 대부분의 입력 수용' },
          { name: 'PassthroughValidator', description: '유효성 검사 없이 모든 입력 통과' },
          { name: 'StrictValidator', description: '엄격한 스키마 제약 조건 적용' },
          { name: 'SchemaValidator', description: '사용자 정의 JSON 스키마 검증' },
        ],
      },
      {
        slot: '정규화기 (Normalizer)',
        options: [
          { name: 'DefaultNormalizer', description: '텍스트 전용 정규화' },
          { name: 'MultimodalNormalizer', description: '이미지, 오디오 등 혼합 콘텐츠 처리' },
        ],
      },
    ],
    architectureNotes:
      'Input은 Phase A의 유일한 스테이지입니다. 파이프라인 호출당 한 번만 실행되며 우회할 수 없습니다. 모든 하위 스테이지는 이 스테이지가 생성하는 NormalizedInput에 의존합니다.',
  },
  2: {
    displayName: '컨텍스트',
    categoryLabel: '인그레스',
    description: '대화 기록 및 메모리 로드',
    detailedDescription:
      '현재 API 호출을 위한 컨텍스트를 수집하고 조합합니다. 상태에 이미 존재하는 대화 기록을 로드하고, 외부 저장소(벡터 DB, 파일 시스템)에서 관련 메모리 청크를 검색하며, 컨텍스트 크기를 예산 대비 모니터링합니다. 컨텍스트가 컨텍스트 윈도우 예산의 80%를 초과하면 자동으로 압축을 트리거하여 오래된 메시지를 제거하거나 요약합니다.',
    technicalBehavior: [
      '마지막 사용자 메시지에서 쿼리 추출 (멀티모달 추출 지원)',
      'Retriever 전략을 호출하여 관련 메모리 청크 가져오기',
      '키 기반 메모리 참조 중복 제거',
      '토큰 수 추정 (4자 ≈ 1토큰 휴리스틱)',
      'estimated_tokens > context_window_budget × 0.8일 때 압축 트리거',
      "state.memory_refs 및 state.metadata['memory_context'] 업데이트",
      "'context.built' 및 선택적으로 'context.compacted' 이벤트 발행",
    ],
    strategies: [
      {
        slot: '컨텍스트 전략',
        options: [
          { name: 'SimpleLoadStrategy', description: '상태에 이미 있는 메시지 사용 — 외부 검색 없음' },
          { name: 'HybridStrategy', description: '최근 N개의 턴 유지 + 관련 메모리 주입' },
          { name: 'ProgressiveDisclosureStrategy', description: '요약부터 시작하여 필요시 세부사항 확장' },
        ],
      },
      {
        slot: '압축기 (Compactor)',
        options: [
          { name: 'TruncateCompactor', description: '예산 초과 시 가장 오래된 메시지 제거' },
          { name: 'SummaryCompactor', description: '오래된 메시지를 AI 생성 요약으로 대체' },
          { name: 'SlidingWindowCompactor', description: '고정된 N개 메시지 슬라이딩 윈도우 유지' },
        ],
      },
      {
        slot: '검색기 (Retriever)',
        options: [
          { name: 'NullRetriever', description: '외부 메모리 검색 없음' },
          { name: 'StaticRetriever', description: '초기화 시 로드된 고정 메모리 베이스' },
        ],
      },
    ],
    architectureNotes:
      'Context는 매 에이전트 루프 반복의 첫 번째 스테이지입니다. 상태 기반 메모리 관리와 토큰 예산 제약 사이를 연결하여 API 호출이 컨텍스트 윈도우 내에 머물도록 보장합니다.',
    bypassCondition: 'stateless=True (기록이 없는 단일 턴 에이전트)',
  },
  3: {
    displayName: '시스템',
    categoryLabel: '인그레스',
    description: '페르소나와 규칙으로 시스템 프롬프트 구성',
    detailedDescription:
      'AI의 행동, 제약 조건, 성격, 운영 규칙을 정의하는 시스템 프롬프트를 조합합니다. 시스템 프롬프트는 단순 문자열 또는 풍부한 콘텐츠 블록 목록(이미지, 캐시된 섹션, 구조화된 지시사항 지원)이 될 수 있습니다. 도구 레지스트리가 제공되고 아직 도구가 등록되지 않았다면, 이 스테이지에서 도구 정의도 상태에 채웁니다.',
    technicalBehavior: [
      'Builder 전략을 호출하여 시스템 프롬프트 구성',
      '문자열 및 콘텐츠 블록 목록 형식 모두 지원',
      'tool_registry 제공 시 state.tools가 비어있으면 모든 도구 등록',
      '시스템 프롬프트는 이 스테이지 이후 불변 — 모든 후속 API 호출에서 사용',
      "'system.built' 이벤트 발행 (프롬프트 유형, 길이, 도구 수 포함)",
    ],
    strategies: [
      {
        slot: '프롬프트 빌더',
        options: [
          { name: 'StaticPromptBuilder', description: '사전 구성된 고정 프롬프트 반환' },
          { name: 'ComposablePromptBuilder', description: '조합 가능한 블록으로 구성: 역할, 제약, 예시, 지시사항' },
        ],
      },
    ],
    architectureNotes:
      '시스템 프롬프트는 기초적인 역할을 합니다 — 모든 하위 AI 행동을 형성합니다. 한 번 구성되면 루프 반복 전체에서 일관된 행동적 앵커링을 제공하며 변경되지 않습니다.',
  },
  4: {
    displayName: '가드',
    categoryLabel: '사전 점검',
    description: '안전 점검, 예산 집행, 권한 게이트',
    detailedDescription:
      '사전 비행 안전 및 예산 집행 검문소입니다. 실행을 거부하거나, 경고를 발행하거나, 계속을 허용할 수 있는 Guard 검증기의 순서화된 체인을 실행합니다. 비용이 많이 드는 API 호출 전의 마지막 관문으로, 토큰 예산 소진, 비용 한도, 반복 횟수 제한, 사용자 권한을 확인합니다. 가드는 실패 즉시 중단(fail-fast) 체인 순서로 실행됩니다.',
    technicalBehavior: [
      '등록된 모든 Guard 검증기를 순서대로 GuardChain으로 실행',
      '각 가드는 GuardResult(passed, action, message) 반환',
      '첫 번째 실패 시 체인 중단 (fail-fast 패턴)',
      "action='warn': 경고 이벤트 기록 후 실행 계속",
      "action='reject': GuardRejectError 발생 및 파이프라인 중단",
      "'guard.check' 이벤트 및 선택적으로 'guard.warn' 이벤트 발행",
    ],
    strategies: [
      {
        slot: '가드 체인',
        options: [
          { name: 'TokenBudgetGuard', description: '남은 토큰 < 임계값(기본 10k)이면 실패' },
          { name: 'CostBudgetGuard', description: '누적 비용이 USD 예산을 초과하면 실패' },
          { name: 'IterationGuard', description: '반복 횟수 >= max_iterations이면 실패' },
          { name: 'PermissionGuard', description: '사용자에게 필요한 권한이 없으면 실패' },
        ],
      },
    ],
    architectureNotes:
      "가드는 토큰과 비용을 투입하기 전에 심층 방어를 제공합니다. 체인은 '경고'(정보성)와 '거부'(차단)를 혼합할 수 있어 강제 중단 전에 점진적 경고를 가능하게 합니다.",
  },
  5: {
    displayName: '캐시',
    categoryLabel: '사전 점검',
    description: '비용 효율을 위한 프롬프트 캐싱 최적화',
    detailedDescription:
      "Anthropic의 임시 프롬프트 캐싱 마커를 시스템 프롬프트와 메시지 기록에 적용합니다. 이 마커는 API에 어떤 부분이 '안정적'이고 요청 간 캐시될 수 있는지 알려주어 입력 토큰 비용을 최대 90%까지 절감합니다. 공격적 전략은 시스템 지시사항, 도구 정의, 대화 기록의 안정적인 접두사에 마커를 적용할 수 있습니다.",
    technicalBehavior: [
      "콘텐츠 블록에 cache_control: {type: 'ephemeral'} 메타데이터 삽입",
      '시스템 캐싱 사용 시 시스템 프롬프트를 콘텐츠 블록으로 변환',
      '공격적 전략 마킹: 시스템, 도구, 마지막 N-4개 안정적 메시지 접두사',
      '캐시는 요청 수준(임시)이며 세션 간 유지되지 않음',
      "'cache.applied' 이벤트 발행 (전략 이름 포함)",
      'NoCacheStrategy가 구성된 경우 자동으로 우회',
    ],
    strategies: [
      {
        slot: '캐시 전략',
        options: [
          { name: 'NoCacheStrategy', description: '캐싱 미적용 (단순 파이프라인 기본값)' },
          { name: 'SystemCacheStrategy', description: '시스템 프롬프트만 캐시 — 최소 최적화' },
          { name: 'AggressiveCacheStrategy', description: '시스템 + 도구 + 안정적 기록 접두사 캐시 — 최대 절약' },
        ],
      },
    ],
    architectureNotes:
      '프롬프트 캐싱은 주요 비용 최적화 수단입니다. 캐시된 입력 토큰은 일반 토큰의 약 10% 비용만 발생합니다. 긴 시스템 프롬프트, 대규모 도구 레지스트리, 멀티턴 대화에서 특히 효과적입니다.',
    bypassCondition: 'NoCacheStrategy 구성 시 (적용할 마커 없음)',
  },
  6: {
    displayName: 'API',
    categoryLabel: '실행',
    description: 'Anthropic Messages API 호출',
    detailedDescription:
      '핵심 실행 스테이지 — 완전히 조합된 메시지, 시스템 프롬프트, 도구 정의, 사고(thinking) 설정과 함께 Anthropic Messages API를 호출합니다. 구성 가능한 재시도 전략(지수적 백오프, 속도 제한 인식)으로 일시적 오류를 처리합니다. 콘텐츠 블록, 토큰 사용량, stop_reason, 모델 메타데이터를 포함하는 APIResponse를 반환합니다.',
    technicalBehavior: [
      '상태에서 APIRequest 구성 (모델, 메시지, max_tokens, 시스템, 도구, 사고 설정)',
      'Provider 전략 호출 (실제 API용 AnthropicProvider, 테스트용 MockProvider)',
      '일시적 오류 시 지수적 백오프로 재시도 (속도 제한, 타임아웃)',
      '응답 콘텐츠 블록에서 어시스턴트 메시지를 state.messages에 추가',
      '하위 스테이지를 위해 원시 응답을 state.last_api_response에 저장',
      '토큰 사용량 추적: input_tokens, output_tokens, cache_creation/read tokens',
      "'api.request' (호출 전) 및 'api.response' (호출 후) 이벤트 발행",
    ],
    strategies: [
      {
        slot: '프로바이더',
        options: [
          { name: 'AnthropicProvider', description: 'Claude에 실제 API 호출 (프로덕션)' },
          { name: 'MockProvider', description: '결정론적 가짜 응답 (테스트)' },
          { name: 'RecordingProvider', description: 'API 상호작용 기록 및 재생' },
        ],
      },
      {
        slot: '재시도',
        options: [
          { name: 'ExponentialBackoffRetry', description: '지터가 포함된 지수적 백오프 (기본값)' },
          { name: 'NoRetry', description: '오류 시 즉시 실패' },
          { name: 'RateLimitAwareRetry', description: 'Anthropic 속도 제한 전용 처리' },
        ],
      },
    ],
    architectureNotes:
      'API 스테이지는 인간의 의도를 AI 추론으로 연결합니다. 응답 콘텐츠는 텍스트 블록(답변), tool_use 블록(함수 호출 요청), thinking 블록(확장된 사고를 통한 내부 추론)을 포함할 수 있습니다. 외부 서비스를 호출하는 유일한 스테이지입니다.',
  },
  7: {
    displayName: '토큰',
    categoryLabel: '실행',
    description: '토큰 사용량 추적 및 비용 계산',
    detailedDescription:
      '토큰 소비량을 추적하고 실시간 USD 비용을 계산합니다. 마지막 API 응답에서 사용량 데이터를 가져와 파이프라인의 누적 합계에 누적하고, 모델별 가격을 적용합니다. 프롬프트 캐싱이 활성화된 경우 캐시 적중/미적중 메트릭도 업데이트하여 비용 최적화 가시성을 제공합니다.',
    technicalBehavior: [
      'state.last_api_response에서 사용량 추출 (입력, 출력, 캐시 토큰)',
      'Tracker 전략이 토큰 유형별로 사용량 분해',
      'Calculator 전략이 모델별 가격 요율로 비용 산출',
      'state.total_cost_usd에 누계 누적 (러닝 합계)',
      'cache_creation 또는 cache_read 토큰 시 state.cache_metrics 업데이트',
      "'token.tracked' 이벤트 발행 (상세 분석 포함)",
    ],
    strategies: [
      {
        slot: '추적기',
        options: [
          { name: 'DefaultTracker', description: '기본 토큰 카운팅 (입력 + 출력)' },
          { name: 'DetailedTracker', description: '콘텐츠 유형별 상세 분석 (텍스트, 도구, 사고)' },
        ],
      },
      {
        slot: '계산기',
        options: [
          { name: 'AnthropicPricingCalculator', description: '공식 Anthropic 가격표 사용' },
          { name: 'CustomPricingCalculator', description: '사용자 정의 토큰당 요율' },
        ],
      },
    ],
    architectureNotes:
      '비용 추적은 예산 인식 실행을 가능하게 합니다. 토큰 데이터는 후속 반복에서 Guard 스테이지(4단계)에 공급되어 예산 가드가 과소비 전에 실행을 중단할 수 있게 합니다.',
  },
  8: {
    displayName: '사고',
    categoryLabel: '실행',
    description: '확장된 사고(thinking) 블록 처리',
    detailedDescription:
      'Claude의 확장된 사고 — 응답 품질을 향상시키는 장문의 내부 추론 — 를 처리합니다. 사고 블록을 응답 블록과 분리하고, 사고 콘텐츠에 프로세서 전략(추출, 저장, 필터링)을 실행하며, 비사고 블록을 하위로 전달합니다. 사고 콘텐츠는 AI 내부용이며 사용자에게 반환되지 않습니다.',
    technicalBehavior: [
      'thinking_enabled=False이거나 응답에 사고 블록이 없으면 우회',
      "API 응답 콘텐츠에서 type='thinking'인 모든 블록 추출",
      '텍스트 및 budget_tokens_used가 포함된 ThinkingBlock 객체 생성',
      '프로세서 전략을 호출하여 사고 콘텐츠 처리',
      '응답 블록(텍스트, tool_use)과 사고 블록 분리',
      '모든 사고 블록의 total_thinking_tokens 합산',
      "'think.processed' 이벤트 발행 (블록 수 및 토큰 사용량 포함)",
    ],
    strategies: [
      {
        slot: '사고 프로세서',
        options: [
          { name: 'PassthroughProcessor', description: '사고 콘텐츠를 변경 없이 저장' },
          { name: 'ExtractAndStoreProcessor', description: '사고에서 핵심 인사이트를 추출하여 저장 (기본값)' },
          { name: 'ThinkingFilterProcessor', description: '저장 전 사고 필터링 및 요약' },
        ],
      },
    ],
    architectureNotes:
      '확장된 사고는 모델이 답변 전에 깊이 추론할 수 있게 하는 Claude의 기능입니다. 사고 토큰은 출력 토큰과 별도이며 thinking_budget을 소비합니다. 이 스테이지는 내부 추론을 감사 가능하고 처리 가능하게 만듭니다.',
    bypassCondition: 'thinking_enabled=False 또는 API 응답에 사고 블록 없음',
  },
  9: {
    displayName: '파싱',
    categoryLabel: '실행',
    description: '응답 파싱 및 완료 신호 감지',
    detailedDescription:
      '원시 API 응답에서 구조화된 정보를 추출합니다. 텍스트 콘텐츠, 도구 호출, 사고 콘텐츠를 통합된 ParsedResponse로 파싱합니다. 또한 응답 텍스트에서 작업 완료, 오류, 차단 상태 또는 계속 요청을 나타내는 특수 패턴을 스캔하는 신호 감지를 실행합니다. 이 신호들이 에이전트의 자체 종료 로직을 구동합니다.',
    technicalBehavior: [
      'Stage 6의 APIResponse를 수신하거나 state.last_api_response에서 가져옴',
      'Parser 전략이 추출: 텍스트, tool_calls (id, name, input), thinking_texts',
      "신호 감지기가 텍스트에서 완료 패턴 스캔: 'complete', 'blocked', 'error', 'continue'",
      'state.pending_tool_calls에 도구 호출 저장 (Stage 10에서 소비)',
      'state.thinking_history에 사고 저장 (감사 추적)',
      '파싱된 응답 텍스트로 state.final_text 업데이트',
      "'parse.complete' 이벤트 발행 (텍스트 길이, 도구 호출 수, 감지된 신호 포함)",
    ],
    strategies: [
      {
        slot: '응답 파서',
        options: [
          { name: 'DefaultParser', description: '표준 Anthropic API 응답 파싱' },
          { name: 'StructuredOutputParser', description: '구조화된 출력 모드(JSON 스키마)용' },
        ],
      },
      {
        slot: '신호 감지기',
        options: [
          { name: 'RegexDetector', description: '빠른 신호 감지를 위한 정규식 패턴 사용 (기본값)' },
          { name: 'StructuredDetector', description: '구조화된 출력용 JSON 기반 신호 감지' },
          { name: 'HybridDetector', description: '여러 감지 방법 결합' },
        ],
      },
    ],
    architectureNotes:
      "완료 신호는 자체 종료를 가능하게 합니다: 에이전트가 도구 호출 없이 '작업이 완료되었습니다'라고 선언할 수 있습니다. 예: 응답 텍스트가 [COMPLETE]로 끝남 → 신호로 감지 → 평가 스테이지가 루프 완료.",
  },
  10: {
    displayName: '도구',
    categoryLabel: '실행',
    description: '도구 호출 실행 (순차 또는 병렬)',
    detailedDescription:
      'AI가 요청한 함수(도구) 호출을 실행합니다. API 응답의 각 tool_use 블록은 등록된 구현체로 라우팅되어 순차적 또는 병렬로 실행되며, 결과는 수집되어 Anthropic API 형식의 사용자 역할 tool_result 메시지로 메시지 기록에 추가됩니다. 실행 후 AI가 도구 결과를 처리할 수 있도록 루프가 강제로 계속됩니다.',
    technicalBehavior: [
      'state.pending_tool_calls가 비어있으면 우회 (요청된 도구 없음)',
      'Router 전략이 각 호출을 등록된 도구 구현체로 라우팅',
      'Executor 전략이 도구 실행: SequentialExecutor(하나씩) 또는 ParallelExecutor(동시)',
      '결과 수집: [{tool_use_id, content, is_error}, ...]',
      '사용자 역할 메시지로 state.messages에 도구 결과 추가',
      "state.loop_decision = 'continue' 강제 설정 (도구 결과를 위한 추가 API 호출 보장)",
      "도구별 'tool.execute_start' 및 'tool.execute_complete' 이벤트 발행",
    ],
    strategies: [
      {
        slot: '실행기',
        options: [
          { name: 'SequentialExecutor', description: '도구를 하나씩 실행 — 안전하고 예측 가능 (기본값)' },
          { name: 'ParallelExecutor', description: '독립적인 호출은 동시 실행 — 더 빠름' },
        ],
      },
      {
        slot: '라우터',
        options: [
          { name: 'RegistryRouter', description: 'state.tools 레지스트리에서 도구 구현체 조회' },
        ],
      },
    ],
    architectureNotes:
      "도구 실행은 에이전트를 에이전트답게 만드는 메커니즘입니다. 도구 실행 후 loop_decision이 평가에 관계없이 'continue'로 강제되어 AI가 다음 반복에서 도구 결과를 확인하고 처리하도록 합니다. 이것이 도구사용 → API → 도구사용 사이클을 만듭니다.",
    bypassCondition: '대기 중인 도구 호출 없음 (AI가 도구를 요청하지 않음)',
  },
  11: {
    displayName: '에이전트',
    categoryLabel: '실행',
    description: '멀티 에이전트 오케스트레이션 및 위임',
    detailedDescription:
      '멀티 에이전트 오케스트레이션 허브입니다. 오케스트레이터 전략이 위임이 적절하다고 판단할 때 전문화된 하위 파이프라인(서브 에이전트)에 작업을 위임합니다. 각 서브 에이전트는 자체 스테이지, 예산, 상태를 가진 독립적인 Pipeline 인스턴스입니다. 서브 에이전트의 결과는 수집, 요약되어 메인 대화에 통합되어 계층적 작업 분해를 가능하게 합니다.',
    technicalBehavior: [
      'SingleAgentOrchestrator이고 state.delegate_requests가 없으면 우회',
      'state.delegate_requests 기반으로 오케스트레이터가 위임 결정',
      '각 위임은 별도의 Pipeline 인스턴스(서브 에이전트) 생성',
      '서브 에이전트는 자체 구성과 예산으로 독립 실행',
      '서브 결과를 수집하여 state.agent_results에 저장',
      "서브 결과 존재 시: 요약을 state.messages에 추가, loop_decision = 'continue' 강제",
      "'agent.orchestrate_start' 및 'agent.orchestrate_complete' 이벤트 발행",
    ],
    strategies: [
      {
        slot: '오케스트레이터',
        options: [
          { name: 'SingleAgentOrchestrator', description: '위임 없음 — 패스스루 (기본값)' },
          { name: 'DelegateOrchestrator', description: '전문화된 서브 에이전트에 위임' },
          { name: 'EvaluatorOrchestrator', description: '품질 확인을 위한 평가자 에이전트에 위임' },
        ],
      },
    ],
    architectureNotes:
      '서브 에이전트는 완전히 격리된 Pipeline 인스턴스입니다. 관리자 에이전트가 복잡한 작업을 분해하여 전문가 에이전트에 부분을 위임하는 분할-정복 아키텍처를 가능하게 합니다. 각 서브 에이전트는 다른 프리셋과 모델을 사용할 수 있습니다.',
    bypassCondition: 'SingleAgentOrchestrator 모드에서 위임 요청 없음',
  },
  12: {
    displayName: '평가',
    categoryLabel: '결정',
    description: '응답 품질 및 완성도 판단',
    detailedDescription:
      "현재 응답이 '충분히 좋은지', 루프를 계속할지, 재시도할지, 에스컬레이션할지를 평가하는 핵심 결정 지점입니다. 전략 기반 평가(신호 감지, 기준 매칭, 보조 에이전트 판단)와 선택적 품질 점수(0.0–1.0)를 결합합니다. 평가 결정은 파이프라인 제어 흐름을 결정하는 루프 결정에 직접 매핑됩니다.",
    technicalBehavior: [
      '평가 전략 실행: 상태를 분석하여 EvaluationResult 반환',
      '선택적으로 품질 점수기 실행하여 수치 점수 (0.0–1.0) 산출',
      '평가 결정을 loop_decision에 매핑: complete, continue, retry, escalate, error',
      'state.evaluation_score에 점수, state.evaluation_feedback에 피드백 저장',
      '평가 결정이 도구 사용 계속을 오버라이드 가능',
      "'evaluate.complete' 이벤트 발행 (점수, 결정, 피드백 포함)",
    ],
    strategies: [
      {
        slot: '평가 전략',
        options: [
          { name: 'SignalBasedEvaluation', description: 'Parse 스테이지의 completion_signal 사용 (기본값)' },
          { name: 'CriteriaBasedEvaluation', description: '사용자 정의 기준 확인: 단어 수, 형식, 콘텐츠 규칙' },
          { name: 'AgentEvaluation', description: '보조 에이전트를 호출하여 응답 품질 평가' },
        ],
      },
      {
        slot: '점수기',
        options: [
          { name: 'NoScorer', description: '수치 품질 점수 없음 (기본값)' },
          { name: 'WeightedScorer', description: '다기준 점수: 관련성, 완성도, 형식' },
        ],
      },
    ],
    architectureNotes:
      '평가는 도구 사용 계속을 오버라이드할 수 있습니다 — 대기 중인 도구가 있어도 평가가 완료 또는 에스컬레이션을 강제할 수 있습니다. 이는 무한 루프를 방지하고 정책 기반 조기 종료를 가능하게 합니다.',
  },
  13: {
    displayName: '루프',
    categoryLabel: '결정',
    description: '루프를 계속할지 종료할지 결정',
    detailedDescription:
      "최종 루프 제어 결정 — 파이프라인의 분기점입니다. Evaluate의 종단 결정(complete, error, escalate)을 존중하지만, 상위가 'continue'라고 할 때 자체 컨트롤러 전략을 적용합니다. 컨트롤러는 확인합니다: 대기 중인 도구 결과가 있는가? 완료 신호가 감지되었는가? 최대 반복 횟수에 도달했는가? 예산이 거의 소진되었는가? 실행이 Stage 2로 돌아갈지 Phase C로 나갈지를 결정하는 최종 loop_decision을 설정합니다.",
    technicalBehavior: [
      'Evaluate 스테이지의 상위 loop_decision 존중',
      '종단 결정(complete, error, escalate)은 변경 없이 통과',
      "'continue' 결정의 경우: 최종 판정을 위해 컨트롤러 전략 호출",
      '컨트롤러 확인: tool_results 대기, 완료 신호, 최대 반복, 예산',
      '최종 state.loop_decision 설정',
      'state.tool_results 초기화 (이번 반복에서 소비됨)',
      "이벤트 발행: 'loop.{decision}' (예: 'loop.complete', 'loop.continue')",
    ],
    strategies: [
      {
        slot: '루프 컨트롤러',
        options: [
          { name: 'StandardLoopController', description: '도구 결과 → 계속, 신호가 결정, end_turn → 완료' },
          { name: 'SingleTurnController', description: '항상 즉시 완료 — 루프 없음 (단일 턴 모드)' },
          { name: 'BudgetAwareLoopController', description: '비용/토큰 예산 비율이 임계값 초과 시 중단' },
        ],
      },
    ],
    architectureNotes:
      "loop_decision == 'continue'이면: state.iteration을 증가시키고 Stage 2(Context)로 돌아갑니다. 그렇지 않으면: Phase B를 벗어나 Phase C(Finalize)로 진행합니다. 루프 경계를 제어하는 유일한 스테이지입니다.",
  },
  14: {
    displayName: '출력',
    categoryLabel: '이그레스',
    description: '결과 출력 (텍스트, 콜백, VTuber, TTS)',
    detailedDescription:
      '최종 응답을 여러 출력 채널을 통해 동시에 외부 소비자에게 전달합니다. Emitter 체인은 결과를 등록된 목적지로 팬아웃합니다: API 응답용 텍스트 버퍼, 콜백용 웹훅, VTuber 애니메이션 시스템, TTS(텍스트-투-스피치) 엔진 등. Emitter는 다른 것들을 차단하지 않고 독립적으로 실패할 수 있습니다.',
    technicalBehavior: [
      '체인에 등록된 Emitter가 없으면 우회',
      '구성된 체인의 각 Emitter 호출',
      '각 Emitter가 전달 방식 커스터마이즈: 형식, 채널, 필터링',
      '모든 Emitter에서 결과 수집',
      'Emitter는 다른 것들을 차단하지 않고 독립적으로 실패 가능 (구성 가능)',
      "'emit.start' 및 'emit.complete' 이벤트 발행",
    ],
    strategies: [
      {
        slot: 'Emitter 체인',
        options: [
          { name: 'TextEmitter', description: '텍스트 버퍼 / API 응답으로 출력' },
          { name: 'CallbackEmitter', description: '웹훅 또는 콜백 함수 호출' },
          { name: 'VTuberEmitter', description: 'VTuber 애니메이션 시스템으로 출력 (Live2D/AIRI)' },
          { name: 'TTSEmitter', description: '텍스트-투-스피치 엔진으로 출력' },
        ],
      },
    ],
    architectureNotes:
      'Emitter는 개념적으로 병렬 실행됩니다 — 응답이 여러 소비자에게 팬아웃됩니다. 이는 멀티 채널 시나리오를 가능하게 합니다: 채팅 UI + 음성 합성 + 로깅, 모두 같은 파이프라인 결과에서.',
    bypassCondition: '체인에 등록된 Emitter 없음',
  },
  15: {
    displayName: '메모리',
    categoryLabel: '이그레스',
    description: '대화 메모리 영속화',
    detailedDescription:
      '대화 기록을 영속화하고 장기 메모리 저장소를 업데이트합니다. 메모리 업데이트 전략 — 무엇을 저장할지 결정(전부, 없음, 요약) — 을 적용하고 영속성 백엔드를 호출하여 기록합니다(파일, 데이터베이스, 벡터 스토어). 대화를 통해 학습하고 기억하는 상태 유지 에이전트에 필수적입니다.',
    technicalBehavior: [
      'stateless=True이거나 NoMemoryStrategy 구성 시 우회',
      '메모리 업데이트 전략을 호출하여 저장용 state.messages 변환',
      '영속성 구성 시 session_id가 있으면 persistence.save() 호출',
      '구성된 백엔드에 기록 (RAM, 파일, 데이터베이스)',
      "'memory.updated' 및 선택적으로 'memory.persisted' 이벤트 발행",
    ],
    strategies: [
      {
        slot: '업데이트 전략',
        options: [
          { name: 'AppendOnlyStrategy', description: '모든 메시지를 그대로 저장 (기본값)' },
          { name: 'NoMemoryStrategy', description: '아무것도 저장하지 않음 — 일회성 실행' },
          { name: 'ReflectiveStrategy', description: '저장 전 대화를 요약하고 성찰' },
        ],
      },
      {
        slot: '영속성',
        options: [
          { name: 'InMemoryPersistence', description: 'RAM에 저장 — 세션 범위, 재시작 시 유실' },
          { name: 'FilePersistence', description: '디스크에 저장 — 재시작에도 유지' },
        ],
      },
    ],
    architectureNotes:
      "Memory는 '무엇을 저장할지'(전략)와 '어디에 저장할지'(영속성)를 분리합니다. 이 분리를 통해 같은 대화 데이터를 구성에 따라 파일, 벡터 데이터베이스에 저장하거나 완전히 폐기할 수 있습니다.",
    bypassCondition: 'stateless=True 또는 NoMemoryStrategy 구성',
  },
  16: {
    displayName: '반환',
    categoryLabel: '이그레스',
    description: '최종 결과 포맷팅 및 반환',
    detailedDescription:
      '터미널 스테이지입니다. 파이프라인의 누적된 상태를 호출자가 기대하는 출력 형식으로 변환합니다: 일반 텍스트, 메타데이터가 포함된 구조화된 JSON, 또는 스트리밍 이터레이터. 응답 텍스트, 총 비용, 반복 횟수, 메타데이터를 포함하는 PipelineResult를 반환합니다. 이 스테이지 이후 파이프라인 실행이 완료됩니다.',
    technicalBehavior: [
      'Formatter 전략을 호출하여 상태를 출력 형식으로 변환',
      'Formatter가 커스터마이즈: 구조, 메타데이터 포함, 직렬화',
      'state.final_output이 설정되면 반환, 아니면 state.final_text 반환',
      "'yield.complete' 이벤트 발행 (텍스트 길이, 반복 횟수, 총 비용 포함)",
      '파이프라인 실행은 여기서 종료 — 결과가 호출자에게 반환됨',
    ],
    strategies: [
      {
        slot: '포맷터',
        options: [
          { name: 'DefaultFormatter', description: '일반 텍스트 응답 반환' },
          { name: 'StructuredFormatter', description: '메타데이터 포함 JSON 반환: 비용, 반복, 이벤트' },
          { name: 'StreamingFormatter', description: '실시간 출력용 스트리밍 이터레이터 반환' },
        ],
      },
    ],
    architectureNotes:
      '최종 스테이지는 파이프라인 로직을 출력 형식에서 분리합니다. 같은 파이프라인이 REST API, 스트리밍 WebSocket, 배치 작업, CLI를 서비스할 수 있습니다 — 각각 다른 출력 형태가 필요하며 — Formatter 전략만 교체하면 됩니다.',
  },
};

export function getStageMetaByOrder(order: number, locale: Locale): StageMetaLocalized | undefined {
  const base = STAGES_EN.find((s) => s.order === order);
  if (!base) return undefined;
  if (locale === 'en') return base;
  const ko = STAGES_KO[order];
  if (!ko) return base;
  return {
    ...base,
    displayName: ko.displayName,
    categoryLabel: ko.categoryLabel,
    description: ko.description,
    detailedDescription: ko.detailedDescription,
    technicalBehavior: ko.technicalBehavior,
    strategies: ko.strategies,
    architectureNotes: ko.architectureNotes,
    bypassCondition: ko.bypassCondition ?? base.bypassCondition,
  };
}

export function getAllStageMeta(locale: Locale): StageMetaLocalized[] {
  return STAGES_EN.map((s) => getStageMetaByOrder(s.order, locale)!);
}

/**
 * Category colors — theme-aware, scoped to the pipeline view.
 *
 * `accent` resolves to one of Geny's semantic CSS vars (primary / success /
 * warning / danger / …), so it flips with the global light/dark switch.
 * `bg` and `border` are derived via `color-mix` so we don't hard-code
 * rgba values tied to a specific palette.
 */
export function getCategoryColor(category: string): {
  accent: string;
  bg: string;
  border: string;
} {
  const tint = (cssVar: string, bgPct: number, borderPct: number) => ({
    accent: cssVar,
    bg: `color-mix(in srgb, ${cssVar} ${bgPct}%, transparent)`,
    border: `color-mix(in srgb, ${cssVar} ${borderPct}%, transparent)`,
  });

  const map: Record<string, { accent: string; bg: string; border: string }> = {
    ingress: tint('var(--pipe-blue)', 10, 28),
    pre_flight: tint('var(--pipe-amber)', 10, 28),
    execution: tint('var(--pipe-purple)', 10, 28),
    decision: tint('var(--pipe-green)', 10, 28),
    egress: tint('var(--pipe-red)', 10, 28),
  };
  return (
    map[category] ?? {
      accent: 'var(--pipe-text-secondary)',
      bg: 'var(--pipe-bg-tertiary)',
      border: 'var(--pipe-border)',
    }
  );
}

/**
 * Derive a canonical category/phase for an order number.
 * Lets us position stages from the manifest even if the manifest
 * metadata doesn't carry a phase/category field explicitly.
 */
export function inferPhaseFromOrder(order: number): StagePhase {
  if (order === 1) return 'A';
  if (order >= 2 && order <= 13) return 'B';
  return 'C';
}

export function inferCategoryFromOrder(order: number): StageCategory {
  if (order >= 1 && order <= 3) return 'ingress';
  if (order >= 4 && order <= 5) return 'pre_flight';
  if (order >= 6 && order <= 11) return 'execution';
  if (order >= 12 && order <= 13) return 'decision';
  return 'egress';
}
