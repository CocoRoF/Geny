/**
 * AudioManager — Web Audio API 기반 TTS 오디오 재생 관리자
 *
 * 책임:
 *  - AudioContext 초기화 + resume (브라우저 자동재생 정책 대응)
 *  - TTS 재생 큐: 다중 에이전트 응답을 순차 재생 (이전 재생을 중단하지 않음)
 *  - StreamingResponse → Blob → Audio 재생
 *  - Web Audio API: AudioBufferSourceNode → AnalyserNode → GainNode → destination
 *  - 진폭 콜백: requestAnimationFrame 루프에서 RMS 계산 (립싱크용)
 *  - 볼륨 제어: GainNode.gain 조절
 *  - stop / clearQueue / dispose
 *  - AbortController 지원: 큐 비우기 시 진행 중 TTS fetch 취소
 *  - iOS/iPadOS WebKit 호환: user gesture 기반 AudioContext 활성화,
 *    decodeAudioData + AudioBufferSourceNode로 HTMLAudioElement 우회
 *
 * iOS 재생 전략:
 *  HTMLAudioElement.play()는 iOS WebKit에서 user gesture 밖에서 차단되므로,
 *  AudioContext.decodeAudioData() + AudioBufferSourceNode.start()를 사용한다.
 *  AudioBufferSourceNode는 AudioContext가 running이면 gesture 없이 재생 가능.
 *  AudioContext.resume()은 ensureResumed()를 통해 user gesture에서 수행된다.
 *  Desktop Chrome에서도 동일하게 작동하므로 분기 없이 단일 경로로 처리한다.
 */

export interface TTSQueueItem {
  response: Response;
  sessionId: string;
  onStart?: () => void;
  onEnd?: () => void;
  /** Pre-fetch된 Blob promise (큐 처리 시 다음 아이템 미리 준비) */
  _prefetchPromise?: Promise<Blob | null>;
  /** 이 클립이 속한 "턴" 식별자. 새 턴이 시작되면 이전 턴의 잔여
   *  아이템을 선별적으로 버릴 수 있다. null이면 legacy 단일 클립. */
  turnId?: string;
  /** 턴 내 seq — strict 순서 보장용. undefined면 도착 순서 재생. */
  seq?: number;
}

export interface EnqueueOptions {
  /** 이 클립이 속한 턴 식별자. 새 턴이 시작되면
   *  ``clearTurn(oldTurnId)`` 로 잔여 아이템을 제거할 수 있다. */
  turnId?: string;
  /** 턴 내 seq — 같은 turnId 안에서는 낮은 seq부터 엄격한 순서로 재생.
   *  중간 seq 가 아직 도착하지 않았으면 도착할 때까지 큐에서 대기. */
  seq?: number;
}

export class AudioManager {
  private audioContext: AudioContext | null = null;
  private gainNode: GainNode | null = null;
  private analyser: AnalyserNode | null = null;
  private onAmplitudeChange: ((amplitude: number) => void) | null = null;
  private animFrameId: number | null = null;
  private _volume: number = 0.7;

  // ── 현재 재생 중인 소스 (HTMLAudioElement 또는 AudioBufferSourceNode) ──
  private currentAudio: HTMLAudioElement | null = null;
  private _currentBufferSource: AudioBufferSourceNode | null = null;
  private sourceNode: MediaElementAudioSourceNode | null = null;

  // ── TTS 큐 시스템 ──
  private _queue: TTSQueueItem[] = [];
  private _isProcessingQueue = false;
  private _currentOnEnd: (() => void) | null = null;
  /** 현재 재생 중인 클립이 속한 turnId — overlap 방지 로직에서 사용 */
  private _currentTurnId: string | null = null;
  /** 턴별로 "다음에 재생해야 할 seq" 를 추적하여 strict ordering 보장.
   *  같은 turnId 안에서 중간 seq 가 아직 도착하지 않았으면 큐를
   *  건너뛰지 않고 대기한다. */
  private _nextSeqByTurn: Map<string, number> = new Map();
  /** 만료된 (이미 clearTurn 된) 턴 ID — 혹시 나중에 도착하는 지연
   *  enqueue 를 조용히 버리기 위해 짧게 보관. LRU 크기 제한. */
  private _retiredTurns: string[] = [];
  private static _MAX_RETIRED = 32;

  /** 턴 도착 순서 ordinal — registerTurnStart 가 부여. 큐 정렬 시
   *  "더 오래된 턴 의 클립이 더 새로운 턴 의 클립보다 먼저 재생되어야"
   *  하는 inter-turn FIFO 보장에 사용. 같은 세션의 새 턴이 시작돼도
   *  이전 턴의 늦은 클립이 새 턴 앞으로 끼어들어가야 자연스럽다. */
  private _turnOrdinal: Map<string, number> = new Map();
  private _nextTurnOrdinal = 0;
  /** 턴별 in-flight HTTP 요청 카운터. dispatch 시 +1, 응답이 큐에 들어가
   *  거나 에러 처리되면 -1. 이전 턴의 합성이 아직 진행 중인지 판단해
   *  새 턴 클립의 재생을 막는데 사용한다. */
  private _turnPending: Map<string, number> = new Map();
  /** 턴 finalize (= 더 이상 dispatch 가 추가되지 않음) 가 호출된 turn 들. */
  private _turnFinalized: Set<string> = new Set();

  // ── iOS WebKit user gesture 오디오 언락 ──
  private _gestureListenerAttached = false;

  /**
   * AudioContext 초기화 (사용자 인터랙션 후 호출 필요)
   */
  async init(): Promise<void> {
    if (this.audioContext) return;
    this.audioContext = new AudioContext();

    // Chrome/Safari: AudioContext는 suspended 상태로 시작될 수 있음.
    if (this.audioContext.state === 'suspended') {
      await this.audioContext.resume();
    }

    this.gainNode = this.audioContext.createGain();
    this.gainNode.gain.value = this._volume;
    this.gainNode.connect(this.audioContext.destination);

    this.analyser = this.audioContext.createAnalyser();
    this.analyser.fftSize = 256;
    this.analyser.smoothingTimeConstant = 0.8;
  }

  /**
   * User gesture 핸들러(onClick/onTouchEnd)에서 동기적으로 호출하여
   * AudioContext를 생성하고 resume한다.
   *
   * iOS/iPadOS WebKit은 user gesture의 직접적인 call stack 내에서만
   * AudioContext.resume()이 성공한다. AudioContext가 running이면
   * AudioBufferSourceNode.start()는 gesture 없이도 작동하므로,
   * 이 메서드를 한 번이라도 gesture에서 호출하면 이후 auto-TTS가 가능하다.
   *
   * 추가로, 글로벌 touchend/click 리스너를 등록하여 백그라운드 복귀 후
   * re-suspend되어도 다음 인터랙션에서 자동 resume.
   *
   * Desktop Chrome(Blink)에서는 이미 작동 중이므로 no-op이 된다.
   */
  ensureResumed(): void {
    if (!this.audioContext) {
      this.audioContext = new AudioContext();
      this.gainNode = this.audioContext.createGain();
      this.gainNode.gain.value = this._volume;
      this.gainNode.connect(this.audioContext.destination);
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 256;
      this.analyser.smoothingTimeConstant = 0.8;
    }
    if (this.audioContext.state === 'suspended') {
      this.audioContext.resume();
    }

    // 글로벌 gesture 리스너 등록 — 이후 모든 터치/클릭에서 자동 resume
    this._attachGestureListener();
  }

  /**
   * 페이지의 모든 터치/클릭에서 AudioContext를 자동 resume하는 리스너.
   * iOS는 백그라운드 전환 후 AudioContext를 re-suspend할 수 있으므로,
   * 유저의 모든 인터랙션에서 resume을 시도해야 한다.
   */
  private _attachGestureListener(): void {
    if (this._gestureListenerAttached) return;
    this._gestureListenerAttached = true;

    const handler = () => {
      if (this.audioContext && this.audioContext.state === 'suspended') {
        this.audioContext.resume();
      }
    };

    // touchend가 iOS에서 가장 확실한 gesture 이벤트
    document.addEventListener('touchend', handler, { passive: true });
    document.addEventListener('click', handler);
  }

  /**
   * 새 턴 시작 시 호출 — 첫 번째로 재생할 seq를 명시적으로 등록한다.
   *
   * **왜 필요한가**: enqueue 가 자동으로 nextSeq 를 추적하긴 하지만,
   * "처음 도착한 seq" 를 expected 로 잡기 때문에 seq=1 이 seq=0 보다
   * 먼저 도착하면 seq=1 을 expected 로 인식해 그대로 재생해 버린다.
   * 턴 시작 시점에 expected=startSeq (보통 0) 를 박아두면 seq=1 이
   * 먼저 와도 _waitForSeq 가 seq=0 을 기다리도록 강제할 수 있다.
   */
  registerTurnStart(turnId: string, startSeq = 0): void {
    this._nextSeqByTurn.set(turnId, startSeq);
    // 턴 도착 ordinal 부여 (한 turnId 당 한 번만)
    if (!this._turnOrdinal.has(turnId)) {
      this._turnOrdinal.set(turnId, this._nextTurnOrdinal++);
    }
    // retired 목록에 들어있다면 제거 (재사용 가능)
    const idx = this._retiredTurns.indexOf(turnId);
    if (idx !== -1) this._retiredTurns.splice(idx, 1);
  }

  /**
   * 턴별 in-flight 합성 요청 +1. 새 문장에 대한 HTTP 요청을 시작하기
   * 직전에 호출. 이전 턴이 아직 합성 중인 동안 새 턴 클립이 큐에 먼저
   * 도착해서 잘못 재생되는 것을 막는 inter-turn FIFO 의 핵심 신호.
   */
  noteTurnDispatch(turnId: string): void {
    if (!this._turnOrdinal.has(turnId)) {
      this._turnOrdinal.set(turnId, this._nextTurnOrdinal++);
    }
    this._turnPending.set(turnId, (this._turnPending.get(turnId) ?? 0) + 1);
  }

  /**
   * 턴별 in-flight 합성 요청 -1. HTTP 응답이 도착해서 enqueue 되었거나
   * (성공/실패 무관) fetch 자체가 끝난 시점에 호출.
   */
  noteTurnReceive(turnId: string): void {
    const cur = this._turnPending.get(turnId) ?? 0;
    if (cur <= 1) {
      this._turnPending.delete(turnId);
    } else {
      this._turnPending.set(turnId, cur - 1);
    }
  }

  /**
   * 턴 finalize — 이 턴에 더 이상 새 dispatch 가 없을 것임을 신호.
   * pending=0 이고 큐에 잔여 아이템이 없으면 _processQueue 의 폴링이
   * 즉시 drain 을 감지해 다음 턴으로 진행.
   */
  markTurnFinalized(turnId: string): void {
    this._turnFinalized.add(turnId);
  }

  /** 턴이 drained 인지: finalized AND pending=0 AND 큐 잔여 없음 AND 재생 중 아님. */
  private _isTurnDrained(turnId: string): boolean {
    if (!this._turnFinalized.has(turnId)) return false;
    if ((this._turnPending.get(turnId) ?? 0) > 0) return false;
    if (this._queue.some((q) => q.turnId === turnId)) return false;
    if (this._currentTurnId === turnId) return false;
    return true;
  }

  /**
   * TTS 응답을 큐에 추가. 현재 재생 중이면 대기, 아니면 즉시 재생.
   * 이전 재생을 중단하지 않고 순차적으로 재생한다.
   *
   * ``opts.turnId`` / ``opts.seq`` 를 지정하면 같은 턴 안에서 strict
   * 순서로 재생된다. 중간 seq 가 아직 도착하지 않았으면 뒤따라 온
   * 높은 seq 가 있어도 대기한다.
   *
   * **중요**: strict ordering 이 필요하면 턴 시작 시점에
   * ``registerTurnStart(turnId, 0)`` 을 먼저 불러야 첫 enqueue 가
   * 잘못된 seq (예: 1 이 0 보다 먼저 도착) 로 expected 를 잠그지 않는다.
   */
  async enqueue(
    response: Response,
    sessionId: string,
    onStart?: () => void,
    onEnd?: () => void,
    opts?: EnqueueOptions,
  ): Promise<void> {
    const turnId = opts?.turnId;
    const seq = opts?.seq;

    // 이미 폐기된 턴의 지연 클립은 조용히 무시 (네트워크로 뒤늦게 도착한 경우)
    if (turnId && this._retiredTurns.includes(turnId)) {
      return;
    }

    const item: TTSQueueItem = {
      response,
      sessionId,
      onStart,
      onEnd,
      turnId,
      seq,
    };

    // 같은 턴에서 seq 가 지정된 경우 순서 유지를 위해 정렬 삽입.
    // **inter-turn FIFO**: 더 오래된 turn (작은 ordinal) 의 클립은
    // 새로운 turn 의 클립보다 항상 앞에 와야 한다. 그렇지 않으면
    // chat0 의 늦게 도착한 seq=2 가 이미 큐에 있는 chat1:seq=0 뒤로
    // 붙어서 [chat0:0, chat0:1, chat1:0, chat0:2] 같은 뒤섞임 발생.
    if (turnId && typeof seq === 'number') {
      // ordinal 미등록 (registerTurnStart 미호출) 인 경우 즉시 부여
      if (!this._turnOrdinal.has(turnId)) {
        this._turnOrdinal.set(turnId, this._nextTurnOrdinal++);
      }
      const myOrd = this._turnOrdinal.get(turnId)!;

      let inserted = false;
      for (let i = 0; i < this._queue.length; i += 1) {
        const q = this._queue[i];
        const qOrd = q.turnId ? this._turnOrdinal.get(q.turnId) ?? Infinity : Infinity;
        const isLaterTurn = qOrd > myOrd;
        const isSameTurnLaterSeq =
          q.turnId === turnId && typeof q.seq === 'number' && q.seq > seq;
        if (isLaterTurn || isSameTurnLaterSeq) {
          this._queue.splice(i, 0, item);
          // 정렬 삽입 시 이후 아이템의 pre-fetch 예약을 무효화
          q._prefetchPromise = undefined;
          inserted = true;
          break;
        }
      }
      if (!inserted) this._queue.push(item);
      // nextSeq 가 아직 등록되지 않았다면 (registerTurnStart 미호출 케이스)
      // 도착한 seq 중 가장 작은 값으로 fallback. 이 경로는 strict ordering
      // 보장이 깨질 수 있으므로 호출자가 registerTurnStart 를 부르는 게 정석.
      if (!this._nextSeqByTurn.has(turnId)) {
        this._nextSeqByTurn.set(turnId, seq);
      }
    } else {
      this._queue.push(item);
    }

    if (!this._isProcessingQueue) {
      await this._processQueue();
    }
  }

  /**
   * 특정 턴의 **대기 중** 클립을 모두 버린다. 이미 재생 중인 클립은
   * 계속 재생되도록 유지 (또는 ``stopCurrent=true`` 로 강제 중단).
   *
   * 새 유저 메시지가 들어와서 AI 턴이 바뀐 경우 호출.
   */
  clearTurn(turnId: string, stopCurrent = false): void {
    const before = this._queue.length;
    this._queue = this._queue.filter((q) => q.turnId !== turnId);
    this._nextSeqByTurn.delete(turnId);

    // retired 목록 업데이트 (LRU)
    if (!this._retiredTurns.includes(turnId)) {
      this._retiredTurns.push(turnId);
      if (this._retiredTurns.length > AudioManager._MAX_RETIRED) {
        this._retiredTurns.shift();
      }
    }

    const dropped = before - this._queue.length;
    if (dropped > 0) {
      console.log(`[AudioManager] clearTurn(${turnId}): dropped ${dropped} queued clip(s)`);
    }

    if (stopCurrent && this._currentTurnId === turnId) {
      this._stopCurrentOnly();
    }
  }

  /**
   * 큐에 쌓인 모든 TTS 아이템을 순차 재생.
   * Pre-fetch: 현재 아이템 재생 중 다음 아이템의 Blob을 미리 준비하여
   * 연속 재생 시 체감 지연 최소화.
   */
  private async _processQueue(): Promise<void> {
    if (this._isProcessingQueue) return;
    this._isProcessingQueue = true;

    try {
      while (this._queue.length > 0) {
        // Strict seq ordering: 맨 앞 아이템이 턴의 nextSeq 와 맞지 않으면
        // 아직 비는 seq 가 도착할 때까지 잠시 대기 (최대 2초).
        const head = this._queue[0];

        // ── Inter-turn FIFO ───────────────────────────────────────
        // head 가 어느 턴이든, 이 턴보다 ordinal 이 작은 (= 더 오래된)
        // 활성 턴이 있으면 그 턴이 drain 될 때까지 기다린다. 이렇게 해야
        // chat0 가 아직 합성 중일 때 chat1:seq=0 이 먼저 도착해서 큐
        // 맨 앞에 있더라도 chat0 의 모든 클립이 끝난 뒤에 chat1 을 재생.
        if (head.turnId) {
          const headOrd = this._turnOrdinal.get(head.turnId);
          if (typeof headOrd === 'number') {
            let blockingTurn: string | null = null;
            for (const [tid, ord] of this._turnOrdinal) {
              if (ord >= headOrd) continue;
              if (this._isTurnDrained(tid)) continue;
              blockingTurn = tid;
              break;
            }
            if (blockingTurn) {
              // 폴링: 50ms 간격으로 (a) blockingTurn 의 새 클립이 큐
              // 맨앞에 끼어들어왔는지, (b) blockingTurn 이 drain 됐는지,
              // (c) head 자체가 바뀌었는지 — 셋 중 하나라도 맞으면 즉시 빠져나감.
              // 60초 timeout 안에 아무 일도 없으면 강제로 blocker 를 drain
              // 처리해서 진행한다 (백엔드 실종 등 이상 상황 방어).
              const deadline = Date.now() + 60000;
              let progressed = false;
              while (Date.now() < deadline) {
                const newHead = this._queue[0];
                if (newHead !== head) { progressed = true; break; }
                if (this._isTurnDrained(blockingTurn)) { progressed = true; break; }
                await new Promise((r) => setTimeout(r, 50));
              }
              if (!progressed) {
                console.warn(
                  `[AudioManager] inter-turn drain timeout: blocking=${blockingTurn}, advancing to head=${head.turnId}:${head.seq}`,
                );
                this._turnPending.delete(blockingTurn);
                this._turnFinalized.add(blockingTurn);
              }
              continue; // queue head 재평가
            }
          }
        }

        if (head.turnId && typeof head.seq === 'number') {
          const expected = this._nextSeqByTurn.get(head.turnId);
          if (expected !== undefined && head.seq > expected) {
            // 비는 seq 있음 — 합성이 아직 진행 중이거나 곧 dispatch 될 가능성이
            // 있으면 무조건 기다린다. "in-flight 가 있는데 2초 안에 안 오면 건너
            // 뛴다" 는 종전 로직은 GPU 큐가 막혔을 때 (parallel 8 dispatch 등)
            // 영구적으로 순서를 깨트렸다.
            //
            // _turnPending / _turnFinalized 를 사용해 "정말로 안 올 것" 인지
            // 정확히 판정한다. Hard ceiling (120s) 은 백엔드 실종 등 이상
            // 상황 방어용.
            const waited = await this._waitForSeq(head.turnId, expected, 120_000);
            if (!waited) {
              console.warn(
                `[AudioManager] seq gap permanent: turn=${head.turnId} expected=${expected} head=${head.seq}, skipping gap`,
              );
              this._nextSeqByTurn.set(head.turnId, head.seq);
            }
            continue;
          }
        }

        const item = this._queue.shift()!;
        if (item.turnId && typeof item.seq === 'number') {
          this._nextSeqByTurn.set(item.turnId, item.seq + 1);
        }
        this._currentTurnId = item.turnId ?? null;

        // Pre-fetch: 다음 아이템이 있으면 Blob 준비를 미리 시작
        if (this._queue.length > 0 && !this._queue[0]._prefetchPromise) {
          const next = this._queue[0];
          next._prefetchPromise = this._fetchBlob(next.response, next.sessionId);
        }

        await this._playOne(item);

        if (item.turnId) {
          this._currentTurnId = null;
        }
      }
    } finally {
      this._isProcessingQueue = false;
    }
  }

  /**
   * Response body를 Blob으로 변환 (pre-fetch용 분리).
   *
   * response.blob()을 사용하여 iOS WebKit 호환성을 확보한다.
   * (ReadableStream.getReader()는 iOS WebKit에서 streaming response에 불안정)
   */
  private async _fetchBlob(response: Response, sessionId: string): Promise<Blob | null> {
    if (!response.ok) return null;
    try {
      const blob = await response.blob();
      if (blob.size === 0) return null;
      console.info(`[AudioManager] prefetch ready: ${blob.size} bytes, session=${sessionId.slice(0, 8)}`);
      return blob;
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return null;
      console.error('[AudioManager] prefetch error:', err);
      return null;
    }
  }

  /**
   * 단일 TTS 응답 재생 (내부용).
   * Pre-fetch된 Blob이 있으면 즉시 사용, 없으면 직접 fetch.
   * 재생이 완료되거나 에러가 발생하면 resolve.
   */
  private async _playOne(item: TTSQueueItem): Promise<void> {
    await this.init();

    // 이전 재생 중지 (큐 처리 중이므로 이전 아이템이 끝났어야 하지만 안전장치)
    this._stopCurrent();

    // AudioContext가 suspended면 재생 전에 반드시 resume
    if (this.audioContext?.state === 'suspended') {
      await this.audioContext.resume();
    }

    try {
      // Pre-fetch된 Blob이 있으면 사용, 없으면 직접 fetch
      let blob: Blob | null = null;
      if (item._prefetchPromise) {
        blob = await item._prefetchPromise;
      } else {
        blob = await this._fetchBlob(item.response, item.sessionId);
      }

      if (!blob) {
        console.error('[AudioManager] TTS returned no audio');
        item.onEnd?.();
        return;
      }

      console.info(`[AudioManager] playing: ${blob.size} bytes, session=${item.sessionId.slice(0, 8)}`);
      await this._playBlob(blob, item.onStart, item.onEnd);
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        console.info('[AudioManager] TTS fetch aborted (queue cleared)');
      } else {
        console.error('[AudioManager] TTS playback error:', err);
      }
      item.onEnd?.();
    }
  }

  /**
   * Blob을 재생하고, 완료 시 resolve.
   *
   * 1차: AudioContext.decodeAudioData + AudioBufferSourceNode (iOS 호환)
   *      → AudioContext가 running이면 gesture 없이도 재생 가능.
   * 2차: HTMLAudioElement fallback (AudioContext 사용 불가 시)
   */
  private async _playBlob(
    blob: Blob,
    onStart?: () => void,
    onEnd?: () => void,
  ): Promise<void> {
    // AudioContext가 running이면 decodeAudioData 경로 사용 (iOS 호환)
    if (this.audioContext && this.audioContext.state === 'running' && this.gainNode) {
      try {
        return await this._playViaWebAudio(blob, onStart, onEnd);
      } catch (err) {
        console.warn('[AudioManager] Web Audio playback failed, falling back to HTMLAudioElement:', err);
      }
    }

    // Fallback: HTMLAudioElement (Desktop에서 AudioContext 없을 때)
    return this._playViaAudioElement(blob, onStart, onEnd);
  }

  /**
   * Web Audio API 경로: decodeAudioData + AudioBufferSourceNode.
   * AudioContext가 running이면 user gesture 없이도 재생 가능.
   * 립싱크용 AnalyserNode도 연결된다.
   */
  private async _playViaWebAudio(
    blob: Blob,
    onStart?: () => void,
    onEnd?: () => void,
  ): Promise<void> {
    const arrayBuffer = await blob.arrayBuffer();
    const audioBuffer = await this.audioContext!.decodeAudioData(arrayBuffer);

    return new Promise<void>((resolve) => {
      const source = this.audioContext!.createBufferSource();
      source.buffer = audioBuffer;
      this._currentBufferSource = source;
      this._currentOnEnd = onEnd ?? null;

      // source → analyser → gain → destination
      if (this.analyser && this.gainNode) {
        source.connect(this.analyser);
        this.analyser.connect(this.gainNode);
      } else {
        source.connect(this.audioContext!.destination);
      }

      this.startAmplitudeTracking();

      source.onended = () => {
        console.info('[AudioManager] playback ended (WebAudio)');
        this.stopAmplitudeTracking();
        if (this._currentBufferSource === source) {
          this._currentBufferSource = null;
          this._currentOnEnd = null;
        }
        try { source.disconnect(); } catch { /* already disconnected */ }
        onEnd?.();
        resolve();
      };

      source.start(0);
      console.info('[AudioManager] playback started (WebAudio)');
      onStart?.();
    });
  }

  /**
   * HTMLAudioElement 경로 (fallback).
   * AudioContext가 사용 불가할 때만 사용.
   */
  private _playViaAudioElement(
    blob: Blob,
    onStart?: () => void,
    onEnd?: () => void,
  ): Promise<void> {
    return new Promise<void>((resolve) => {
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      this.currentAudio = audio;
      this._currentOnEnd = onEnd ?? null;
      audio.volume = this._volume;

      const cleanup = () => {
        URL.revokeObjectURL(url);
        if (this.currentAudio === audio) {
          this.currentAudio = null;
          this._currentOnEnd = null;
        }
      };

      audio.onplay = () => {
        console.info('[AudioManager] playback started (AudioElement)');
        onStart?.();
      };

      audio.onended = () => {
        console.info('[AudioManager] playback ended (AudioElement)');
        cleanup();
        onEnd?.();
        resolve();
      };

      audio.onerror = () => {
        const err = audio.error;
        console.error('[AudioManager] audio error:', err?.code, err?.message);
        cleanup();
        onEnd?.();
        resolve();
      };

      audio.play().catch((playErr) => {
        console.error('[AudioManager] audio.play() rejected:', playErr);
        cleanup();
        onEnd?.();
        resolve();
      });
    });
  }

  /**
   * TTS 스트리밍 오디오 재생 (하위 호환성 유지).
   * 내부적으로 enqueue를 사용하므로 큐에 추가된다.
   */
  async playTTSResponse(
    response: Response,
    onStart?: () => void,
    onEnd?: () => void,
  ): Promise<void> {
    await this.enqueue(response, '', onStart, onEnd);
  }

  /**
   * 진폭 추적 시작 (립싱크용)
   */
  private startAmplitudeTracking(): void {
    if (!this.analyser) return;
    const dataArray = new Uint8Array(this.analyser.frequencyBinCount);

    const track = () => {
      this.analyser!.getByteFrequencyData(dataArray);

      // RMS 계산
      let sum = 0;
      for (let i = 0; i < dataArray.length; i++) {
        sum += (dataArray[i] / 255) ** 2;
      }
      const rms = Math.sqrt(sum / dataArray.length);

      this.onAmplitudeChange?.(rms);
      this.animFrameId = requestAnimationFrame(track);
    };

    this.animFrameId = requestAnimationFrame(track);
  }

  /**
   * 진폭 추적 중지
   */
  private stopAmplitudeTracking(): void {
    if (this.animFrameId) {
      cancelAnimationFrame(this.animFrameId);
      this.animFrameId = null;
    }
    this.onAmplitudeChange?.(0); // 입 닫기
  }

  /** 립싱크 콜백 등록 */
  setAmplitudeCallback(cb: (amplitude: number) => void): void {
    this.onAmplitudeChange = cb;
  }

  /** 볼륨 설정 (0~1) */
  setVolume(vol: number): void {
    this._volume = Math.max(0, Math.min(1, vol));
    if (this.gainNode) {
      this.gainNode.gain.value = this._volume;
    }
  }

  /** 현재 볼륨 */
  get volume(): number {
    return this._volume;
  }

  /** AudioContext 접근 (Enhanced LipSync 초기화용) */
  getAudioContext(): AudioContext | null {
    return this.audioContext;
  }

  /**
   * 현재 재생만 중지 (큐의 다음 아이템은 유지).
   * onEnd 콜백을 반드시 호출하여 ttsSpeaking 상태를 정리.
   */
  private _stopCurrent(): void {
    this.stopAmplitudeTracking();
    const pendingOnEnd = this._currentOnEnd;
    this._currentOnEnd = null;

    // AudioBufferSourceNode 정지
    if (this._currentBufferSource) {
      try {
        this._currentBufferSource.onended = null;
        this._currentBufferSource.stop();
        this._currentBufferSource.disconnect();
      } catch { /* already stopped/disconnected */ }
      this._currentBufferSource = null;
    }

    // HTMLAudioElement 정지
    if (this.currentAudio) {
      this.currentAudio.onended = null;
      this.currentAudio.onerror = null;
      this.currentAudio.onplay = null;
      this.currentAudio.pause();
      this.currentAudio.src = '';
      this.currentAudio = null;
    }
    if (this.sourceNode) {
      try { this.sourceNode.disconnect(); } catch { /* already disconnected */ }
      this.sourceNode = null;
    }

    this._currentTurnId = null;

    // onEnd 콜백을 반드시 호출하여 외부 상태(ttsSpeaking 등)를 정리
    pendingOnEnd?.();
  }

  /** ``clearTurn(stopCurrent=true)`` 용 내부 별칭. */
  private _stopCurrentOnly(): void {
    this._stopCurrent();
  }

  /**
   * 같은 턴의 다음 기대 seq 가 도착할 때까지 대기 (poll 방식, 25ms 간격).
   *
   * **종료 조건** (둘 중 하나):
   *  1. 성공 (`true` 반환):
   *     - 큐 head 가 바뀌었거나 (= 비는 seq 가 enqueue 되어 정렬 삽입됨)
   *     - 큐 head 가 다른 턴으로 바뀜
   *     - 턴이 retired
   *  2. 실패 (`false` 반환) — gap skip 유도:
   *     - **턴이 finalized AND in-flight HTTP 가 0** → 빠진 seq 의 합성
   *       자체가 실패했거나 영영 안 올 것이 확실. 즉시 skip.
   *     - hardDeadlineMs 를 초과 → 백엔드 실종 등 이상 상황 방어.
   *
   * **왜 hardDeadline 을 길게 (120s) 잡는가**: parallel 8-dispatch 시
   * GPU 큐 적체로 한 클립 합성이 10초를 넘는 것은 정상 범위. 이전 2 초
   * 타임아웃은 무조건 gap skip 을 유발해 순서를 영구히 깨트렸다.
   * pending+finalized 신호로 정확히 판정하므로 hardDeadline 은 실제로는
   * 거의 도달하지 않는 안전망이다.
   */
  private async _waitForSeq(turnId: string, expected: number, hardDeadlineMs: number): Promise<boolean> {
    const deadline = Date.now() + hardDeadlineMs;
    while (Date.now() < deadline) {
      // 큐의 맨 앞 아이템이 바뀌었으면 즉시 빠져나감 (재평가)
      const head = this._queue[0];
      if (!head || head.turnId !== turnId) return true;
      if (typeof head.seq !== 'number' || head.seq <= expected) return true;
      // 폐기된 턴이면 더 기다릴 필요 없음
      if (this._retiredTurns.includes(turnId)) return true;
      // **핵심**: 더 이상 합성이 진행 중이지 않고 finalize 됐는데도
      // expected 가 안 왔다면 — 이 seq 는 영영 안 옴. 즉시 skip.
      const pending = this._turnPending.get(turnId) ?? 0;
      const finalized = this._turnFinalized.has(turnId);
      if (finalized && pending === 0) {
        return false;
      }
      await new Promise((r) => setTimeout(r, 25));
    }
    return false;
  }

  /**
   * 현재 재생 중지 (공개 API).
   * 큐는 유지됨. 큐까지 비우려면 clearQueue() 사용.
   */
  stop(): void {
    this._stopCurrent();
  }

  /**
   * 큐의 모든 대기 아이템을 비우고, 현재 재생도 중지.
   * 각 대기 아이템의 onEnd를 호출하여 상태 정리.
   */
  clearQueue(): void {
    // 대기 중인 아이템들의 onEnd 콜백 호출
    const pendingItems = this._queue.splice(0);
    for (const item of pendingItems) {
      item.onEnd?.();
    }
    // 현재 재생 중지
    this._stopCurrent();
    this._isProcessingQueue = false;
  }

  /** 큐에 대기 중인 아이템 수 */
  get queueLength(): number {
    return this._queue.length;
  }

  /** 재생 중 여부 */
  get isPlaying(): boolean {
    return this._currentBufferSource !== null || (this.currentAudio !== null && !this.currentAudio.paused);
  }

  /** 정리 */
  dispose(): void {
    this.clearQueue();
    this.audioContext?.close();
    this.audioContext = null;
  }
}

// 싱글턴
let _audioManager: AudioManager | null = null;
export function getAudioManager(): AudioManager {
  if (!_audioManager) {
    _audioManager = new AudioManager();
  }
  return _audioManager;
}
