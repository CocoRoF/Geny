/**
 * sentenceBoundaryDetector — 실시간 LLM 토큰 스트림에서
 * **이미 완성된** 문장 경계를 찾아내는 유틸리티.
 *
 * 에이전트가 `streaming_text`를 조금씩 쏟아낼 때, 이미 끝난 문장만
 * 뽑아 TTS 큐로 넘기기 위해 사용한다. 마지막 미완 문장(trailing
 * incomplete fragment)은 다음 호출까지 보류된다.
 *
 * 핵심 규칙 (omnivoice/server/text_split.py 와 의도적으로 일치시킴):
 *  - 종결부호: `.`, `!`, `?`, `。`, `！`, `？`, `…` + 연속된 개행
 *  - 종결부호 뒤에 따옴표/괄호가 따라붙으면 문장 말미에 포함
 *  - 소수점(`1.5`) · 축약형(`e.g.`) 같은 의사-종결은 **뒤에 공백/개행이 있을 때만** 종결로 본다
 *  - `\n\n` (blank line)은 무조건 강제 종결 — 시 / 대사 전환 대응
 *
 * 한글/영문 혼재 대응:
 *  - 한글 문장은 거의 마침표 없이 `요.`, `다.`, `!`, `?`, `~` 로 끝남
 *  - 감탄사(`아!`, `음...`)는 min-chunk 없으면 단독 문장이 됨 — 어차피
 *    OmniVoice 측 `min_sentence_chars` 로 병합되므로 여기선 그대로 쪼갠다
 */

// 종결부호 + 선택적 닫는 따옴표/괄호 + (공백 | 개행 | EOF)
// sticky(y) 플래그 대신 global(g)로 반복 매칭.
const SENTENCE_END = /([.!?。！？～~…]+|[.!?]+)(['")\]』」】》]*)(\s+|$)/gu;
// blank line (paragraph separator) — 강제 종결
const PARAGRAPH_BREAK = /\n[ \t]*\n/g;

/** 추출 결과 */
export interface BoundaryResult {
  /** 완성된 문장 배열 (앞 공백/개행 trim) */
  sentences: string[];
  /** 아직 종결되지 않아 보류된 꼬리 */
  remainder: string;
  /** `fullText`에서 `sentences`로 소비된 바이트 수 (caller가 emitted offset 갱신용) */
  consumed: number;
}

/**
 * `prevEmitted`까지 이미 TTS에 전송된 상태에서, `fullText` 중 추가로
 * 완성된 문장들을 뽑아낸다. 꼬리(미완)는 `remainder`로 돌려주고, 호출자는
 * 다음 틱에 `fullText` 전체를 다시 넘겨주면 된다 (누적 버퍼 전략).
 *
 * 안정성:
 *  - `prevEmitted`가 `fullText`의 prefix가 아니면 (에이전트가 재생성 등)
 *    버퍼를 리셋하지 않고 `fullText` 전체를 새로 스캔한다 — 중복 전송을
 *    피하기 위해 caller가 `forceFinal`로 강제 종료를 호출해야 한다.
 *  - 한 번에 여러 문장이 완성되었을 수 있으므로 **루프**로 모두 뽑아낸다.
 *
 * @param fullText — 지금까지 누적된 streaming_text 전체
 * @param prevEmitted — 이전 호출에서 TTS로 이미 보낸 prefix
 * @param opts.forceFinal — `true`면 꼬리까지 sentences로 포함 (턴 종료 시)
 * @param opts.minChars — 이 길이 미만의 꼬리는 문장으로 치지 않고 보류 (default 1). 강제 종료 때는 무시.
 */
export function extractCompletedSentences(
  fullText: string,
  prevEmitted: string,
  opts: { forceFinal?: boolean; minChars?: number } = {},
): BoundaryResult {
  const { forceFinal = false, minChars = 1 } = opts;

  // prefix mismatch 방어 — 재생성 등 비정상 케이스. fullText 기준으로
  // 작업하되 이미 보낸 것으로 간주되는 prevEmitted는 없는 것으로 친다.
  const base = fullText.startsWith(prevEmitted) ? prevEmitted.length : 0;
  const unseen = fullText.slice(base);

  if (!unseen) {
    return { sentences: [], remainder: '', consumed: base };
  }

  // 먼저 paragraph break로 강제 분할 → 각 파라그래프 안에서 문장 분할.
  // (paragraph break 자체도 sentences 경계가 된다)
  const sentences: string[] = [];
  let cursor = 0;

  // Paragraph breaks first: slice on \n\n and process each block
  const blocks: { text: string; endsWithBreak: boolean }[] = [];
  let lastIdx = 0;
  PARAGRAPH_BREAK.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = PARAGRAPH_BREAK.exec(unseen)) !== null) {
    blocks.push({ text: unseen.slice(lastIdx, m.index + m[0].length), endsWithBreak: true });
    lastIdx = m.index + m[0].length;
  }
  if (lastIdx < unseen.length) {
    blocks.push({ text: unseen.slice(lastIdx), endsWithBreak: false });
  }

  for (const block of blocks) {
    const blockText = block.text;
    let blockCursor = 0;
    SENTENCE_END.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = SENTENCE_END.exec(blockText)) !== null) {
      const end = match.index + match[0].length;
      const piece = blockText.slice(blockCursor, end).trim();
      if (piece) sentences.push(piece);
      blockCursor = end;
    }
    // Block tail: 종결부호 없는 꼬리.
    const tail = blockText.slice(blockCursor);
    if (block.endsWithBreak) {
      // paragraph break 앞의 꼬리는 강제 종결로 간주 (문장부호가 없어도
      // 화자 입장에서 한 호흡 끊는 지점)
      const trimmed = tail.trim();
      if (trimmed) sentences.push(trimmed);
      cursor += blockText.length;
    } else {
      // 마지막 블록의 꼬리만 remainder로 남음 — 그 앞의 모든 블록은
      // 위에서 paragraph break로 소비됨.
      cursor += blockCursor;
      // 꼬리는 아래에서 처리
    }
  }

  // 마지막 블록의 미완 꼬리
  const remainder = unseen.slice(cursor);

  if (forceFinal && remainder.trim() && remainder.trim().length >= minChars) {
    sentences.push(remainder.trim());
    return { sentences, remainder: '', consumed: base + unseen.length };
  }

  return { sentences, remainder, consumed: base + cursor };
}

/**
 * 간단한 in-memory 추출기 — 세션별 prevEmitted를 보관하여 호출자가
 * offset 관리를 신경쓰지 않아도 되도록 한 래퍼.
 *
 * 같은 `key`(세션/턴 조합)로 반복 호출하면 누적 버퍼 전략으로 동작하고,
 * `reset(key)`로 턴 경계에서 버퍼를 비울 수 있다.
 *
 * **문장 병합 (coalescing)**:
 *   `minChars` 옵션을 주면, 추출된 문장이 그 길이 미만이면 다음 문장과
 *   합쳐질 때까지 holding 버퍼에 보류한다. TTS 요청 1건당 fixed 오버헤드
 *   (커넥션 풀 + GPU 워밍업 + RTF 비효율) 가 크기 때문에, "안녕!" 같은
 *   극단적으로 짧은 클립이 큐를 점유하지 않게 막는다. `flush()` 시점에는
 *   minChars 미만이어도 holding 잔여를 강제로 emit 한다.
 */
export interface ExtractorOptions {
  /** 한 emit 클립의 최소 문자 수. 미만이면 다음 문장과 병합. (default 0 = 비활성) */
  minChars?: number;
  /** 두 문장을 이어붙일 때 사이에 넣는 구분자 (default ' ') */
  joiner?: string;
  /**
   * 이 문장 앞에서는 병합하지 않는다 — 보류 중이던 짧은 문장을 먼저 내보낸다.
   * 감정 cue 로 시작하는 문장이 그 예: 짧은 문장과 한 클립으로 묶이면 클립
   * 하나는 한 감정으로만 합성되므로 분위기 전환이 사라진다.
   */
  breakBefore?: (sentence: string) => boolean;
}

export class SentenceStreamExtractor {
  private _emitted = new Map<string, string>();
  private _holding = new Map<string, string>();
  private readonly _minChars: number;
  private readonly _joiner: string;
  private readonly _breakBefore?: (sentence: string) => boolean;

  constructor(opts: ExtractorOptions = {}) {
    this._minChars = Math.max(0, opts.minChars ?? 0);
    this._joiner = opts.joiner ?? ' ';
    this._breakBefore = opts.breakBefore;
  }

  /**
   * 추출된 문장 배열을 minChars 기준으로 병합한다.
   * 마지막 그룹이 minChars 미만이면 holding 으로 보류, 다음 push 때 합침.
   */
  private _coalesce(key: string, sentences: string[], force: boolean): string[] {
    if (this._minChars <= 0) {
      // 비활성: holding 무시하고 그대로 반환.
      return sentences;
    }
    const out: string[] = [];
    let buf = this._holding.get(key) ?? '';
    for (const s of sentences) {
      if (buf && this._breakBefore?.(s)) {
        out.push(buf);
        buf = '';
      }
      buf = buf ? `${buf}${this._joiner}${s}` : s;
      if (buf.length >= this._minChars) {
        out.push(buf);
        buf = '';
      }
    }
    if (force && buf) {
      out.push(buf);
      buf = '';
    }
    if (buf) this._holding.set(key, buf);
    else this._holding.delete(key);
    return out;
  }

  /**
   * 누적 텍스트에서 새로 완성된 문장들을 뽑고 내부 상태를 갱신한다.
   * `minChars` 가 설정되어 있으면 짧은 문장은 holding 버퍼에 모아 병합.
   */
  push(key: string, fullText: string): string[] {
    const prev = this._emitted.get(key) ?? '';
    const { sentences, consumed } = extractCompletedSentences(fullText, prev);
    if (sentences.length > 0 || consumed > prev.length) {
      this._emitted.set(key, fullText.slice(0, consumed));
    }
    return this._coalesce(key, sentences, /* force */ false);
  }

  /**
   * 턴 종료 — 미완 꼬리 + holding 잔여까지 모두 강제 emit.
   */
  flush(key: string, fullText: string): string[] {
    const prev = this._emitted.get(key) ?? '';
    const { sentences } = extractCompletedSentences(fullText, prev, { forceFinal: true });
    const out = this._coalesce(key, sentences, /* force */ true);
    this._emitted.delete(key);
    this._holding.delete(key);
    return out;
  }

  reset(key: string): void {
    this._emitted.delete(key);
    this._holding.delete(key);
  }
}
