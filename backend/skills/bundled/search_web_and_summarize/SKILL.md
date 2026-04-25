---
name: search-web-and-summarize
description: Run a web search for the operator's query, fetch the top 3 results, and return a synthesised answer with inline citations.
allowed_tools:
  - web_search
  - web_fetch
  - web_fetch_multiple
model_override: claude-sonnet-4-6
execution_mode: inline
---

# Search Web and Summarize

You are answering the operator's question by doing primary-source web research. Workflow:

1. **Plan the search.** Restate the query in your own words. If it's ambiguous, narrow it before searching (don't ask the operator — make a sensible disambiguation and note it).

2. **Search.** Call `web_search` with `max_results=5`. Inspect the snippets: which 2–3 results look most authoritative for this question?

3. **Fetch.** Call `web_fetch_multiple` (or `web_fetch` for a single source) on the chosen URLs. If a result is paywalled / 404 / empty, note it and continue with the others.

4. **Synthesise.** Write the answer in two parts:
   - A 1–2 sentence direct answer to the operator's question.
   - 2–4 paragraphs of supporting detail, with **inline citations** like `[1]`, `[2]` matching the URL list at the bottom.

5. **Citations.** End with a numbered list of the URLs you used. Don't include sources you didn't actually consult — accuracy matters more than coverage.

Keep total output under 600 words. If the search returns nothing useful, say so directly rather than padding with adjacent content.
