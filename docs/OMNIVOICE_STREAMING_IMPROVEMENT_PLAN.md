# OmniVoice × Geny TTS 스트리밍 심층 분석 및 완벽 개선 계획

> 작성일: 2026-04-23
> 대상: Geny 백엔드 TTS 파이프라인 · OmniVoice 합성 서버 · VTuber 프런트엔드 오디오 큐
> 핵심 질문: **왜 "streaming"이 활성화되어 있는데도 단일 요청보다 체감상 더 느린가?**

---

## 1. 한 줄 요약 (TL;DR)

현재 구조는 이름만 스트리밍이며, **"하나의 전체 텍스트 → 서버가 문장 분할 → GPU 세마포어(max=1) 위에서 `for` 루프로 순차 합성"** 이다.
따라서:

1. **첫 문장이 끝나기 전까지 첫 오디오가 나오지 않는다** — "첫 문장 조기 송출"이라는 스트리밍의 유일한 이점이 문장 분할 오버헤드로 상쇄된다.
2. **두 번째 문장 이후는 항상 첫 문장 + 두 번째 문장 연속 합성 시간이 드는데**, 세마포어가 `1`이라 동시 실행이 원천 차단되어 있다.
3. **프런트엔드는 에이전트 턴이 끝난 뒤에야 TTS를 호출**한다. 즉 "chat-stream 도중에 chunk 단위로 TTS로 넘겨주는" 경로가 **아예 존재하지 않는다**.

결과: 짧은 단일 문장(80자 미만, `single` 경로)은 setup 오버헤드가 없어 빠른데, **긴 발화(`always` 모드)는 스트리밍의 체감 이득 < 문장 분할/세마포어 직렬화 오버헤드** 가 되어 오히려 느려 보이는 현상이 발생한다.

---

## 2. 현재 데이터 흐름 (End-to-End)

```
┌─────────────────────── Agent Turn ──────────────────────┐
│                                                          │
│   LangGraph 스트리밍 토큰 → agent_progress(streaming_text)│ ── UI 표시 전용 (TTS 미사용)
│                                                          │
│   턴 종료 → agent_message(full_text)                     │ ── ★ 여기서 처음으로 TTS 트리거
└──────────────────────────┬───────────────────────────────┘
                           │  (VTuberChatPanel.tsx:240)
                           ▼
            speakResponse(sessionId, fullText, emotion)
            (useVTuberStore.ts:252)
                           │
                           ▼
      POST /api/tts/agents/{sid}/speak/stream   (전체 text)
      (tts_controller.py:168)
                           │
                           ▼
       TTSService.speak_sentences(text=full_text)
       (tts_service.py:182)
                           │
                           ▼
   OmniVoiceEngine.synthesize_sentence_stream(request)
   (omnivoice_engine.py:230)   ──  payload["text"] = full_text
                           │
                           ▼
         POST  OmniVoice  /tts/stream   (NDJSON)
         (omnivoice/server/api.py:152)
                           │
                           ▼
      sentences = split_sentences(req.text)   ← 서버 측 분할
                           │
                           ▼
       for seq, sentence in enumerate(sentences):    ← ★ 순차 for 루프
           async with state.semaphore:                ← ★ Semaphore(1) 직렬화
               audio = await engine.synthesize(s)     ← run_in_executor
           yield NDJSON frame
                           │
                           ▼
     consumeSentenceStream() → audioManager.enqueue()
     (ttsSentenceStream.ts:80)
                           │
                           ▼
     AudioManager FIFO 큐 → HTMLAudioElement 재생
```

---

## 3. 병목 지점 4곳 (증거 기반)

### B1. 프런트엔드: **chat-stream 중 TTS 미호출** (가장 큰 체감 지연)

- [useVTuberStore.ts:252](Geny/frontend/src/store/useVTuberStore.ts#L252) `speakResponse`는 인자로 **이미 완성된 full text** 를 받는다.
- 호출 지점은 [VTuberChatPanel.tsx:240-243](Geny/frontend/src/components/live2d/VTuberChatPanel.tsx#L240)뿐으로, `eventType === 'agent_message'` 분기 — 즉 **에이전트 턴이 종료된 뒤**이다.
- `agent_progress` 이벤트의 `streaming_text`는 단순 UI 버블 업데이트 용도로만 소비되고 TTS로 흘러가지 않는다.
- **결과**: "생성되는 동안 한 문장씩 즉시 읽기 시작"이 불가능. LLM이 토큰 280자를 다 뱉을 때까지 TTS 시작 자체를 대기한다.

### B2. Geny 백엔드: **문장 분할 책임 없음 + 재-버퍼링**

- [omnivoice_engine.py:282-298](Geny/backend/service/vtuber/tts/engines/omnivoice_engine.py#L282): `payload["text"] = request.text` — Geny는 **텍스트를 단일 페이로드**로 OmniVoice에 넘긴다.
- Geny 단에서 감정/세션/참조 음성 프로필 등을 적용한 뒤 분할할 수 있는 훅이 없다. 따라서 분할 정책은 OmniVoice의 `max_sentence_chars` / `min_sentence_chars`에만 종속된다.
- **결과**: Geny가 LLM에서 문장을 이미 받고 있더라도, 그 경계 정보를 버리고 연결된 하나의 문자열로 다시 말아 보낸다. OmniVoice는 이를 `split_sentences(text)`로 **다시** 분할한다 (왕복 낭비).

### B3. OmniVoice 서버: **순차 `for` 루프** (설계 병목)

- [omnivoice/server/api.py:200-222](Geny/omnivoice/server/api.py#L200):
  ```python
  async def _gen():
      for seq, sentence in enumerate(sentences):      # ★ 직렬
          audio, sr = await engine.synthesize(...)    # ★ 이전 문장 끝나야 다음 시작
          yield json.dumps(frame).encode("utf-8") + b"\n"
  ```
- 동일 파일의 주석이 이미 이 한계를 인정한다:
  > "Latency model: client receives sentence #1 once it's fully synthesised (single-GPU semaphore prevents pipelining), then #2, etc."

- **결과**: 문장 수 N일 때 전체 지연 = `∑ t_i + overhead`. 스트리밍의 유일한 이득은 "첫 문장 시점 = t_1 < ∑t_i" 뿐이며, 문장 분할/세팅 오버헤드(모델 warm, ref-cache 조회 등)가 `t_1`에 가산되면 단일 합성 대비 느려진다.

### B4. OmniVoice: **`Semaphore(max_concurrency=1)` 기본값**

- [omnivoice/server/settings.py:67-75](Geny/omnivoice/server/settings.py#L67): `max_concurrency: int = Field(default=1, ...)`.
- [omnivoice/server/engine.py:516](Geny/omnivoice/server/engine.py#L516): `async with state.semaphore:` 가 **모든** 합성 호출을 감싼다.
- **결과**: B3를 `asyncio.gather`로 고쳐도, 세마포어가 1이면 실제 GPU 작업은 여전히 직렬. B3·B4는 반드시 함께 푼다.

### B5 (보조). 프런트엔드 오디오 큐: **동시 디코딩/프리페치 부재**

- [ttsSentenceStream.ts:80-130](Geny/frontend/src/lib/ttsSentenceStream.ts#L80): NDJSON 프레임을 받자마자 base64→Blob→`audioManager.enqueue` 하는 순서. Blob 디코딩이 순차 `handleLine`에서 일어난다.
- `audioManager`는 FIFO이며, 클립 사전 디코드(Web Audio decodeAudioData) 파이프라인이 없어서 프레임 도착과 실제 재생 사이에 추가 200~500ms 가 낀다.

---

## 4. 목표 SLO

| 지표 | 현재(추정) | 목표 |
|------|-----------|------|
| 첫 음성 도착(First Audio, FA) | 단일 문장일 때 < 1.5s, 다문장 긴 발화일 때 3~5s | **< 1.2s** (에이전트 첫 문장 감지 시점 기준) |
| 3문장 총 재생 완료(E2E) | 순차 합성합 8~12s | **3.5~5s** (≥ 2-way 병렬 가정) |
| 문장 간 갭(inter-clip gap) | 200~600ms | **< 150ms** (프리페치로 제거) |
| 실패 시 fallback 경로 | 있음 (single-shot) | 유지 + **부분 재합성**(failed seq만 재시도) |

---

## 5. 개선안 (우선순위 · 단계별)

### 🥇 P0 — OmniVoice 서버 병렬 합성 (B3 + B4)

핵심 변경은 서버 한 파일. 위험도 낮고 효과 가장 크다.

**파일**: [omnivoice/server/api.py](Geny/omnivoice/server/api.py#L152) `/tts/stream`

```python
# AS-IS (발췌)
for seq, sentence in enumerate(sentences):
    audio, sr = await engine.synthesize(text=sentence, ...)
    yield frame
```

```python
# TO-BE: 세마포어-인지 병렬 + 순서 보존 yield
async def _synth_one(seq: int, sentence: str) -> dict:
    try:
        audio, sr = await engine.synthesize(text=sentence, ...)
        return {"seq": seq, "text": sentence, "audio_b64": ..., "format": req.audio_format}
    except Exception as exc:
        return {"seq": seq, "text": sentence, "error": str(exc)}

# 모든 문장을 동시에 시작 → engine 내부 Semaphore(N)이 실제 병렬도 제한
tasks = [asyncio.create_task(_synth_one(i, s)) for i, s in enumerate(sentences)]

# 순서 보존을 위해 pending_buffer 사용
done_flags: dict[int, dict] = {}
next_to_emit = 0
for coro in asyncio.as_completed(tasks):
    result = await coro
    done_flags[result["seq"]] = result
    while next_to_emit in done_flags:
        yield (json.dumps(done_flags.pop(next_to_emit), ensure_ascii=False) + "\n").encode("utf-8")
        next_to_emit += 1
```

- **순서 보존**: `as_completed`로 완료 순서대로 수집하되, `next_to_emit` 커서로 in-order yield.
- **부수 효과 없음**: `engine.synthesize` 내부의 `async with state.semaphore` 는 이미 존재하므로 동시 제출만 해도 GPU가 알아서 직렬화한다.
- **Semaphore 튜닝**: 멀티 GPU 또는 VRAM 여유가 있을 때 `OMNIVOICE_MAX_CONCURRENCY=2~4` 로 운영 환경에서 승격.

**측정 가능한 이득**: 문장 3개를 동시에 제출 → `max_concurrency=2` 기준 체감 총 시간 ≈ `⌈3/2⌉ × 평균 합성시간`. 단일 세마포어로도 첫 문장 완료는 현재와 동일하나, **문장 2~3의 합성이 문장 1의 yield/네트워크 대기 동안 미리 시작**되어 클립 간 갭이 사라진다.

---

### 🥇 P0 — Geny 백엔드: 문장 경계 패스스루 (B2)

LLM이 이미 끝낸 문장을 Geny가 OmniVoice로 **순차적으로** 넘길 수 있도록 한다.

**새 엔드포인트**: `POST /api/tts/agents/{sid}/speak/ndjson-chunks`
- 요청: `Content-Type: application/x-ndjson`, 각 줄이 `{"seq": n, "text": "...", "final": false}`.
- 서버 내부: 각 chunk를 받는 즉시 `engine.synthesize_sentence(sentence)` 비동기 태스크 제출 → 완료 NDJSON을 프런트엔드로 파이프.

**시그니처 추가**: [omnivoice_engine.py](Geny/backend/service/vtuber/tts/engines/omnivoice_engine.py)
```python
async def synthesize_sentence(self, request: TTSRequest, sentence: str) -> TTSSentenceChunk:
    """단일 문장만 동기적으로 합성 (새 P0 경로용)."""
```

**효과**: Geny가 LLM 문장 경계에서 즉시 TTS 태스크를 투입 → OmniVoice가 받자마자 합성 시작 → B1·B2·B3를 동시에 해소.

---

### 🥈 P1 — 프런트엔드 chat-stream → TTS 파이프라이닝 (B1)

**목표**: `agent_progress` streaming_text에서 **문장 완성 시점**에 부분 TTS 트리거.

**파일**:
- [VTuberChatPanel.tsx:257-273](Geny/frontend/src/components/live2d/VTuberChatPanel.tsx#L257) `agent_progress` 핸들러
- 신규 유틸: `Geny/frontend/src/lib/sentenceBoundaryDetector.ts`

**로직**:
```ts
// 문장 종료 감지: 한국어/영어 공용
const SENTENCE_END = /[.!?。！？…]["')\]]*\s|[\n]/g;

// agent_progress 수신 시
const prevEmitted = emittedSentencesRef.current[sessionId] ?? '';
const full = agent.streaming_text ?? '';
const unseen = full.slice(prevEmitted.length);

// 완성된 문장들만 추출
const sentences: string[] = [];
let lastEnd = 0;
for (const match of unseen.matchAll(SENTENCE_END)) {
  sentences.push(unseen.slice(lastEnd, match.index! + match[0].length).trim());
  lastEnd = match.index! + match[0].length;
}
// 미완성 꼬리는 버리고, 이미 보낸 문장까지만 emitted에 기록
if (sentences.length) {
  emittedSentencesRef.current[sessionId] = prevEmitted + unseen.slice(0, lastEnd);
  for (const s of sentences) {
    if (s) store.streamSpeakChunk(sessionId, s, inferredEmotion); // 새 메서드
  }
}
```

**새 스토어 메서드**: `streamSpeakChunk(sessionId, sentence, emotion)` — `speakResponse`와 달리 **턴 사이 state 리셋 없이** 누적 큐잉.

**턴 종료 시**: `agent_message` 핸들러에서 `emittedSentencesRef`와 실제 full text를 diff — 누락된 꼬리만 추가 TTS 호출. 이미 전송한 문장은 중복 방지.

**효과**: "첫 문장 완성 → 즉시 TTS 제출" 이 되어, LLM이 다음 문장을 생성하는 동안 OmniVoice는 첫 문장을 합성하고, 프런트엔드는 첫 문장을 재생한다. 3단 파이프라인 동시 가동.

---

### 🥈 P1 — 프런트엔드: Web Audio 프리디코드 파이프라인 (B5)

**파일**: `Geny/frontend/src/lib/audioManager.ts`

- `HTMLAudioElement` → `AudioBufferSourceNode` 전환 (이미 부분적으로 쓰이면 검토).
- 프레임 도착 즉시 `audioContext.decodeAudioData(arrayBuffer)` 병렬 실행 → `AudioBuffer` 캐시.
- 재생 스케줄러는 "이전 클립 `onended` + 0ms" 가 아니라 `audioContext.currentTime`에 sample-accurate 연쇄.

**효과**: 클립 간 공백 < 50ms. 특히 한국어 같이 짧은 문장(3~8단어)이 연속될 때 체감 큼.

---

### 🥉 P2 — 관측 가능성 & 자동 튜닝

1. **서버 타이밍 로그 구조화** — [api.py](Geny/omnivoice/server/api.py#L200) 이미 `synth_dt` 출력 중. **per-seq 큐 대기시간(enqueue→start_synth) 을 추가**. 그라파나/프런트엔드 LogsTab에서 문장별 bar chart 표시 가능.

2. **세마포어 적응형 튜닝** — 합성 평균 시간 · VRAM usage · OOM 카운터를 관찰해 `max_concurrency`를 런타임 조정. 시작은 1, 안정적이면 2로 승격.

3. **프런트엔드 메트릭** — `speakResponse` 호출 → 첫 audio 실제 `play()` 사이 시간을 `performance.measure` 로 기록. LogsTab에 "FA=820ms" 형식 표시.

---

## 6. 호환성 · 롤백 전략

| 변경 | 하위 호환 | 롤백 |
|------|-----------|------|
| P0 OmniVoice `/tts/stream` 병렬화 | **유지** (same request/response schema) | 코드 한 줄 `gather` → `for` 복귀 |
| P0 `synthesize_sentence` 신규 메서드 | 기존 `synthesize_sentence_stream` 유지 | 신규 미사용 시 무영향 |
| P0 `/speak/ndjson-chunks` 신규 엔드포인트 | 기존 `/speak/stream` 유지 | 프런트엔드 플래그로 off |
| P1 프런트 streaming_text → TTS | 런타임 플래그 `ttsGeneral.preEmitSentences` 뒤에 숨김 | 플래그 false로 즉시 복귀 |
| P1 AudioBuffer 전환 | 기존 `<audio>` 폴백 유지 | iOS WebKit 이슈 재발 시 롤백 |

---

## 7. 테스트 계획

### 유닛 테스트
- **omnivoice/tests/test_api_stream_parallel.py** (신규):
  - 문장 N=3, 합성 지연 각각 1.0s/0.5s/2.0s (mock engine) → 전체 완료 ≤ 2.2s (max+소폭 오버헤드) 이고 **yield 순서는 seq=0,1,2**.
- **Geny/backend/tests/service/vtuber/tts/test_sentence_chunks.py** (신규):
  - `/speak/ndjson-chunks` 가 seq 순서 보존, 중간 chunk 실패 시 나머지 진행.

### 통합 / 수동
- 긴 한국어 발화(280자, 5문장) → FA, 총 시간 측정 before/after.
- 네트워크 지연 200ms 주입(Chrome DevTools) → 순서 역전 없음 확인.
- `max_concurrency=2` 설정 → VRAM < 20GB 유지 확인.

### 회귀
- 기존 `/tts` (single-shot) 경로 변함 없음 확인.
- fallback 체인: `speak/stream` 실패 → `/tts` → `/speak` 의 3단 fallback이 P1 경로에서도 유지.

---

## 8. 실행 순서 (권장)

| 단계 | 작업 | 예상 범위 |
|------|------|-----------|
| 1 | **P0-OmniVoice 병렬화** (`api.py` `/tts/stream`) + 유닛 테스트 | 단일 파일 수정 · 테스트 1개 |
| 2 | `OMNIVOICE_MAX_CONCURRENCY=2` 로드 테스트, VRAM 모니터링 | 운영 설정 |
| 3 | **P0-Geny 문장 단위 엔드포인트** (`synthesize_sentence` + `/speak/ndjson-chunks`) | 백엔드 2~3 파일 |
| 4 | **P1 프런트엔드 pre-emit** (SentenceBoundaryDetector + streaming_text 훅) | 프런트엔드 2~3 파일 + 플래그 |
| 5 | P1 AudioBuffer 파이프라인 | `audioManager.ts` 리팩터 |
| 6 | P2 관측성 & 튜닝 | 로그/메트릭 |

---

## 9. 리스크 & 미정사항

- **GPU OOM 위험** (P0 병렬화): `max_concurrency > 1` 은 OmniVoice가 돌아가는 모델/GPU VRAM에 강하게 의존. 기본값은 1 유지, 운영자가 의식적으로 승격.
- **한국어 문장 경계 정확도** (P1): `SENTENCE_END` 정규식이 "1.5초" 같은 소수점을 잘못 분할할 수 있음. 숫자 뒤 공백 여부 룩어헤드 또는 `intl-segmenter` 사용 고려.
- **프런트엔드 파이프라이닝 + 취소**: 턴 중간에 사용자가 새 메시지를 보내면 기존 streaming TTS 클립을 abort해야 한다. 현재 `_ttsAbortControllers` 로직을 chunk 단위로 확장 필요.
- **감정 태그**: 문장 단위 pre-emit 시 감정은 턴 종료까지 미정. 최초 문장은 `neutral` 로 시작하고, `agent_message` 수신 시점에 최종 감정으로 **이후** 문장을 보정하는 방안(첫 문장은 감정 미반영) — 사용자 합의 필요.

---

## 10. 부록: 증거 파일/라인 인덱스

| 병목 | 파일 | 라인 |
|------|------|------|
| B1 | [useVTuberStore.ts](Geny/frontend/src/store/useVTuberStore.ts#L252) | 252-340 |
| B1 | [VTuberChatPanel.tsx](Geny/frontend/src/components/live2d/VTuberChatPanel.tsx#L240) | 237-250 |
| B2 | [omnivoice_engine.py](Geny/backend/service/vtuber/tts/engines/omnivoice_engine.py#L282) | 282-340 |
| B2 | [tts_service.py](Geny/backend/service/vtuber/tts/tts_service.py#L182) | 182-220 |
| B3 | [omnivoice/server/api.py](Geny/omnivoice/server/api.py#L200) | 152-250 |
| B4 | [omnivoice/server/settings.py](Geny/omnivoice/server/settings.py#L67) | 67-75 |
| B4 | [omnivoice/server/engine.py](Geny/omnivoice/server/engine.py#L516) | 105-115, 381, 516 |
| B5 | [ttsSentenceStream.ts](Geny/frontend/src/lib/ttsSentenceStream.ts#L80) | 80-150 |

---

**결론**: P0 두 항목(OmniVoice 병렬화 + Geny 문장 경계 패스스루)만 적용해도 **다문장 발화의 첫 음성 도착 시간이 현재 대비 2~3배 단축**될 것으로 예측된다. P1의 chat-stream pre-emit을 얹으면 LLM 생성/합성/재생이 완전 파이프라인화되어, 체감상 "생각하면서 말하는" 수준의 응답성을 달성할 수 있다.
