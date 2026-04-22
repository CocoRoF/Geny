# streaming.md — 문장 스트리밍 큐 상세 설계

> [index.md §4](index.md#4-문장-스트리밍-큐-아키텍처-요약) 와 [plan.md Phase 4](plan.md#phase-4--문장-스트리밍-큐-pr-4) 의 내부 동작 명세.

---

## 1. 데이터 플로우 (책임 경계 명시)

```
LLM (workflow_engine, claude_manager 등)
        │ SSE token stream  (이미 존재)
        ▼
WebSocket  ws/agent_session_ws.py  ──▶  status updates per session
        │
        ▼
Frontend  VTuberChatPanel.tsx
        │  agent.streaming_text 누적 변화 감지
        ▼
SentenceAccumulator  (frontend/src/lib/sentenceSplitter.ts)  ── 분할만 ──▶  ['문장1.', '문장2!', ...]
        │  for each finished sentence
        ▼
useVTuberStore.speakSentence(sessionId, text, seq, isLast)
        │  fetch POST /api/tts/agents/{sid}/speak/sentence
        ▼
backend  tts_controller  speak_sentence
        │  ├─ sanitize
        │  ├─ 세션 큐(asyncio.Queue) 에 enqueue + (Future, audio_chan)
        │  └─ StreamingResponse  ◀── audio_chan 에서 chunked yield
        │
        ▼
backend worker (per-session)
        │  큐에서 다음 문장 dequeue
        ▼
TTSService.speak(text=sentence)  ──▶  OmniVoiceEngine
        │
        ▼
omnivoice service  POST /tts (또는 /tts/stream)
```

**핵심.** 분할은 **프론트** 한 곳. 백엔드는 *문장 1건 단위*로만 받음. 백엔드의 세션 큐는 *전송된 문장들의 GPU 직렬화 + 취소* 를 책임.

이유:
- LLM SSE 는 이미 프론트로 흘러가고 있다 (`agent.streaming_text`). 백엔드가 같은 스트림을 fork 해서 한 번 더 분할하면 정보가 두 곳에 흩어진다.
- 사용자가 "이 메시지 다시 읽어줘" 같은 *retroactive* 요청 시에도 동일 분할 함수가 그대로 사용됨 → 분할 로직은 클라이언트 utility 가 자연스럽다.
- 백엔드가 분할에 관여하면 SSE → 분할 → 재SSE 의 *패스스루 레이어*가 생기고, 디버깅 면적이 늘어남.

---

## 2. SentenceAccumulator — 분할 규칙

### 2.1 알고리즘

```ts
// frontend/src/lib/sentenceSplitter.ts
const SENT_END = /[.!?。！？…]/
const COMMA    = /[,，、:;]/
const PROTECT  = [
  /\d+\.\d+/g,                    // 소수점 (3.14)
  /https?:\/\/\S+/g,              // URL
  /`[^`]*`/g,                     // inline code
  /```[\s\S]*?```/g,              // code block
  /[A-Za-z]\.[A-Za-z]\./g,        // 약어 (e.g. U.S.A.)
]

export class SentenceAccumulator {
  private buf = ''
  private masks: Array<[number, number]> = []   // 보호 구간

  push(chunk: string): string[] {
    this.buf += chunk
    return this._extract()
  }

  flush(): string[] {
    const out = this.buf.trim() ? [this.buf.trim()] : []
    this.buf = ''
    return out
  }

  private _extract(): string[] {
    this._recomputeProtects()
    const out: string[] = []
    let lastCut = 0
    for (let i = 0; i < this.buf.length; i++) {
      if (this._isProtected(i)) continue
      const ch = this.buf[i]
      const next = this.buf[i + 1] ?? ''
      const sentenceEnd =
        SENT_END.test(ch) &&
        (next === '' || /\s|["')\]」』]/.test(next))
      if (sentenceEnd) {
        out.push(this.buf.slice(lastCut, i + 1).trim())
        lastCut = i + 1
        continue
      }
      // 길이 안전판: 80자 누적 + comma
      if (i - lastCut >= 80 && COMMA.test(ch)) {
        out.push(this.buf.slice(lastCut, i + 1).trim())
        lastCut = i + 1
      }
    }
    this.buf = this.buf.slice(lastCut)
    return out.filter(s => s.length > 0)
  }

  // ... _recomputeProtects, _isProtected 생략
}
```

### 2.2 테스트 케이스 (sentenceSplitter.test.ts)

| # | 입력 (점진 push) | 기대 출력 |
|---|-----------------|-----------|
| 1 | `"안녕"`, `"하세요. 반갑"`, `"습니다!"` | `['안녕하세요.', '반갑습니다!']` |
| 2 | `"3.14는 원주율"`, `"입니다."` | `['3.14는 원주율입니다.']` (소수점 보호) |
| 3 | `"방문 https://e"`, `"xample.com 하세요."` | `['방문 https://example.com 하세요.']` |
| 4 | `'"좋아요." 하고 답"`, ``'했다.'` | `['"좋아요." 하고 답했다.']` (인용 부호 다음 공백 없음 → 분할 X) |
| 5 | 80자 초과 + 쉼표 | comma 에서 강제 분할 |
| 6 | 빈 chunk 반복 | `[]` |
| 7 | 코드블록 ```python\nprint("a.")\n``` | 코드블록 통째로 1 문장 |
| ... | (총 30 케이스) | |

---

## 3. 프론트 호출 시퀀스

```ts
// VTuberChatPanel.tsx 내부 SSE 처리
const acc = sentenceAccumulators.current[sessionId] ??= new SentenceAccumulator()
let seq = sentenceSeqs.current[sessionId] ??= 0

if (agent.status === 'executing' && agent.streaming_text) {
  const newPortion = agent.streaming_text.slice(prevLen)
  for (const sent of acc.push(newPortion)) {
    if (useVTuberStore.getState().ttsStreamingEnabled) {
      useVTuberStore.getState().speakSentence(sessionId, sent, seq++, false)
    }
  }
}

if (agent.status === 'completed') {
  for (const sent of acc.flush()) {
    if (useVTuberStore.getState().ttsStreamingEnabled) {
      useVTuberStore.getState().speakSentence(sessionId, sent, seq++, true)
    }
  }
  // 마지막 문장에 isLast=true 만 보내고 싶으면, flush() 결과의 마지막 요소만 isLast 처리
  sentenceSeqs.current[sessionId] = 0
}
```

**유저 새 입력 도착 시.** `clearQueue()` + 백엔드 `DELETE /api/tts/agents/{sid}/queue` (신규 엔드포인트, 4b 에 추가) 호출 → 진행중 합성 cancel + 큐 비우기.

---

## 4. audioManager seq 보강

[`audioManager.ts`](../../frontend/src/lib/audioManager.ts) 의 `TTSQueueItem` 에 `seq?: number` 추가.

```ts
async enqueue(response, sessionId, { seq, onStart, onEnd } = {}) {
  this._queue.push({ response, sessionId, seq, onStart, onEnd })
  this._queue.sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0))
  // 단, 이미 _isProcessingQueue 중이면 현재 재생 중 항목은 보존
  if (!this._isProcessingQueue) await this._processQueue()
}
```

도착 순서가 어긋난 경우 (예: seq=3 이 seq=2 보다 먼저 도착) — sort 가 순서를 복구. 단 *재생 중인 항목보다 작은 seq* 가 늦게 도착하면 무시 (이미 늦었음). 이 정책은 단위 테스트로 명시.

---

## 5. 백엔드 세션 큐

### 5.1 자료구조

```python
# backend/service/vtuber/tts/job_queue.py
@dataclass
class TTSJob:
    seq: int
    text: str
    emotion: str
    language: str | None
    voice_profile: str | None
    out_chan: asyncio.Queue[bytes | None]   # None = EOF
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)

class TTSJobQueue:
    def __init__(self, tts_service):
        self._tts = tts_service
        self._sessions: dict[str, asyncio.Queue[TTSJob]] = {}
        self._workers: dict[str, asyncio.Task] = {}

    def enqueue(self, session_id: str, job: TTSJob) -> None:
        q = self._sessions.setdefault(session_id, asyncio.Queue())
        q.put_nowait(job)
        if session_id not in self._workers or self._workers[session_id].done():
            self._workers[session_id] = asyncio.create_task(self._worker(session_id))

    async def cancel_session(self, session_id: str) -> int:
        q = self._sessions.get(session_id)
        if not q: return 0
        dropped = 0
        while not q.empty():
            job = q.get_nowait()
            job.cancelled.set()
            await job.out_chan.put(None)
            dropped += 1
        # 진행 중 작업도 cancel 신호
        worker = self._workers.get(session_id)
        if worker and not worker.done():
            worker.cancel()
        return dropped

    async def _worker(self, session_id: str):
        q = self._sessions[session_id]
        while True:
            try:
                job = await asyncio.wait_for(q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                return  # idle 종료
            if job.cancelled.is_set():
                continue
            try:
                async for chunk in self._tts.speak(
                    text=job.text, emotion=job.emotion,
                    language=job.language, voice_profile=job.voice_profile,
                ):
                    if job.cancelled.is_set(): break
                    await job.out_chan.put(chunk.audio_data)
            except Exception:
                logger.exception("TTSJobQueue worker failed seq=%d", job.seq)
            finally:
                await job.out_chan.put(None)
```

### 5.2 컨트롤러

```python
# backend/controller/tts_controller.py 신규 엔드포인트
@router.post("/agents/{session_id}/speak/sentence")
async def speak_sentence(session_id: str, body: SpeakSentenceRequest):
    cleaned = sanitize_tts_text(body.text)
    if not cleaned:
        return JSONResponse(status_code=204, content={})

    job = TTSJob(
        seq=body.seq, text=cleaned, emotion=body.emotion or "neutral",
        language=body.language, voice_profile=...,
        out_chan=asyncio.Queue(maxsize=64),
    )
    get_tts_job_queue().enqueue(session_id, job)

    async def stream():
        while True:
            chunk = await job.out_chan.get()
            if chunk is None: break
            yield chunk
    return StreamingResponse(stream(), media_type=...)


@router.delete("/agents/{session_id}/queue")
async def cancel_queue(session_id: str):
    n = await get_tts_job_queue().cancel_session(session_id)
    return {"cancelled": n}
```

### 5.3 chat WS 와의 hook

`Geny/backend/ws/agent_session_ws.py` (또는 동등 위치) 에서 *유저 새 입력 도착 시* `get_tts_job_queue().cancel_session(session_id)` 호출. 이로써 프론트의 명시적 DELETE 호출이 누락되어도 백엔드가 정리.

---

## 6. omnivoice 서버 chunked transfer (4a)

OmniVoice 의 `model.generate()` 가 list[ndarray] 를 반환하는 동기 호출이라 진정한 *모델-내부 streaming* 은 어려움. 따라서 1차 구현은 **server 단 문장 분할 + 청크별 yield**.

```python
# server/api.py
@router.post("/tts/stream")
async def tts_stream(req: TTSRequest, request: Request):
    # 클라이언트 disconnect 감지 위해 background task
    sentences = split_into_sentences(req.text, req.language)

    async def gen():
        yield wav_header_bytes(sample_rate=req.sample_rate)
        for sent in sentences:
            if await request.is_disconnected():
                return
            audio = await engine.synthesize(text=sent, ...)
            for chunk in slice_pcm(audio, frame_ms=100):
                yield chunk

    return StreamingResponse(gen(), media_type="audio/wav")
```

**한계.** 어차피 *문장 1건* 의 합성 자체는 한 덩어리. 문장 단위 streaming 은 backend 의 sentence-queue 가 담당. 따라서 omnivoice 서버의 `/tts/stream` 은 옵션. 1차에서는 backend 가 매 문장마다 `/tts` 를 호출하는 단순 패턴 사용.

→ **결정.** Phase 4a 는 *옵션*. Phase 4b/4c 가 핵심. 4a 는 multi-sentence 단일 호출 use-case (예: "전체 텍스트를 한 번에 보내고 청크별로 받기") 가 필요할 때 진행.

---

## 7. 백프레셔 / 흐름 제어

- omnivoice GPU 가 직렬이므로 `Semaphore(1)` 가 자연스러운 backpressure.
- backend 큐는 maxsize 미설정 (LLM 토큰 yield 속도가 사람 청취 속도보다 느려 자연 균형).
- 프론트 audioManager 큐도 maxsize 없음. 단 *재생되지 않은 채 누적된 항목 ≥ 5* 면 콘솔 warning.
- 클라이언트 fetch 의 `body` 는 작음 (한 문장, 수십~수백 byte) → HTTP keepalive 충분.

---

## 8. 취소 시나리오 매트릭스

| 트리거 | 영향 범위 | 동작 |
|--------|-----------|------|
| 유저가 채팅창에 새 메시지 입력 | 세션 단위 | `cancel_session(sid)` + 프론트 `clearQueue()` |
| 유저가 stop 버튼 클릭 | 세션 단위 | 동일 |
| 세션 변경 (탭 전환) | 세션 단위 | 위와 동일, 추가로 audioManager pause |
| 컨테이너 omnivoice 재시작 | 전역 | 진행중 fetch 가 EOF → audioManager 다음 항목으로 이동, fallback 트리거 |
| LLM 응답이 에러로 종료 | 세션 단위 | flush() 미호출 → 대신 `cancel_session(sid)` |

---

## 9. 관측 (logs / metrics)

backend `TTSJobQueue` INFO 로그 형식:

```
[tts.queue] enqueue session=<sid> seq=3 text_len=42 queue_depth=2
[tts.queue] start    session=<sid> seq=3
[tts.queue] done     session=<sid> seq=3 wall_ms=820 audio_ms=2400 rtf=0.34
[tts.queue] cancel   session=<sid> dropped=1
```

omnivoice 서버 `/tts` 응답 후 INFO:

```
[tts] synth voice=paimon_ko lang=ko text_len=42 num_step=24 cfg=2.0
       audio_dur=2.40s wall=0.82s rtf=0.34 gpu_peak_mb=4231
```

이 로그 라인을 [benchmarks.md](benchmarks.md) 에서 정규식으로 파싱하여 누적 표 갱신.
