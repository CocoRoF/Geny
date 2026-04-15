'use client';

import { useRef, useEffect, useState, useCallback } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { usePlayground2DStore } from '@/store/usePlayground2DStore';
import { useI18n } from '@/lib/i18n';


import type { WorldState, WorldEvent, GenySessionRole, WorldLayout } from '@/lib/playground2d/types';
import { ROLE_BUILDING_MAP } from '@/lib/playground2d/types';

// ─── Lazy imports (heavy modules loaded after mount) ───

let WorldMapClass: typeof import('@/lib/playground2d/worldMap').default | null = null;
let WorldEditorClass: typeof import('@/lib/playground2d/worldEditor').default | null = null;
let createWorldModelFn: typeof import('@/lib/playground2d/worldModel').createWorldModel | null = null;
let applyEventFn: typeof import('@/lib/playground2d/eventsPipeline').applyWorldEvent | null = null;

async function ensureModules() {
  if (!WorldMapClass || !createWorldModelFn || !applyEventFn) {
    console.log('[Playground2D] Starting module imports...');
    try {
      const [modelMod, eventsMod, wmMod, weMod] = await Promise.all([
        import('@/lib/playground2d/worldModel'),
        import('@/lib/playground2d/eventsPipeline'),
        import('@/lib/playground2d/worldMap'),
        import('@/lib/playground2d/worldEditor'),
      ]);
      WorldMapClass = wmMod.default;
      WorldEditorClass = weMod.default;
      createWorldModelFn = modelMod.createWorldModel;
      applyEventFn = eventsMod.applyWorldEvent;
      console.log('[Playground2D] All modules loaded');
    } catch (err) {
      console.error('[Playground2D] Module import failed:', err);
      throw err;
    }
  }
}

// ─── Fetch layout from backend ───

async function fetchLayout(): Promise<WorldLayout | null> {
  try {
    const res = await fetch('/api/playground2d/layout');
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// ─── Session → World Event conversion ───

function sessionToWorldEvents(
  sessions: { session_id: string; session_name: string | null; status: string; role: GenySessionRole }[],
  existingAgents: Record<string, unknown>,
): WorldEvent[] {
  const events: WorldEvent[] = [];
  const now = Date.now();

  for (const s of sessions) {
    const agentId = s.session_id;
    const agentName = s.session_name || agentId.substring(0, 10);

    // Ensure agent exists with a run_started event
    if (!existingAgents[agentId]) {
      events.push({
        event_type: 'run_started',
        agent_id: agentId,
        agent_name: agentName,
        run_id: `run_${agentId}`,
        timestamp: now,
      });
    }

    // Map session status to world events
    if (s.status === 'running') {
      events.push({
        event_type: 'task_assigned',
        agent_id: agentId,
        agent_name: agentName,
        task_id: `task_${agentId}`,
        task_label: `Session: ${agentName}`,
        timestamp: now,
      });
    } else if (s.status === 'stopped' || s.status === 'error') {
      events.push({
        event_type: 'run_completed',
        agent_id: agentId,
        agent_name: agentName,
        run_id: `run_${agentId}`,
        timestamp: now,
      });
    }
  }

  return events;
}

// ─── WebSocket helpers ───

function getWsBase(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  if (envUrl !== undefined && envUrl !== '') {
    return envUrl.replace(/^http/, 'ws');
  }
  if (typeof window !== 'undefined') {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const backendPort = process.env.NEXT_PUBLIC_BACKEND_PORT;
    if (backendPort) {
      return `${proto}//${window.location.hostname}:${backendPort}`;
    }
    return `${proto}//${window.location.host}`;
  }
  return 'ws://localhost:8000';
}

/** WebSocket subscription handle */
interface WsSubscription {
  close: () => void;
}

/** Parse an SSE log entry into a WorldEvent, or null if not relevant. */
function parseLogToWorldEvent(
  sessionId: string,
  sessionName: string,
  logData: Record<string, unknown>,
): WorldEvent | null {
  const data = (logData.data || logData) as Record<string, unknown>;
  const level = (data.level || '') as string;
  const meta = (data.metadata || {}) as Record<string, unknown>;
  const now = Date.now();

  if (level === 'TOOL' || meta.type === 'tool_use') {
    return {
      event_type: 'tool_called',
      agent_id: sessionId,
      agent_name: sessionName,
      tool_name: (meta.tool_name as string) || 'unknown',
      task_id: `task_${sessionId}`,
      timestamp: now,
    };
  }

  if (level === 'ITER' || meta.type === 'iteration_complete') {
    const isComplete = meta.is_complete === true;
    const success = meta.success !== false;
    if (isComplete) {
      return {
        event_type: success ? 'task_completed' : 'task_paused',
        agent_id: sessionId,
        agent_name: sessionName,
        task_id: `task_${sessionId}`,
        task_label: `Session: ${sessionName}`,
        timestamp: now,
      };
    }
  }

  if (level === 'COMMAND' || meta.type === 'command') {
    return {
      event_type: 'task_assigned',
      agent_id: sessionId,
      agent_name: sessionName,
      task_id: `task_${sessionId}`,
      task_label: (meta.preview as string)?.slice(0, 60) || `Session: ${sessionName}`,
      timestamp: now,
    };
  }

  return null;
}

/** Parse an SSE status event. */
function parseStatusToWorldEvent(
  sessionId: string,
  sessionName: string,
  statusData: Record<string, unknown>,
): WorldEvent | null {
  const status = (statusData.status || '') as string;
  if (status === 'completed' || status === 'error') {
    return {
      event_type: 'run_completed',
      agent_id: sessionId,
      agent_name: sessionName,
      run_id: `run_${sessionId}`,
      timestamp: Date.now(),
    };
  }
  if (status === 'running') {
    return {
      event_type: 'task_assigned',
      agent_id: sessionId,
      agent_name: sessionName,
      task_id: `task_${sessionId}`,
      task_label: `Session: ${sessionName}`,
      timestamp: Date.now(),
    };
  }
  return null;
}

// ─── Character Customization Panel ───

function CharacterThumbnail({ sheet, variantIndex, size = 40, onClick, selected }: {
  sheet: HTMLImageElement; variantIndex: number; size?: number;
  onClick?: () => void; selected?: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const charsPerSheet = 4;
  const charInSheet = variantIndex % charsPerSheet;

  useEffect(() => {
    const cvs = canvasRef.current;
    if (!cvs || !sheet) return;
    const ctx = cvs.getContext('2d');
    if (!ctx) return;
    const cellW = Math.floor(sheet.width / 12);
    const cellH = Math.floor(sheet.height / 8);
    const baseCol = (charInSheet % 4) * 3;
    const baseRow = Math.floor(charInSheet / 4) * 4;
    const sx = (baseCol + 1) * cellW; // idle frame
    const sy = baseRow * cellH;        // down direction
    ctx.clearRect(0, 0, size, size);
    ctx.drawImage(sheet, sx, sy, cellW, cellH, 2, 1, size - 4, size - 2);
  }, [sheet, charInSheet, size]);

  return (
    <canvas
      ref={canvasRef}
      width={size}
      height={size}
      onClick={onClick}
      className={`cursor-pointer rounded transition-all ${
        selected
          ? 'ring-2 ring-sky-400 bg-sky-400/20'
          : 'hover:ring-1 hover:ring-slate-400 bg-slate-800/80 hover:bg-slate-700/80'
      }`}
      style={{ width: size, height: size, imageRendering: 'pixelated' }}
    />
  );
}

function CharacterCustomizePanel({ spriteStore, onClose }: {
  spriteStore: { characterSheetImages: HTMLImageElement[] } | null;
  onClose: () => void;
}) {
  const sheets = spriteStore?.characterSheetImages || [];
  const charsPerSheet = 4;
  const totalVariants = sheets.length * charsPerSheet;

  const agentAvatars = usePlayground2DStore(s => s.agentAvatars);
  const setAgentAvatar = usePlayground2DStore(s => s.setAgentAvatar);
  const worldAgents = usePlayground2DStore(s => s.worldState?.agents);

  const agentList = Object.entries(worldAgents || {}).map(([id, a]) => ({ id, name: a.name || id.slice(0, 10) }));
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(agentList[0]?.id || null);

  const currentVariant = selectedAgentId ? agentAvatars[selectedAgentId] ?? null : null;

  if (sheets.length === 0) {
    return (
      <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/60">
        <div className="bg-slate-900 border border-slate-700 rounded-lg p-6 text-slate-300 text-sm">
          Character sheets not loaded yet.
          <button onClick={onClose} className="ml-4 text-sky-400 hover:underline">Close</button>
        </div>
      </div>
    );
  }

  return (
    <div className="absolute inset-0 z-30 flex bg-black/70" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="m-auto flex bg-slate-900 border border-slate-600 rounded-xl shadow-2xl overflow-hidden"
           style={{ maxWidth: '90%', maxHeight: '85%', width: 720, height: 520 }}>

        {/* Left: Agent list */}
        <div className="w-48 border-r border-slate-700 flex flex-col">
          <div className="px-3 py-2 text-xs font-bold text-sky-300 border-b border-slate-700 bg-slate-800/60">
            Agents ({agentList.length})
          </div>
          <div className="flex-1 overflow-y-auto">
            {agentList.length === 0 && (
              <div className="p-3 text-xs text-slate-500">No agents yet.<br/>Agents appear when sessions are running.</div>
            )}
            {agentList.map(a => {
              const av = agentAvatars[a.id];
              const sheetIdx = av != null ? Math.floor(av / charsPerSheet) : null;
              const sheet = sheetIdx != null ? sheets[sheetIdx] : null;
              return (
                <button
                  key={a.id}
                  onClick={() => setSelectedAgentId(a.id)}
                  className={`w-full flex items-center gap-2 px-3 py-2 text-left text-xs transition-colors ${
                    selectedAgentId === a.id
                      ? 'bg-sky-400/15 text-sky-200'
                      : 'text-slate-300 hover:bg-slate-800'
                  }`}
                >
                  {sheet ? (
                    <CharacterThumbnail sheet={sheet} variantIndex={av!} size={28} />
                  ) : (
                    <div className="w-7 h-7 rounded bg-slate-700 flex items-center justify-center text-[10px] text-slate-500">?</div>
                  )}
                  <span className="truncate">{a.name}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Right: Character grid */}
        <div className="flex-1 flex flex-col">
          <div className="px-4 py-2 flex items-center justify-between border-b border-slate-700 bg-slate-800/60">
            <div className="text-xs font-bold text-slate-200">
              {selectedAgentId
                ? `Select character for: ${agentList.find(a => a.id === selectedAgentId)?.name || '?'}`
                : 'Select an agent first'
              }
            </div>
            <button onClick={onClose} className="text-slate-400 hover:text-white text-sm px-2 py-0.5 rounded hover:bg-slate-700">
              ✕
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-3">
            <div className="grid gap-1" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(42px, 1fr))' }}>
              {Array.from({ length: totalVariants }, (_, vi) => {
                const sheetIdx = Math.floor(vi / charsPerSheet);
                const sheet = sheets[sheetIdx];
                if (!sheet) return null;
                return (
                  <CharacterThumbnail
                    key={vi}
                    sheet={sheet}
                    variantIndex={vi}
                    size={42}
                    selected={currentVariant === vi}
                    onClick={() => {
                      if (selectedAgentId) {
                        setAgentAvatar(selectedAgentId, vi);
                      }
                    }}
                  />
                );
              })}
            </div>
          </div>
          <div className="px-4 py-2 text-[10px] text-slate-500 border-t border-slate-700">
            {totalVariants} characters available · Click to assign · Saved to local storage
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Loading overlay ───

function LoadingOverlay({ progress, message }: { progress: number; message: string }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#10200f] z-10">
      <div className="text-[#9ad09a] text-lg font-bold mb-4">{message}</div>
      <div className="w-64 h-3 bg-[#1a3a18] rounded-full overflow-hidden border border-[#375934]">
        <div
          className="h-full bg-[#5aad5e] rounded-full transition-all duration-300"
          style={{ width: `${Math.round(progress * 100)}%` }}
        />
      </div>
      <div className="text-[#6b9b6b] text-sm mt-2">{Math.round(progress * 100)}%</div>
    </div>
  );
}

// ─── Asset status panel ───

function AssetPanel({ loaded, missing, missingKeys }: { loaded: number; missing: number; missingKeys: string[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="absolute top-2 left-2 z-20">
      <button
        onClick={() => setOpen(!open)}
        className="px-2.5 py-1.5 text-xs font-medium rounded bg-[rgba(15,23,42,0.9)] text-[#fde68a] border border-[#fbbf24] cursor-pointer hover:bg-[rgba(15,23,42,1)]"
      >
        Assets {missing > 0 ? `(${missing} missing)` : '→'}
      </button>
      {open && (
        <div className="mt-1 p-3 rounded-lg bg-[rgba(15,23,42,0.96)] border border-[#475569] text-xs max-w-[300px] max-h-[400px] overflow-auto">
          <div className="text-[#e2e8f0] font-bold mb-2">Sprite Summary</div>
          <div className="text-[#94a3b8] mb-1">Loaded: {loaded}</div>
          <div className="text-[#94a3b8] mb-2">Fallback: {missing}</div>
          {missingKeys.length > 0 && (
            <>
              <div className="text-[#fbbf24] font-bold mb-1 mt-2">Missing sprites:</div>
              <div className="text-[#64748b] space-y-0.5">
                {missingKeys.slice(0, 40).map(k => (
                  <div key={k} className="truncate">{k}</div>
                ))}
                {missingKeys.length > 40 && (
                  <div className="text-[#475569]">...and {missingKeys.length - 40} more</div>
                )}
              </div>
            </>
          )}
          <div className="text-[#475569] mt-3 text-[10px] leading-tight">
            Place PixyMoon sprites in<br />
            <code className="text-[#64748b]">public/assets/pixymoon/Cute RPG World/</code>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main component ───

export default function Playground2DTab() {
  const containerRef = useRef<HTMLDivElement>(null);
  const worldMapRef = useRef<InstanceType<typeof import('@/lib/playground2d/worldMap').default> | null>(null);
  const worldEditorRef = useRef<InstanceType<typeof import('@/lib/playground2d/worldEditor').default> | null>(null);
  const worldStateRef = useRef<WorldState | null>(null);
  const savedLayoutRef = useRef<WorldLayout | null>(null);
  const prevSessionIdsRef = useRef<string>('');

  const [loading, setLoading] = useState(true);
  const [loadProgress, setLoadProgress] = useState(0);
  const [loadMessage, setLoadMessage] = useState('Initializing world...');
  const [assetInfo, setAssetInfo] = useState<{ loaded: number; missing: number; missingKeys: string[] } | null>(null);
  const [showCharPanel, setShowCharPanel] = useState(false);

  const sessions = useAppStore(s => s.sessions);
  const selectSession = useAppStore(s => s.selectSession);
  const setActiveTab = useAppStore(s => s.setActiveTab);
  const { t } = useI18n();

  // Agent click → select session + switch to info tab
  const handleAgentClick = useCallback((agentId: string) => {
    selectSession(agentId);
    setActiveTab('info');
  }, [selectSession, setActiveTab]);

  // ─── Initialize world + renderer ───
  useEffect(() => {
    if (!containerRef.current) return;

    let destroyed = false;

    (async () => {
      try {
        console.log('[Playground2D] Init starting...');
        setLoadMessage('Loading modules...');
        setLoadProgress(0.1);
        await ensureModules();
        if (destroyed) return;

        console.log('[Playground2D] Fetching layout...');
        setLoadMessage('Fetching layout...');
        setLoadProgress(0.2);

        // Fetch layout from backend so canvas and editor share the same data
        const layout = await fetchLayout();
        savedLayoutRef.current = layout;
        if (destroyed) return;

        console.log('[Playground2D] Building world...');
        setLoadMessage('Building world...');
        setLoadProgress(0.3);

        // Create world model — pass layout so it matches what the editor will load
        const worldModel = createWorldModelFn!(layout);
        const initialState: WorldState = {
          world: worldModel,
          agents: {},
          avatars: {},
          runs: {},
          meta: { lastEventAt: Date.now() },
        };
        worldStateRef.current = initialState;
        usePlayground2DStore.getState().setWorldState(initialState);

        if (destroyed || !containerRef.current) return;

        console.log('[Playground2D] Loading sprites...');
        setLoadMessage('Loading sprites...');
        setLoadProgress(0.5);

        // Create WorldMap renderer
        const map = new WorldMapClass!(containerRef.current, {
          onAgentClick: handleAgentClick,
          getCustomAvatarVariant: (agentId: string) => usePlayground2DStore.getState().getAgentAvatar(agentId),
          onAvatarVariantChanged: (agentId: string, variantIndex: number) => usePlayground2DStore.getState().setAgentAvatar(agentId, variantIndex),
        });
        worldMapRef.current = map;

        // Load sprites with progress
        await map.loadSprites((loaded, total) => {
          if (!destroyed) {
            setLoadProgress(0.5 + (loaded / Math.max(total, 1)) * 0.5);
          }
        });

        if (destroyed) { map.destroy(); return; }

        // Check asset summary
        const summary = map.assetSummary;
        if (summary) {
          console.log('[Playground2D] Sprites loaded:', summary.loadedCount, 'missing:', summary.missingKeys.length);
          setAssetInfo({ loaded: summary.loadedCount, missing: summary.missingKeys.length, missingKeys: summary.missingKeys });
        }

        // Set initial state and start rendering
        map.setWorldState(initialState);
        map.start();

        // Initialize World Editor — appends DOM inside containerRef (position: absolute)
        if (WorldEditorClass && containerRef.current) {
          const editor = new WorldEditorClass({
            worldMap: map,
            container: containerRef.current,
            apiBaseUrl: '',  // same origin
            onLayoutChanged: (newLayout: WorldLayout) => {
              // When editor saves, rebuild world with new layout and persist
              savedLayoutRef.current = newLayout;
              if (!createWorldModelFn || !worldStateRef.current) return;
              const prev = worldStateRef.current;
              const newWorld = createWorldModelFn(newLayout);
              const nextState: WorldState = {
                world: newWorld,
                agents: prev.agents,
                avatars: prev.avatars,
                runs: prev.runs,
                meta: prev.meta,
              };
              worldStateRef.current = nextState;
              worldMapRef.current?.setWorldState(nextState);
              usePlayground2DStore.getState().setWorldState(nextState);
              console.log('[Playground2D] Layout saved and applied to world state');
            },
          });
          worldEditorRef.current = editor;
        }

        console.log('[Playground2D] Ready!');
        setLoading(false);
        setLoadProgress(1);
        usePlayground2DStore.getState().setLoading(false);
      } catch (err) {
        console.error('[Playground2D] Init error:', err);
        if (!destroyed) {
          setLoadMessage('Failed to initialize world');
          setLoading(false);
        }
      }
    })();

    return () => {
      destroyed = true;
      if (worldEditorRef.current) {
        worldEditorRef.current.destroy();
        worldEditorRef.current = null;
      }
      if (worldMapRef.current) {
        worldMapRef.current.destroy();
        worldMapRef.current = null;
      }
    };
  }, [handleAgentClick]);

  // ─── Sync Geny sessions → world events ───
  useEffect(() => {
    const map = worldMapRef.current;
    const currentState = worldStateRef.current;
    if (!map || !currentState || loading) return;

    // Deduplicate: only process when session list actually changes
    const sessionKey = sessions.map(s => `${s.session_id}:${s.status}:${s.role}:${s.session_name}`).join('|');
    if (sessionKey === prevSessionIdsRef.current) return;
    prevSessionIdsRef.current = sessionKey;

    const sessionsByRole = new Map<string, GenySessionRole>();
    const mappedSessions = sessions.map(s => {
      const role = (s.role || 'worker') as GenySessionRole;
      sessionsByRole.set(s.session_id, role);
      return {
        session_id: s.session_id,
        session_name: s.session_name,
        status: s.status,
        role,
      };
    });

    const events = sessionToWorldEvents(mappedSessions, currentState.agents);

    if (events.length === 0) return;

    // Apply events to state (applyWorldEvent mutates in-place)
    // Deep clone to avoid shared mutation issues
    const nextState: WorldState = JSON.parse(JSON.stringify(currentState));
    for (const event of events) {
      applyEventFn!(nextState, event);
    }

    // Assign roles to agents so destination logic can use ROLE_BUILDING_MAP
    for (const [sessionId, role] of sessionsByRole) {
      if (nextState.agents[sessionId]) {
        nextState.agents[sessionId].role = role;
      }
    }

    worldStateRef.current = nextState;
    map.setWorldState(nextState);
    usePlayground2DStore.getState().setWorldState(nextState);
  }, [sessions, loading]);

  // ─── WebSocket subscriptions for running sessions (real-time events) ───
  const wsSubsRef = useRef<Map<string, WsSubscription>>(new Map());

  const applyRealtimeEvent = useCallback((event: WorldEvent) => {
    const map = worldMapRef.current;
    const currentState = worldStateRef.current;
    if (!map || !currentState || !applyEventFn) return;

    const nextState: WorldState = JSON.parse(JSON.stringify(currentState));
    applyEventFn(nextState, event);

    // Preserve roles
    for (const [agentId, agent] of Object.entries(currentState.agents)) {
      if (agent.role && nextState.agents[agentId]) {
        nextState.agents[agentId].role = agent.role;
      }
    }

    worldStateRef.current = nextState;
    map.setWorldState(nextState);
    usePlayground2DStore.getState().setWorldState(nextState);
  }, []);

  useEffect(() => {
    if (loading || !applyEventFn) return;
    const subs = wsSubsRef.current;
    const wsBase = getWsBase();
    const runningSessions = sessions.filter(s => s.status === 'running');
    const runningIds = new Set(runningSessions.map(s => s.session_id));

    // Close subscriptions for sessions that are no longer running
    for (const [id, sub] of subs) {
      if (!runningIds.has(id)) {
        sub.close();
        subs.delete(id);
      }
    }

    // Open WebSocket subscriptions for new running sessions
    for (const s of runningSessions) {
      if (subs.has(s.session_id)) continue;
      const sessionId = s.session_id;
      const sessionName = s.session_name || sessionId.substring(0, 10);
      const wsUrl = `${wsBase}/ws/execute/${sessionId}`;
      let ws: WebSocket | null = null;
      let closed = false;

      try {
        ws = new WebSocket(wsUrl);
      } catch { continue; }

      ws.onopen = () => {
        ws!.send(JSON.stringify({ type: 'reconnect' }));
      };

      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === 'log') {
            const event = parseLogToWorldEvent(sessionId, sessionName, msg.data as Record<string, unknown>);
            if (event) applyRealtimeEvent(event);
          } else if (msg.type === 'status') {
            const event = parseStatusToWorldEvent(sessionId, sessionName, msg.data as Record<string, unknown>);
            if (event) applyRealtimeEvent(event);
          } else if (msg.type === 'done') {
            subs.delete(sessionId);
          }
        } catch { /* ignore */ }
      };

      ws.onerror = () => { ws = null; };
      ws.onclose = () => { ws = null; if (!closed) subs.delete(sessionId); };

      subs.set(sessionId, { close: () => { closed = true; if (ws) { ws.close(); ws = null; } } });
    }

    return () => {
      // Don't close on every re-render — only on unmount
    };
  }, [sessions, loading, applyRealtimeEvent]);

  // Cleanup all WebSocket subscriptions on unmount
  useEffect(() => {
    return () => {
      for (const sub of wsSubsRef.current.values()) {
        sub.close();
      }
      wsSubsRef.current.clear();
    };
  }, []);

  // ─── Auto-poll sessions every 30 seconds ───
  useEffect(() => {
    if (loading) return;
    const loadSessions = useAppStore.getState().loadSessions;
    if (!loadSessions) return;

    const interval = setInterval(() => {
      loadSessions();
    }, 30_000);

    return () => clearInterval(interval);
  }, [loading]);

  return (
    <div
      ref={containerRef}
      className="flex-1 min-h-0 bg-[#10200f] overflow-hidden"
      style={{ position: 'relative' }}
    >
      {loading && <LoadingOverlay progress={loadProgress} message={loadMessage} />}
      {assetInfo && <AssetPanel loaded={assetInfo.loaded} missing={assetInfo.missing} missingKeys={assetInfo.missingKeys} />}

      {/* Character customization toggle */}
      {!loading && (
        <button
          onClick={() => setShowCharPanel(true)}
          className="absolute bottom-3 right-3 z-20 px-3 py-1.5 text-xs font-medium rounded-lg bg-[rgba(15,23,42,0.92)] text-amber-200 border border-amber-500/60 cursor-pointer hover:bg-[rgba(15,23,42,1)] hover:border-amber-400 transition-colors"
        >
          🎭 Characters
        </button>
      )}

      {/* Character customization panel */}
      {showCharPanel && (
        <CharacterCustomizePanel
          spriteStore={worldMapRef.current?.spriteStore || null}
          onClose={() => setShowCharPanel(false)}
        />
      )}
    </div>
  );
}
