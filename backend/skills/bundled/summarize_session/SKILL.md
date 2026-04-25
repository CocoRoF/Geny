---
name: summarize-session
description: Compact the current session's recent turns into a 3-paragraph summary covering what was discussed, decisions made, and open follow-ups.
allowed_tools:
  - memory_search
  - memory_list
  - memory_read
model_override: claude-haiku-4-5
execution_mode: inline
---

# Summarize Session

You are summarising the current Geny session for the operator. Produce a tight three-paragraph summary:

**1. Topics covered (bullet sentences).**
What was the operator working on? List 3–6 concrete topics with one-sentence descriptions each.

**2. Decisions and conclusions.**
What was decided, agreed on, or accepted? Distinguish "decided" (won't re-litigate) from "leaning toward" (still open).

**3. Open follow-ups.**
What's unfinished? What needs the operator's input? What would the next session start with?

Use `memory_search` / `memory_list` / `memory_read` to ground the summary in the session's actual notes — do NOT make up content. If the memory backend is empty, say so explicitly instead of fabricating.

Keep the summary under ~250 words. Use plain prose, not lists for the body of each paragraph.
