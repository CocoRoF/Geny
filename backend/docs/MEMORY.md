# Memory System

> Per-session memory system combining Long-Term Memory (LTM) + Short-Term Memory (STM) + FAISS vector search

## Architecture Overview

```
SessionMemoryManager (unified facade)
        │
        ├── LongTermMemory       ── Markdown files + DB
        │     └── MEMORY.md, dated.md, topics/*.md
        │
        ├── ShortTermMemory      ── JSONL transcript + DB
        │     └── session.jsonl, summary.md
        │
        └── VectorMemoryManager  ── FAISS + Embedding API
              ├── SessionVectorStore (IndexFlatIP)
              └── EmbeddingProvider (OpenAI / Google / Voyage)
```

All writes use **dual recording to file + DB**; reads use **DB first → file fallback**.

---

## Long-Term Memory (LongTermMemory)

Markdown file-based knowledge store that persists across sessions.

### Storage Layout

```
{storage_path}/memory/
├── MEMORY.md                # Main memory file (append-only)
├── 2026-03-21.md            # Dated execution records
├── 2026-03-20.md
└── topics/
    ├── python-basics.md     # Topic-specific knowledge
    └── api-design.md
```

### Methods

| Method | Description |
|--------|-------------|
| `append(text, heading=None)` | Append to MEMORY.md with KST timestamp |
| `write_dated(text, date=None)` | Write to dated file (default: today) |
| `write_topic(topic, text)` | Write to `topics/{slug}.md` |
| `load_all()` | Load all .md files (DB first) |
| `load_main()` | Load MEMORY.md only |
| `search(query, max_results=5)` | Keyword search (density + recency scoring) |

### Search Scoring

```python
score = keyword_density * 0.7 + recency * 0.3
```

Maximum file indexing size: 256 KB.

---

## Short-Term Memory (ShortTermMemory)

In-session conversation transcript. JSONL format.

### Storage Layout

```
{storage_path}/transcripts/
├── session.jsonl            # Conversation log (max 2000 lines)
└── summary.md               # Session summary
```

### JSONL Format

```json
{"type": "message", "role": "user", "content": "...", "ts": "2026-03-21T15:30:00"}
{"type": "message", "role": "assistant", "content": "...", "ts": "..."}
{"type": "event", "event": "tool_call", "data": {"name": "web_search", "args": {...}}, "ts": "..."}
```

### Methods

| Method | Description |
|--------|-------------|
| `add_message(role, content, metadata)` | Add message |
| `add_event(event, data)` | Record event |
| `write_summary(summary)` | Write/overwrite session summary |
| `load_all()` | Full transcript (excluding summary) |
| `get_recent(n=20)` | Recent N messages |
| `get_summary()` | Load session summary |
| `search(query, max_results=10)` | Keyword search + recency boost |
| `message_count()` | Total message count |

---

## Vector Memory (FAISS)

Semantic similarity search. Chunks long-term memory files → embeds → stores in FAISS index.

### Storage Layout

```
{storage_path}/vectordb/
├── index.faiss              # FAISS index (IndexFlatIP)
└── metadata.json            # Chunk metadata
```

### Embedding Provider

Configuration: `LTMConfig` (`ltm` group in Config System)

| Provider | Model | Dimensions |
|----------|-------|------------|
| **OpenAI** | `text-embedding-3-small` | 1536 |
| | `text-embedding-3-large` | 3072 |
| | `ada-002` | 1536 |
| **Google** | `text-embedding-004` | 768 |
| | `embedding-001` | 768 |
| **Voyage AI** | `voyage-3-large` | 1024 |
| | `voyage-3` | 1024 |
| | `voyage-3-lite` | 512 |
| | `voyage-code-3` | 1024 |

Batch size: 96 per request. Uses `httpx.AsyncClient`.

### LTM Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | `false` | Enable vector memory |
| `embedding_provider` | `"openai"` | Embedding provider |
| `embedding_model` | `"text-embedding-3-small"` | Model |
| `embedding_api_key` | `""` | API key |
| `chunk_size` | `1024` | Chunk size (characters) |
| `chunk_overlap` | `256` | Chunk overlap (characters) |
| `top_k` | `6` | Search result count |
| `score_threshold` | `0.35` | Minimum similarity score |
| `max_inject_chars` | `10000` | Maximum characters for prompt injection |

### SessionVectorStore

Based on FAISS `IndexFlatIP` (L2-normalized vectors = cosine similarity).

| Method | Description |
|--------|-------------|
| `load_or_create()` | Load from disk or create new (dimension validation) |
| `save()` | Save `index.faiss` + `metadata.json` |
| `add_chunks(texts, vectors, source_file, ...)` | Add chunks (deduplication) |
| `remove_source(source_file)` | Remove chunks by source file |
| `search(query_vector, top_k=5, score_threshold=0.0)` | Cosine similarity search |

### Text Chunking

```python
chunk_text(text, chunk_size=512, chunk_overlap=64)
```

Split priority: paragraph (`\n\n`) → sentence (`.!?`) → line (`\n`) boundaries. Overlap maintains context.

### VectorMemoryManager

FAISS indexing + search orchestrator.

| Method | Description |
|--------|-------------|
| `initialize()` | Load config, create embedding provider + vector store |
| `index_memory_files()` | Scan `memory/*.md` → chunk → embed → FAISS upsert |
| `index_text(text, source_file, replace=False)` | Index single text |
| `search(query, top_k, score_threshold)` | Query embedding → FAISS search |
| `build_vector_context(results, max_chars)` | Format results as XML tags |

---

## SessionMemoryManager

Top-level facade integrating LTM + STM + VMM.

### Recording Methods

| Method | Target | Description |
|--------|--------|-------------|
| `record_message(role, content)` | STM | Record conversation message |
| `record_event(event, data)` | STM | Record event |
| `remember(text, heading=None)` | LTM | Append to MEMORY.md |
| `remember_dated(text)` | LTM | Write to dated file |
| `remember_topic(topic, text)` | LTM | Write to topic file |
| `record_execution(input_text, result_state, ...)` | LTM + VMM | Record structured execution summary |

### record_execution Output Format

Execution summary recorded in dated LTM file:

```markdown
## ✅ Task: Create a Python web server
- **Duration:** 12.3s | **Difficulty:** easy | **Iterations:** 1
- **Completion:** COMPLETE
- **Cost:** $0.0234

### Output Preview
First 500 characters of final response...
```

Hard path includes TODO list, medium path includes review feedback, model fallback info included when applicable.

### Search Methods

```python
results = await manager.search("web server", max_results=10)
# LTM results get 1.2x weight boost
```

### Context Build (for prompt injection)

```python
context = await manager.build_memory_context_async(
    query="web server",
    include_summary=True,
    include_recent=True,
    max_chars=8000
)
```

Output format (XML tags):
```xml
<session-summary>
  Session summary content...
</session-summary>

<long-term-memory>
  MEMORY.md content...
</long-term-memory>

<vector-memory>
  [memory/2026-03-20.md] Relevant chunk...
  [memory/topics/python-basics.md] Relevant chunk...
</vector-memory>

<memory-recall>
  Keyword search results...
</memory-recall>

<recent-message>
  Recent conversation history...
</recent-message>
```

Default budget: 8000 characters.

---

## Data Types

### MemoryEntry

```python
@dataclass
class MemoryEntry:
    source: MemorySource      # LONG_TERM, SHORT_TERM, BOOTSTRAP
    content: str
    timestamp: Optional[datetime]
    filename: Optional[str]
    line_start: Optional[int]
    line_end: Optional[int]
    metadata: Dict[str, Any]

    @property
    def token_estimate(self) -> int:
        return len(self.content) // 3  # 3 chars ≈ 1 token
```

### MemorySearchResult

```python
@dataclass
class MemorySearchResult:
    entry: MemoryEntry
    score: float
    snippet: str
    match_type: str  # "keyword", "recency", "combined", "db_keyword"
```

---

## Workflow Integration

The `memory_inject` node automatically injects memory during workflow execution:

```
Memory Inject Node
    │
    ├── 1. LLM Gate: Determine if memory is needed (MemoryGateOutput)
    │
    ├── 2. If needed:
    │     ├── Session summary (STM summary)
    │     ├── MEMORY.md (LTM main)
    │     ├── FAISS vector search (VMM)
    │     └── Keyword search (LTM + STM)
    │
    └── 3. State update:
          ├── memory_refs: List of loaded memory chunks
          └── memory_context: Formatted memory text
```

---

## Related Files

```
service/memory/
├── types.py                # MemorySource, MemoryEntry, MemorySearchResult, MemoryStats
├── long_term.py            # LongTermMemory (Markdown + DB)
├── short_term.py           # ShortTermMemory (JSONL + DB)
├── embedding.py            # EmbeddingProvider ABC + 3 implementations
├── vector_store.py         # SessionVectorStore (FAISS), chunk_text()
├── vector_memory.py        # VectorMemoryManager (indexing + search)
└── manager.py              # SessionMemoryManager (unified facade)
```
