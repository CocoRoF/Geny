# 03 — Frontend completion

**Phase:** 1 (first — lowest risk, highest user-visible value)
**PRs:** 4
**Risk:** low — additive frontend, no backend touch.

---

## Why deferred from cycles A+B

Three component shells shipped (TasksTab.tsx, CronTab.tsx,
SlashCommandAutocomplete.tsx) but nothing in the sidebar / chat
input invokes them yet. Operators see "tasks running in logs but
no UI tab" — confusing.

Skill metadata extension (`category` / `effort` / `examples`) is
in the backend response but SkillPanel.tsx renders neither.

Permission mode toggle for the new `acceptEdits` / `dontAsk` modes
is missing from SettingsTab.tsx.

---

## PR-D.3.1 — feat(frontend): wire TasksTab + CronTab into TabNavigation

### Files

- `frontend/src/components/TabNavigation.tsx` (modify)
- `frontend/src/components/TabContent.tsx` (modify)
- `frontend/src/types/tabs.ts` or equivalent (modify if a tab enum/union exists)

### Change

Add two entries to the tab list:

```tsx
{ key: 'tasks', label: 'Tasks', icon: ListChecks, component: TasksTab },
{ key: 'cron',  label: 'Cron',  icon: Calendar,    component: CronTab },
```

Position: after "Memory" tab, before "Settings". Both should be
visible to authenticated users; admin-only restrictions are not
warranted (read-only data + scoped REST endpoints).

### Acceptance criteria

- [ ] both tabs appear in sidebar after deploy
- [ ] clicking either renders the existing component
- [ ] tab state persists in `useAppStore` like other tabs
- [ ] no regression on existing tabs

### Manual smoke

1. Deploy → visit web UI
2. Sidebar shows "Tasks" + "Cron" entries
3. Click Tasks → polling list renders empty (no tasks yet)
4. POST a task via curl → row appears within 5s

---

## PR-D.3.2 — feat(frontend): SlashCommandAutocomplete in CommandTab

### Files

- `frontend/src/components/tabs/CommandTab.tsx` (modify)

### Change

Mount `SlashCommandAutocomplete` above the chat textarea, gated on
`inputValue.startsWith('/')`. On select, replace the slash token
with `/<selected> ` and refocus the textarea.

```tsx
const [draft, setDraft] = useState('');

return (
  <div>
    {draft.startsWith('/') && (
      <SlashCommandAutocomplete
        inputValue={draft}
        onSelect={(name) => {
          // Preserve everything after the first whitespace token.
          const tail = draft.replace(/^\/\S*\s?/, '');
          setDraft(`/${name} ${tail}`);
          textareaRef.current?.focus();
        }}
      />
    )}
    <textarea ref={textareaRef} value={draft} onChange={...} />
  </div>
);
```

Server-side dispatch:

```tsx
async function handleSubmit() {
  if (draft.startsWith('/')) {
    const resp = await slashCommandApi.execute(draft);
    if (resp.matched) {
      // Render the system message in the timeline.
      pushSystemMessage(resp.content || '');
      if (resp.follow_up_prompt) {
        // The host wants the LLM to see follow_up_prompt as user input.
        await sendUserMessage(resp.follow_up_prompt);
      }
      setDraft('');
      return;
    }
  }
  // fallback: regular chat send
  await sendUserMessage(draft);
}
```

### Tests

`frontend/src/components/__tests__/CommandTab.slash.test.tsx`
(if frontend test infra exists; otherwise manual smoke).

### Acceptance criteria

- [ ] typing `/co` shows /cost, /context, /config rows
- [ ] click → input becomes `/<name> `
- [ ] submit `/cost` → backend dispatch + system-message render
- [ ] follow_up_prompt path: `/skill-foo bar` runs server-side then
      LLM sees `bar` (whatever the md template substitutes)
- [ ] no slash → existing chat flow unchanged

---

## PR-D.3.3 — feat(frontend): SkillPanel — show category / effort / examples

### Files

- `frontend/src/components/skills/SkillPanel.tsx` (modify)
- `frontend/src/types/skill.ts` (modify — extend the Skill type)

### Change

Skill type gains:

```ts
export interface Skill {
  id: string;
  name: string;
  description: string;
  category?: string;
  effort?: 'low' | 'medium' | 'high' | string;
  examples?: string[];
  // ... existing fields
}
```

Render:

- Category badge (small pill) next to the skill name
- Effort indicator (●○○ / ●●○ / ●●●) if present
- Examples accordion below description; clicking an example
  populates the slash-command input

### Backend wiring

Verify that `controller/skills_controller.py` already surfaces these
fields in its response model. If not, extend the pydantic model to
include them (small follow-up in the backend file).

### Acceptance criteria

- [ ] new fields appear in SkillPanel
- [ ] missing fields don't render badges (graceful)
- [ ] examples accordion opens on click; clicking an example
      populates the chat input
- [ ] no regression on existing skill panel rendering

---

## PR-D.3.4 — feat(frontend): permission mode dropdown in SettingsTab

### Files

- `frontend/src/components/tabs/SettingsTab.tsx` (modify)
- `frontend/src/lib/api.ts` — `permissionApi` (modify if a separate
  permission settings endpoint exists; otherwise the mode lives
  in settings.json and is read at session start)

### Change

Settings panel gains a "Permission mode" dropdown with all 6
options:

| Value | Label |
|---|---|
| `default` | Default (rules decide) |
| `plan` | Plan (read-only stance) |
| `auto` | Auto (allow including destructive) |
| `bypass` | Bypass (developer only — allows even denies) |
| `acceptEdits` | Accept Edits (auto-allow Write/Edit) |
| `dontAsk` | Don't Ask (every ask becomes allow) |

Tooltips clarify each. Selection saves to settings.json via
`PATCH /api/settings` (or whatever Geny's existing settings save
endpoint is).

### Acceptance criteria

- [ ] dropdown shows all 6 modes
- [ ] selection persists to settings.json
- [ ] new session reads the saved mode
- [ ] tooltip clarifies each mode's behavior

---

## Combined acceptance criteria (all 4 PRs)

- [ ] sidebar has Tasks + Cron tabs
- [ ] CommandTab autocomplete works
- [ ] SkillPanel renders new metadata
- [ ] SettingsTab exposes new modes
- [ ] no regression on existing UI flows
- [ ] manual smoke checklist (in 05) passes for every new UI path
