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
   * TTS 응답을 큐에 추가. 현재 재생 중이면 대기, 아니면 즉시 재생.
   * 이전 재생을 중단하지 않고 순차적으로 재생한다.
   */
  async enqueue(
    response: Response,
    sessionId: string,
    onStart?: () => void,
    onEnd?: () => void,
  ): Promise<void> {
    this._queue.push({ response, sessionId, onStart, onEnd });
    if (!this._isProcessingQueue) {
      await this._processQueue();
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
        const item = this._queue.shift()!;

        // Pre-fetch: 다음 아이템이 있으면 Blob 준비를 미리 시작
        if (this._queue.length > 0 && !this._queue[0]._prefetchPromise) {
          const next = this._queue[0];
          next._prefetchPromise = this._fetchBlob(next.response, next.sessionId);
        }

        await this._playOne(item);
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

    // onEnd 콜백을 반드시 호출하여 외부 상태(ttsSpeaking 등)를 정리
    pendingOnEnd?.();
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
