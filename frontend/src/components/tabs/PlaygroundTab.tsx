'use client';

import { useRef, useEffect, useCallback, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { useAppStore } from '@/store/useAppStore';
import { getRoads, getGroundTiles, BUILDINGS, NATURE } from '@/lib/cityLayout';
import { Asset3DLoader } from '@/lib/assetLoader';
import { AvatarSystem } from '@/lib/avatarSystem';

/* ────────────────────────────────────────────────────────────
   Camera controller (reproduces the orbit / pan / zoom from
   the original vanilla JS scene)
   ──────────────────────────────────────────────────────────── */

function CameraController() {
  const { camera, gl } = useThree();
  const state = useRef({
    angle: Math.PI / 4,
    pitch: Math.PI / 5,
    distance: 38,
    target: new THREE.Vector3(10, 0, 10),
    isPanning: false,
    isRotating: false,
    panStart: { x: 0, y: 0 },
    rotateStart: { x: 0, y: 0 },
    angleStart: 0,
    pitchStart: 0,
    targetStart: new THREE.Vector3(),
    clickStart: null as { x: number; y: number } | null,
  });

  const updateCam = useCallback(() => {
    const s = state.current;
    const x = s.target.x + s.distance * Math.cos(s.pitch) * Math.sin(s.angle);
    const y = s.target.y + s.distance * Math.sin(s.pitch);
    const z = s.target.z + s.distance * Math.cos(s.pitch) * Math.cos(s.angle);
    camera.position.set(x, y, z);
    camera.lookAt(s.target);
  }, [camera]);

  useEffect(() => {
    updateCam();
    const dom = gl.domElement;
    dom.style.cursor = 'grab';

    const onDown = (e: MouseEvent) => {
      const s = state.current;
      if (e.button === 0) {
        s.isPanning = true;
        s.panStart = { x: e.clientX, y: e.clientY };
        s.clickStart = { x: e.clientX, y: e.clientY };
        s.targetStart.copy(s.target);
        dom.style.cursor = 'move';
      } else if (e.button === 2) {
        s.isRotating = true;
        s.rotateStart = { x: e.clientX, y: e.clientY };
        s.angleStart = s.angle;
        s.pitchStart = s.pitch;
        dom.style.cursor = 'grabbing';
      }
    };

    const onMove = (e: MouseEvent) => {
      const s = state.current;
      if (s.isRotating) {
        const dx = e.clientX - s.rotateStart.x;
        const dy = e.clientY - s.rotateStart.y;
        s.angle = s.angleStart - dx * 0.005;
        s.pitch = Math.max(0.1, Math.min(Math.PI / 2.2, s.pitchStart + dy * 0.005));
        updateCam();
      }
      if (s.isPanning) {
        const dx = e.clientX - s.panStart.x;
        const dy = e.clientY - s.panStart.y;
        const panSpeed = 0.02 * (s.distance / 15);
        const rX = Math.cos(s.angle), rZ = -Math.sin(s.angle);
        const fX = Math.sin(s.angle), fZ = Math.cos(s.angle);
        s.target.x = s.targetStart.x - dx * rX * panSpeed - dy * fX * panSpeed;
        s.target.z = s.targetStart.z - dx * rZ * panSpeed - dy * fZ * panSpeed;
        updateCam();
      }
    };

    const onUp = (e: MouseEvent) => {
      const s = state.current;
      if (e.button === 0) {
        // click detection (< 5px drag)
        if (s.clickStart) {
          const dx = e.clientX - s.clickStart.x;
          const dy = e.clientY - s.clickStart.y;
          if (Math.sqrt(dx * dx + dy * dy) < 5) {
            handleAvatarClick(e);
          }
          s.clickStart = null;
        }
        s.isPanning = false;
      } else if (e.button === 2) {
        s.isRotating = false;
      }
      if (!s.isPanning && !s.isRotating) dom.style.cursor = 'grab';
    };

    const onLeave = () => {
      const s = state.current;
      s.isPanning = false;
      s.isRotating = false;
      dom.style.cursor = 'grab';
    };

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const s = state.current;
      s.distance = Math.max(8, Math.min(60, s.distance * (e.deltaY > 0 ? 1.1 : 0.9)));
      updateCam();
    };

    const ctx = (e: Event) => e.preventDefault();

    dom.addEventListener('mousedown', onDown);
    dom.addEventListener('mousemove', onMove);
    dom.addEventListener('mouseup', onUp);
    dom.addEventListener('mouseleave', onLeave);
    dom.addEventListener('wheel', onWheel, { passive: false });
    dom.addEventListener('contextmenu', ctx);

    return () => {
      dom.removeEventListener('mousedown', onDown);
      dom.removeEventListener('mousemove', onMove);
      dom.removeEventListener('mouseup', onUp);
      dom.removeEventListener('mouseleave', onLeave);
      dom.removeEventListener('wheel', onWheel);
      dom.removeEventListener('contextmenu', ctx);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gl, updateCam]);

  // expose imperative helpers
  const ref = useRef(state);
  (ref as React.MutableRefObject<typeof state>).current = state;

  // Expose resetView / zoom via a stable ref on the DOM element
  useEffect(() => {
    const dom = gl.domElement;
    (dom as unknown as Record<string, unknown>).__cameraCtrl = {
      zoomIn: () => { state.current.distance = Math.max(8, state.current.distance * 0.8); updateCam(); },
      zoomOut: () => { state.current.distance = Math.min(60, state.current.distance * 1.2); updateCam(); },
      resetView: () => {
        const s = state.current;
        s.angle = Math.PI / 4; s.pitch = Math.PI / 5; s.distance = 38;
        s.target.set(10, 0, 10);
        updateCam();
      },
    };
  }, [gl, updateCam]);

  // ── avatar click via raycaster ─────────────────────────
  const raycaster = useRef(new THREE.Raycaster());
  const mouse = useRef(new THREE.Vector2());

  const handleAvatarClick = useCallback((e: MouseEvent) => {
    const dom = gl.domElement;
    const rect = dom.getBoundingClientRect();
    mouse.current.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.current.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.current.setFromCamera(mouse.current, camera);

    const avatarSys: AvatarSystem | undefined = (dom as unknown as Record<string, unknown>).__avatarSystem as AvatarSystem | undefined;
    if (!avatarSys) return;

    const meshes: THREE.Mesh[] = [];
    for (const [sid, ad] of avatarSys.avatars) {
      ad.container.traverse((child) => {
        if ((child as THREE.Mesh).isMesh) {
          child.userData.sessionId = sid;
          meshes.push(child as THREE.Mesh);
        }
      });
    }

    const hits = raycaster.current.intersectObjects(meshes, false);
    if (hits.length > 0) {
      const sid = hits[0].object.userData.sessionId;
      if (sid) {
        // dispatch to zustand store
        useAppStore.getState().selectSession(sid);
      }
    }
  }, [camera, gl]);

  return null;
}

/* ────────────────────────────────────────────────────────────
   City builder + avatar manager  (runs inside <Canvas>)
   ──────────────────────────────────────────────────────────── */

/* ────────────────────────────────────────────────────────────
   Build city imperatively (roads, ground tiles, buildings, nature)
   ──────────────────────────────────────────────────────────── */

function buildCity(loader: Asset3DLoader, scene: THREE.Scene): void {
  // Ground tiles
  const tiles = getGroundTiles();
  for (const t of tiles) {
    const m = loader.getModel(t.type, t.name);
    if (m) {
      m.position.set(t.gx, 0, t.gz);
      m.rotation.y = t.rotation;
      m.receiveShadow = true;
      scene.add(m);
    } else if (t.isGround) {
      const geo = new THREE.PlaneGeometry(1, 1);
      const mat = new THREE.MeshLambertMaterial({ color: 0x4a7c3f });
      const fb = new THREE.Mesh(geo, mat);
      fb.rotation.x = -Math.PI / 2;
      fb.position.set(t.gx + 0.5, 0.001, t.gz + 0.5);
      fb.receiveShadow = true;
      scene.add(fb);
    }
  }

  // Roads
  for (const r of getRoads()) {
    const m = loader.getModel(r.type, r.name);
    if (m) {
      m.position.set(r.gx, 0, r.gz);
      m.rotation.y = r.rotation;
      m.receiveShadow = true;
      scene.add(m);
    }
  }

  // Buildings
  for (const b of BUILDINGS) {
    const m = loader.getModel(b.type, b.name);
    if (m) {
      m.position.set(b.gx, 0, b.gz);
      m.rotation.y = b.rotation;
      m.castShadow = true;
      m.receiveShadow = true;
      scene.add(m);
    }
  }

  // Nature
  for (const n of NATURE) {
    const m = loader.getModel(n.type, n.name);
    if (m) {
      m.position.set(n.gx, n.y ?? 0, n.gz);
      m.rotation.y = n.rotation;
      if (n.scale) m.scale.setScalar(n.scale);
      m.castShadow = true;
      m.receiveShadow = true;
      scene.add(m);
    }
  }
}

/* ────────────────────────────────────────────────────────────
   Main PlaygroundTab component
   ──────────────────────────────────────────────────────────── */

export default function PlaygroundTab() {
  const sessions = useAppStore((s) => s.sessions);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [loadingPct, setLoadingPct] = useState<number | null>(0);

  /** Toolbar button handlers — delegate to CameraController via domElement */
  const cameraCtrl = useCallback(() => {
    const canvas = document.querySelector('canvas');
    return (canvas as unknown as Record<string, { zoomIn: () => void; zoomOut: () => void; resetView: () => void }>)?.__cameraCtrl;
  }, []);

  const sessionList = sessions.map((s) => ({ session_id: s.session_id, session_name: s.session_name ?? undefined }));

  return (
    <div className="flex flex-col h-full rounded-lg overflow-hidden relative"
         style={{ background: 'linear-gradient(135deg, #0f0f1e 0%, #1a1a2e 50%, #16213e 100%)' }}>
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2 shrink-0 z-10"
           style={{
             background: 'rgba(0, 0, 0, 0.3)',
             borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
             minHeight: '44px',
           }}>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-[0.9rem] font-semibold text-[var(--text-primary)]">
            <span className="text-[1.1rem]">🏙️</span>
            City Playground
          </div>
          <span className="text-[0.75rem] text-[var(--text-muted)] px-2 py-0.5 rounded-full"
                style={{ background: 'rgba(255, 255, 255, 0.06)' }}>
            {sessions.length} citizens
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => cameraCtrl()?.zoomIn()}
            className="flex items-center justify-center w-[30px] h-[30px] rounded-[6px] text-[var(--text-secondary)] cursor-pointer transition-all duration-150 text-[0.85rem] p-0"
            style={{
              background: 'rgba(255, 255, 255, 0.06)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
            }}
            title="Zoom In"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4">
              <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </button>
          <button
            onClick={() => cameraCtrl()?.zoomOut()}
            className="flex items-center justify-center w-[30px] h-[30px] rounded-[6px] text-[var(--text-secondary)] cursor-pointer transition-all duration-150 text-[0.85rem] p-0"
            style={{
              background: 'rgba(255, 255, 255, 0.06)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
            }}
            title="Zoom Out"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4">
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </button>
          <button
            onClick={() => cameraCtrl()?.resetView()}
            className="flex items-center justify-center w-[30px] h-[30px] rounded-[6px] text-[var(--text-secondary)] cursor-pointer transition-all duration-150 text-[0.85rem] p-0"
            style={{
              background: 'rgba(255, 255, 255, 0.06)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
            }}
            title="Reset View"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4">
              <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
              <polyline points="9 22 9 12 15 12 15 22" />
            </svg>
          </button>
        </div>
      </div>

      {/* Canvas container */}
      <div className="flex-1 relative overflow-hidden cursor-grab active:cursor-grabbing">
        {/* Loading overlay */}
        {loadingPct !== null && loadingPct < 100 && (
          <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-4"
               style={{ background: 'rgba(15, 15, 30, 0.95)' }}>
            <div className="w-8 h-8 rounded-full animate-spin"
                 style={{
                   border: '3px solid rgba(255, 255, 255, 0.1)',
                   borderTopColor: 'var(--primary-color)',
                 }} />
            <div className="text-[0.85rem] text-[var(--text-secondary)]">Building city...</div>
          </div>
        )}

        {/* Three.js Canvas */}
        <Canvas
          shadows
          gl={{
            antialias: true,
            toneMapping: THREE.ACESFilmicToneMapping,
            toneMappingExposure: 1.3,
            outputColorSpace: THREE.SRGBColorSpace,
            powerPreference: 'high-performance',
          }}
          camera={{ fov: 45, near: 0.1, far: 200 }}
          onCreated={({ gl: renderer }) => {
            renderer.shadowMap.type = THREE.PCFSoftShadowMap;
            canvasRef.current = renderer.domElement;
          }}
          style={{ display: 'block', width: '100%', height: '100%' }}
        >
          {/* Fog */}
          <fogExp2 attach="fog" args={[0x9dd5f5, 0.012]} />

          {/* Lights */}
          <ambientLight color={0xfff5e6} intensity={0.5} />
          <directionalLight
            color={0xfffaf0}
            intensity={1.2}
            position={[20, 30, 15]}
            castShadow
            shadow-mapSize-width={4096}
            shadow-mapSize-height={4096}
            shadow-camera-near={1}
            shadow-camera-far={80}
            shadow-camera-left={-30}
            shadow-camera-right={30}
            shadow-camera-top={30}
            shadow-camera-bottom={-30}
            shadow-bias={-0.0003}
            shadow-normalBias={0.02}
            shadow-radius={2}
          />
          <directionalLight color={0xe6f0ff} intensity={0.4} position={[-15, 15, -10]} />
          <hemisphereLight args={[0xb4d7ff, 0x80c080, 0.4]} />

          {/* City platform */}
          <mesh position={[10, -1.02, 10]} receiveShadow castShadow>
            <boxGeometry args={[24, 2, 24]} />
            <meshStandardMaterial color={0x4a5568} roughness={0.9} metalness={0.1} />
          </mesh>

          {/* Camera controller (custom orbit) */}
          <CameraController />

          {/* City + avatars */}
          <CitySceneInner sessions={sessionList} onProgress={setLoadingPct} />
        </Canvas>
      </div>

      {/* Status overlay placeholder */}
      <div className="absolute bottom-3 left-3 flex flex-col gap-1 z-10 pointer-events-none" />

      {/* Empty state */}
      {sessions.length === 0 && loadingPct === null && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-center z-10 pointer-events-none">
          <div className="text-[0.8rem] text-[var(--text-muted)] px-4 py-1.5 rounded-full"
               style={{ background: 'rgba(0, 0, 0, 0.5)', backdropFilter: 'blur(8px)' }}>
            Create sessions to see citizens in the city!
          </div>
        </div>
      )}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────
   Inner scene wrapper (reports loading progress to parent)
   ──────────────────────────────────────────────────────────── */

interface CitySceneInnerProps {
  sessions: { session_id: string; session_name?: string }[];
  onProgress: (pct: number | null) => void;
}

function CitySceneInner({ sessions, onProgress }: CitySceneInnerProps) {
  const { scene, gl } = useThree();
  const assetLoader = useRef<Asset3DLoader | null>(null);
  const avatarSystem = useRef<AvatarSystem | null>(null);
  const lastTime = useRef(performance.now());

  useEffect(() => {
    let cancelled = false;

    (async () => {
      const loader = new Asset3DLoader();
      assetLoader.current = loader;
      await loader.loadAll((loaded, total) => {
        if (!cancelled) onProgress(Math.round((loaded / total) * 100));
      });
      if (cancelled) return;

      // Sky background
      const texLoader = new THREE.TextureLoader();
      texLoader.load('/static/assets/kloofendal_48d_partly_cloudy_puresky_4k.jpg', (tex) => {
        tex.mapping = THREE.EquirectangularReflectionMapping;
        scene.background = tex;
        scene.environment = tex;
      }, undefined, () => {
        // fallback: solid color
        scene.background = new THREE.Color(0x9dd5f5);
      });

      // Build city
      buildCity(loader, scene);

      // Avatar system
      const avSys = new AvatarSystem();
      await avSys.init(scene);
      avatarSystem.current = avSys;
      (gl.domElement as unknown as Record<string, unknown>).__avatarSystem = avSys;

      if (!cancelled) onProgress(null); // signal done
    })();

    return () => {
      cancelled = true;
      avatarSystem.current?.dispose();
      avatarSystem.current = null;
      assetLoader.current?.dispose();
      assetLoader.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    avatarSystem.current?.syncSessions(sessions);
  }, [sessions]);

  useFrame(() => {
    const now = performance.now();
    const dt = now - lastTime.current;
    lastTime.current = now;
    avatarSystem.current?.update(dt);
  });

  return null;
}
