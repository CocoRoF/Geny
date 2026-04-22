# Voice profile format

`geny-omnivoice` discovers profiles by scanning `OMNIVOICE_VOICES_DIR`
(default `/voices`, mounted from `Geny/backend/static/voices`).

Each subdirectory is one profile. Layout:

```
<voices_dir>/<profile_id>/
├── profile.json       # required for emotion-aware reference selection
├── ref_neutral.wav    # at least one reference recommended
├── ref_joy.wav
├── ref_anger.wav
└── ...
```

## profile.json

We keep the **same schema** that GPT-SoVITS already uses, so the file
can stay shared between both engines. Unknown keys are passed through.

```json
{
  "name": "paimon_ko",
  "display_name": "파이몬 (한국어)",
  "language": "ko",
  "is_template": true,
  "prompt_text": "으음~ 나쁘지 않은데? 너도 먹어봐~ 우리 같이 먹자!",
  "prompt_lang": "ko",
  "emotion_refs": {
    "neutral": {
      "file": "ref_neutral.wav",
      "prompt_text": "으음~ 나쁘지 않은데? 너도 먹어봐~ 우리 같이 먹자!",
      "prompt_lang": "ko"
    },
    "joy": {
      "file": "ref_joy.wav",
      "prompt_text": "우와아——! 이건 세상에서 제일 맛있는 요리야!",
      "prompt_lang": "ko"
    }
  }
}
```

### Fields consumed by geny-omnivoice

| Path                                | Purpose                                                |
|-------------------------------------|--------------------------------------------------------|
| `display_name` / `name`             | Human-readable label in `GET /voices`.                 |
| `language`                          | Default language for `clone` mode when caller omits it.|
| `is_template`                       | Flag exposed in `GET /voices`.                         |
| `emotion_refs.<emotion>.file`       | Filename inside the profile directory.                 |
| `emotion_refs.<emotion>.prompt_text`| Used as `ref_text` for that emotion.                   |
| `emotion_refs.<emotion>.prompt_lang`| Used to pin the language when transcript-language doesn't match speech.|

### Optional voice-design fields (geny-omnivoice extension)

These are **opt-in** and ignored by GPT-SoVITS. Add them only if you
want a profile to default to a specific design instruction.

```json
{
  "omnivoice_design": {
    "instruct": "female, low pitch, british accent",
    "preferred_language": "en"
  }
}
```

## Filesystem-only fallback

If `profile.json` is missing or has no `emotion_refs`, the server falls
back to scanning the directory for `ref_<emotion>.wav` files and uses
each of them with no prompt text.

## Reference audio recommendations

Per upstream OmniVoice guidance (`docs/tips.md` in the upstream repo):

- Keep references to **3–10 seconds**. Longer clips slow down inference
  and may degrade cloning quality.
- Use a reference whose language matches the target speech for the most
  natural pronunciation.
- For better results with Arabic numerals, normalize them to words
  (e.g. "123" → "one hundred twenty-three") before sending the request.
