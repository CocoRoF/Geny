# GenY Opsidian Enhancement Plan

> **Date**: 2026-04-06
> **Scope**: User Opsidian / Curated Knowledge / Session Memory UI
> **Focus**: Business logic & UX (not infrastructure)

---

## Current State Summary

### What Works

| Feature | User Opsidian | Curated Knowledge | Session Memory |
|---------|:---:|:---:|:---:|
| Read notes (markdown) | O | O | O |
| Create notes (DraftEditor) | O | O | X |
| Edit content | O | O | X (read-only) |
| Edit category | O | O | X |
| Edit importance | O | O | X |
| Edit tags | O | O | X |
| Edit title | X (creation only) | X (creation only) | X |
| Delete notes | O | O | X |
| Wikilink navigation | O | O | O |
| Search (text + semantic) | O | O | O |
| Graph visualization | O | O | O |
| Category sidebar grouping | O | O | O |
| Tag panel | O | O | O |
| Backlink panel | O | O | O |
| Right panel properties | O | O | O |
| Multi-tab file view | O | O | O |
| Curation pipeline | O | - | - |

### What's Missing

- **Folder/hierarchy**: 5개 카테고리만 존재, 사용자 정의 폴더 없음
- **Editor**: raw textarea만 제공, 마크다운 툴바/서식 지원 없음
- **Keyboard shortcuts**: 0개 구현 (Ctrl+G 힌트만 표시, 실제 핸들러 없음)
- **Note template**: 없음
- **Title editing**: 생성 후 제목 변경 불가
- **Bulk operations**: 없음
- **Import/Export**: 없음
- **Tag autocomplete**: 없음
- **Unlinked references**: 없음
- **Mobile responsive**: 미지원

---

## Enhancement Categories

### Phase 1: Editor Core

에디터 경험이 가장 기초적이고 임팩트가 큰 영역.

#### 1.1 Markdown Toolbar

**현재**: `<textarea>` 만 존재 (UserOpsidianView:830-848, CuratedKnowledgeView)
**개선**: 에디터 상단에 포맷팅 툴바 추가

```
[ B ] [ I ] [ S ] [ H1 ] [ H2 ] [ H3 ] [ • ] [ 1. ] [ > ] [ ``` ] [ --- ] [ [[ ]] ] [ 🔗 ]
```

| Button | Action | Shortcut |
|--------|--------|----------|
| **B** | `**bold**` 감싸기 | Ctrl+B |
| **I** | `*italic*` 감싸기 | Ctrl+I |
| **S** | `~~strike~~` 감싸기 | Ctrl+Shift+S |
| **H1~H3** | 행 앞에 `#` 삽입 | Ctrl+1, 2, 3 |
| **Bullet** | `- ` 삽입 | Ctrl+Shift+L |
| **Numbered** | `1. ` 삽입 | Ctrl+Shift+O |
| **Quote** | `> ` 삽입 | Ctrl+Shift+Q |
| **Code** | `` ``` `` 블록 삽입 | Ctrl+Shift+K |
| **Divider** | `---` 삽입 | - |
| **Wikilink** | `[[]]` 삽입 + 노트 검색 팝업 | Ctrl+L |
| **URL link** | `[text](url)` 삽입 | Ctrl+K |

**영향 파일**:
- `UserOpsidianView.tsx` — NoteEditor editing mode (line 686-851)
- `CuratedKnowledgeView.tsx` — CuratedNoteEditor editing mode
- 새 컴포넌트: `MarkdownToolbar.tsx` (공유)

**구현 방식**: textarea에 `selectionStart/selectionEnd` 조작으로 선택 텍스트 감싸기

---

#### 1.2 Split Preview (Editor + Preview)

**현재**: 편집 모드에서는 raw markdown만 보임, 뷰 모드에서는 렌더링만 보임
**개선**: 편집 시 좌/우 split view 옵션

```
┌────────────────────┬────────────────────┐
│   Raw Markdown     │   Rendered Preview │
│   (textarea)       │   (ReactMarkdown)  │
└────────────────────┴────────────────────┘
```

- 토글 버튼: `[Editor Only]` / `[Split]` / `[Preview Only]`
- Split 모드에서 스크롤 동기화 (선택 사항)
- 기존 ReactMarkdown 렌더러 재사용

---

#### 1.3 Title Editing (기존 노트)

**현재**: 생성 시에만 title 입력 가능, 이후 read-only (NoteEditor line 820-828)
**개선**: 뷰 모드에서 title 클릭 → inline editing, 저장 시 파일명 변경

**백엔드 필요사항**:
- `PUT /api/opsidian/files/{filename}` 에 `title` 필드 추가
- `StructuredMemoryWriter.update_note()` 에서 title 변경 시 파일 rename + 링크 참조 업데이트
- 양방향 링크에서 old filename을 new filename으로 일괄 교체

**주의**: 파일명이 slug(title) 기반이므로 title 변경 = 파일 rename. linked_from 참조도 갱신 필요.

---

#### 1.4 Auto-save & Draft Recovery

**현재**: 저장 버튼 누르지 않으면 편집 내용 소실
**개선**:
- 편집 중 30초마다 localStorage에 draft 자동 저장
- 페이지 이탈 시 `beforeunload` 경고
- 다음 진입 시 draft 감지 → "이전 편집 내용을 복원하시겠습니까?" 프롬프트

---

### Phase 2: Folder & Organization

#### 2.1 Custom Subcategory (하위 폴더)

**현재**: 5개 고정 카테고리만 존재 (daily/topics/entities/projects/insights)

**개선 Option A — Subcategory Path**:
카테고리 내에 `/` 구분자로 하위 경로 지원

```
topics/
  programming/
    python.md
    rust.md
  design/
    figma-tips.md
daily/
  2026-04/
    2026-04-06.md
```

- 카테고리 필드를 `topics/programming` 형태로 입력 가능
- 사이드바에서 depth 기반 트리 렌더링
- 접기/펼치기 지원

**백엔드 변경**:
- `StructuredMemoryWriter`: category에 `/` 허용, 디렉토리 자동 생성
- `MemoryIndexManager`: 계층적 category 파싱
- API: category 필터에 prefix match 지원 (`?category=topics/programming` → 하위 포함)

**프론트엔드 변경**:
- 사이드바: 재귀적 트리 렌더링
- 카테고리 선택: 기존 dropdown → 트리 선택기 또는 자유 입력
- DraftEditor/NoteEditor: 카테고리 입력 UI 확장

---

#### 2.2 Drag & Drop Reorganization

**현재**: 사이드바에서 파일 클릭만 가능
**개선**: 사이드바에서 노트를 다른 카테고리로 드래그 이동

- `react-dnd` 또는 native HTML5 drag & drop
- 드래그 중 카테고리 폴더 하이라이트
- 드롭 시 `userOpsidianApi.updateFile(filename, { category: newCategory })` 호출
- 이동 결과 toast 알림

---

#### 2.3 Pinned Notes

**현재**: 없음
**개선**: 중요한 노트를 사이드바 상단에 고정

- 사이드바에 "Pinned" 섹션 추가
- 노트 우클릭 또는 pin 아이콘으로 토글
- pinned 상태는 `localStorage` 또는 별도 config에 저장
- Pinned 노트는 카테고리 트리 위에 항상 표시

---

#### 2.4 Sorting Options

**현재**: 수정일 기준 내림차순 고정
**개선**: 사이드바 상단에 정렬 옵션

| Sort | Key |
|------|-----|
| 수정일 (최신순) | `modified desc` (현재 기본) |
| 수정일 (오래된순) | `modified asc` |
| 생성일 | `created desc/asc` |
| 제목 (가나다순) | `title asc` |
| 중요도 | `importance` (critical → low) |
| 크기 | `char_count desc` |

---

### Phase 3: Keyboard Shortcuts

#### 3.1 Global Shortcut System

**현재**: 키보드 단축키 0개

**개선**: 전역 키보드 이벤트 시스템 구축

**구현 구조**:
```tsx
// useOpsidianShortcuts.ts — custom hook
useEffect(() => {
  const handler = (e: KeyboardEvent) => {
    const mod = e.ctrlKey || e.metaKey;
    // ... dispatch based on key combo
  };
  window.addEventListener('keydown', handler);
  return () => window.removeEventListener('keydown', handler);
}, [deps]);
```

#### 3.2 Shortcut Map

**Navigation**:

| Shortcut | Action |
|----------|--------|
| `Ctrl+P` / `Cmd+K` | Quick Search (파일명 검색 → 즉시 열기) |
| `Ctrl+O` | 파일 목록 포커스 |
| `Ctrl+Tab` | 다음 탭으로 이동 |
| `Ctrl+Shift+Tab` | 이전 탭으로 이동 |
| `Ctrl+W` | 현재 탭 닫기 |
| `Ctrl+\` | 사이드바 토글 |
| `Ctrl+Shift+\` | 우측 패널 토글 |
| `↑` / `↓` | 사이드바 파일 네비게이션 (사이드바 포커스 시) |
| `Enter` | 선택된 파일 열기 (사이드바 포커스 시) |

**View Modes**:

| Shortcut | Action |
|----------|--------|
| `Ctrl+1` | 에디터 뷰 |
| `Ctrl+2` | 그래프 뷰 |
| `Ctrl+3` | 검색 뷰 |

**Note Actions**:

| Shortcut | Action |
|----------|--------|
| `Ctrl+N` | 새 노트 생성 |
| `Ctrl+E` | 현재 노트 편집 모드 토글 |
| `Ctrl+S` | 저장 (편집 모드에서) |
| `Ctrl+Shift+D` | 현재 노트 삭제 (confirm 포함) |
| `Escape` | 편집 취소 / 모달 닫기 / 검색 닫기 |

**Editing** (편집 모드 textarea 내):

| Shortcut | Action |
|----------|--------|
| `Ctrl+B` | Bold 토글 |
| `Ctrl+I` | Italic 토글 |
| `Ctrl+L` | Wikilink 삽입 (노트 검색 팝업) |
| `Ctrl+K` | URL 링크 삽입 |
| `Ctrl+Shift+K` | 코드 블록 삽입 |
| `Tab` | 들여쓰기 (선택 영역 또는 현재 줄) |
| `Shift+Tab` | 내어쓰기 |

#### 3.3 Quick Switcher (Ctrl+P)

Obsidian의 핵심 UX. 모달 팝업으로 파일명을 fuzzy search하여 즉시 열기.

```
┌──────────────────────────────────┐
│  🔍 Search notes...              │
├──────────────────────────────────┤
│  📘 Python 비동기 프로그래밍    │  ← 키보드 하이라이트
│  📗 Rust 메모리 모델            │
│  📙 2026-04-06 일기             │
│  📕 프로젝트 GenY 로드맵       │
└──────────────────────────────────┘
```

- 파일명, 제목, 태그 대상 fuzzy match
- `↑` `↓` 로 선택, `Enter` 로 열기
- 최근 열었던 파일 우선 표시
- 결과 없을 시 "새 노트 만들기" 옵션

---

#### 3.4 Shortcut Help Panel

`Ctrl+/` 또는 `?` 로 전체 단축키 목록 모달 표시.

---

### Phase 4: Tag System

#### 4.1 Tag Autocomplete

**현재**: 태그 입력 시 자유 텍스트, 기존 태그 참조 불가
**개선**: 입력 중 기존 태그를 dropdown으로 제안

- `memoryIndex.tag_map` 에서 기존 태그 목록 추출
- 입력 중 prefix match로 제안
- `↑` `↓` + `Enter` 로 선택
- 쉼표 입력 시 태그 확정 → pill/chip UI로 표시

#### 4.2 Tag Chips UI

**현재**: 쉼표 구분 텍스트 (`"idea, project, important"`)
**개선**: 개별 태그를 chip/pill로 시각화

```
[ idea × ] [ project × ] [ important × ] [ + Add tag... ]
```

- 각 chip에 X 버튼으로 개별 삭제
- 드래그로 순서 변경 (선택 사항)
- 색상은 태그별 해시 기반 자동 배정 또는 카테고리별 고정

#### 4.3 Bulk Tag Operations

- 사이드바 태그 패널에서 태그 우클릭 → 이름 변경 / 삭제
- 태그 이름 변경 시 해당 태그를 가진 모든 노트 일괄 갱신
- 태그 병합: 두 태그를 하나로 합치기

**백엔드 필요**:
- `PUT /api/opsidian/tags/{tag_name}` — rename tag across all notes
- `DELETE /api/opsidian/tags/{tag_name}` — remove tag from all notes
- `POST /api/opsidian/tags/merge` — merge two tags

---

### Phase 5: Link & Reference

#### 5.1 Wikilink Picker (Ctrl+L)

**현재**: 사용자가 `[[note-name]]` 을 수동 타이핑해야 함
**개선**: `Ctrl+L` 또는 `[[` 입력 시 노트 검색 팝업

```
┌──────────────────────────────────┐
│  🔗 Link to note...              │
├──────────────────────────────────┤
│  📘 Python 비동기 프로그래밍    │
│  📗 Rust 메모리 모델            │
│  └ 별칭: |display text           │
└──────────────────────────────────┘
```

- 파일명 fuzzy search
- 선택 시 `[[filename|alias]]` 자동 삽입
- alias 입력 선택 가능

#### 5.2 Unlinked References

**현재**: 없음
**개선**: 노트 본문에서 다른 노트 제목이 언급되지만 `[[]]` 로 링크되지 않은 부분을 감지

- RightPanel에 "Unlinked References" 섹션 추가
- 각 항목에 "Link" 버튼 → 클릭 시 자동으로 `[[ ]]` 감싸기
- 백엔드: 본문 내 다른 노트 제목/별칭 매칭

#### 5.3 Backlink Context

**현재**: 백링크가 파일명만 표시
**개선**: 백링크 주변 텍스트(context)도 함께 표시

```
📎 Python 비동기 프로그래밍
   "...이 패턴은 [[FastAPI]] 에서 자주 사용되며..."
```

- 각 백링크 항목에 해당 `[[ ]]` 주변 ±50자 snippet 포함

---

### Phase 6: Note Templates

#### 6.1 Template System

**현재**: 모든 새 노트가 빈 상태에서 시작
**개선**: 카테고리별 또는 사용자 정의 템플릿 제공

**Built-in Templates**:

| Template | Content |
|----------|---------|
| **Daily Note** | `## Today\n\n## Tasks\n- [ ] \n\n## Notes\n\n## Reflection\n` |
| **Meeting Note** | `## Attendees\n\n## Agenda\n\n## Discussion\n\n## Action Items\n- [ ] ` |
| **Project** | `## Overview\n\n## Goals\n\n## Tasks\n\n## Timeline\n\n## Notes\n` |
| **Idea** | `## Concept\n\n## Why\n\n## How\n\n## Related\n` |
| **Reference** | `## Source\n\n## Summary\n\n## Key Points\n\n## Notes\n` |

**사용자 정의 템플릿**:
- 노트를 "템플릿으로 저장" 기능
- 새 노트 생성 시 템플릿 선택 dropdown
- 템플릿 관리 UI (생성/수정/삭제)

**저장 방식**: `_user_opsidian/{username}/_templates/` 디렉토리에 markdown 파일로 저장

---

### Phase 7: Search Enhancement

#### 7.1 Advanced Search Filters

**현재**: 텍스트 + 시맨틱 검색만, 필터 없음
**개선**:

```
🔍 [검색어                                          ]
    Category: [All ▼]  Importance: [All ▼]  Tag: [All ▼]
    Date Range: [From] ~ [To]   Sort: [Relevance ▼]
```

- 카테고리/중요도/태그 드롭다운 필터
- 날짜 범위 필터 (created/modified)
- 정렬 옵션 (관련성/날짜/제목)

#### 7.2 Search History

- 최근 검색어 5개 기록 (localStorage)
- 검색창 포커스 시 드롭다운으로 표시

---

### Phase 8: Import / Export

#### 8.1 Markdown Import

**현재**: 노트는 API 또는 에이전트 통해서만 생성
**개선**: `.md` 파일 드래그 앤 드롭 또는 파일 선택으로 대량 임포트

- 파일 선택기 또는 drop zone UI
- YAML frontmatter 자동 파싱 (존재 시)
- frontmatter 없는 경우 기본 metadata 적용
- 임포트 결과 요약 (성공/실패/건너뜀)

**백엔드 필요**:
- `POST /api/opsidian/import` — multipart file upload
- frontmatter 파싱 + note 생성

#### 8.2 Export

- 개별 노트 → `.md` 다운로드
- 전체 볼트 → `.zip` 다운로드 (폴더 구조 보존)
- 복사 버튼 (노트 본문 클립보드 복사)

---

### Phase 9: UX Polish

#### 9.1 Right-Click Context Menu

**현재**: 없음
**개선**: 사이드바 파일/태그/링크에 우클릭 메뉴

**파일 우클릭**:
```
📄 Open in New Tab
✏️ Rename
📁 Move to Category...
🔗 Copy Wikilink
📌 Pin / Unpin
🗑️ Delete
```

**태그 우클릭**:
```
✏️ Rename Tag
🔀 Merge with...
🗑️ Remove from All Notes
```

#### 9.2 Breadcrumb Navigation

**현재**: 파일 선택 시 경로 표시 없음
**개선**: 에디터 상단에 breadcrumb

```
User Vault > topics > programming > python-async.md
```

클릭 시 해당 카테고리 필터로 이동

#### 9.3 Recent Files

- StatusBar 또는 사이드바에 "최근 파일" 섹션
- 최근 열었던 10개 파일 (localStorage)
- 빠른 접근용

#### 9.4 Note Count per Tag in Editor

**현재**: 태그 패널에서만 파일 수 보임
**개선**: 노트 편집 시 태그 chip에 count 표시

```
[ python (12) × ] [ async (5) × ]
```

#### 9.5 Empty State Improvements

**현재**: "Select a note or create a new one" 만 표시
**개선**: 빈 상태에서 유용한 행동 유도

```
✨ Welcome to your vault!

[+ Create Note]  [📁 Import Files]  [⌨️ Shortcuts (Ctrl+/)]

Quick Start:
  📝 Daily Note (Ctrl+N)
  🔍 Search (Ctrl+P)
```

---

## Priority Matrix

| Phase | 항목 | 사용자 임팩트 | 구현 난이도 | 추천 순서 |
|-------|------|:---:|:---:|:---:|
| **3** | Keyboard Shortcuts | ★★★★★ | ★★☆ | **1st** |
| **1.1** | Markdown Toolbar | ★★★★★ | ★★☆ | **2nd** |
| **3.3** | Quick Switcher (Ctrl+P) | ★★★★★ | ★★☆ | **3rd** |
| **4.1** | Tag Autocomplete + Chips | ★★★★☆ | ★★☆ | **4th** |
| **5.1** | Wikilink Picker | ★★★★☆ | ★★☆ | **5th** |
| **2.1** | Custom Subcategory | ★★★★☆ | ★★★ | **6th** |
| **1.2** | Split Preview | ★★★☆☆ | ★★☆ | **7th** |
| **1.3** | Title Editing | ★★★☆☆ | ★★★ | **8th** |
| **6** | Note Templates | ★★★☆☆ | ★★☆ | **9th** |
| **9.1** | Context Menu | ★★★☆☆ | ★★☆ | **10th** |
| **2.2** | Drag & Drop | ★★☆☆☆ | ★★★ | **11th** |
| **7** | Advanced Search | ★★☆☆☆ | ★★☆ | **12th** |
| **5.2** | Unlinked References | ★★☆☆☆ | ★★★ | **13th** |
| **8** | Import / Export | ★★☆☆☆ | ★★★ | **14th** |
| **1.4** | Auto-save | ★★☆☆☆ | ★☆☆ | **15th** |
| **2.3** | Pinned Notes | ★★☆☆☆ | ★☆☆ | **16th** |
| **2.4** | Sorting Options | ★★☆☆☆ | ★☆☆ | **17th** |

---

## Implementation Notes

### Shared Components to Create

| Component | Used By | Purpose |
|-----------|---------|---------|
| `MarkdownToolbar.tsx` | NoteEditor, CuratedNoteEditor, DraftEditor | 마크다운 서식 버튼 |
| `useOpsidianShortcuts.ts` | All Opsidian views | 글로벌 키보드 단축키 hook |
| `QuickSwitcher.tsx` | All Opsidian views | Ctrl+P 파일 검색 모달 |
| `TagInput.tsx` | NoteEditor, DraftEditor | 태그 칩 + autocomplete |
| `WikilinkPicker.tsx` | Editor (Ctrl+L, `[[` trigger) | 노트 링크 검색 팝업 |
| `ContextMenu.tsx` | Sidebar files, tags, links | 우클릭 메뉴 |
| `ShortcutHelp.tsx` | Global (Ctrl+/) | 단축키 목록 모달 |

### Backend API Additions Needed

| Endpoint | Purpose | Phase |
|----------|---------|-------|
| `PUT /api/opsidian/files/{filename}` — title field | 제목 변경 + 파일 rename | 1.3 |
| `PUT /api/opsidian/tags/{tag}` | 태그 일괄 이름 변경 | 4.3 |
| `DELETE /api/opsidian/tags/{tag}` | 태그 일괄 삭제 | 4.3 |
| `POST /api/opsidian/tags/merge` | 태그 병합 | 4.3 |
| `GET /api/opsidian/unlinked?filename=X` | 미링크 참조 검색 | 5.2 |
| `POST /api/opsidian/import` | 마크다운 파일 임포트 | 8.1 |
| `GET /api/opsidian/export` | 볼트 zip 내보내기 | 8.2 |
| `GET /api/opsidian/templates` | 템플릿 목록 | 6.1 |
| `POST /api/opsidian/templates` | 템플릿 저장 | 6.1 |
