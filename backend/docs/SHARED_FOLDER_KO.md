# Shared Folder

> 세션 간 파일 공유를 위한 공유 디렉토리 — 심볼릭 링크 + REST API

## 아키텍처 개요

```
SharedFolderManager (싱글턴)
    │
    ├── 공유 폴더       ── {STORAGE_ROOT}/_shared/
    │
    ├── 세션 링크       ── {session_storage}/_shared → 공유 폴더
    │   ├── Windows: mklink /J (디렉토리 정션, 관리자 불필요)
    │   └── Unix: Path.symlink_to()
    │
    └── REST API        ── /api/shared-folder/ (파일 CRUD + 업·다운로드)
```

---

## 동작 원리

### 세션 간 파일 교환

1. 세션 생성 시 `link_to_session(session_storage_path)` 호출
2. `{session_storage}/_shared` → 전역 공유 폴더로 심볼릭 링크/정션 생성
3. 모든 Claude CLI 세션이 작업 디렉토리에서 `_shared/` 접근 가능
4. 한 세션이 넣은 파일이 다른 모든 세션에서 즉시 가시

### 보안

모든 파일 연산 전 `_validate_path(relative_path)`:

```python
target = (shared_root / relative_path).resolve()
target.relative_to(shared_root)  # ValueError → None 반환
```

디렉토리 트래버설 공격 방지 (`../../etc/passwd` 차단).

---

## SharedFolderManager

### 경로 해석 우선순위

1. 생성자 `shared_path` 인자
2. 환경변수 `GENY_SHARED_FOLDER_PATH`
3. 기본값: `{DEFAULT_STORAGE_ROOT}/_shared`

### 파일 연산

| 메서드 | 반환 | 설명 |
|--------|------|------|
| `list_files(subpath="")` | `List[Dict]` | 파일 목록 (`name`, `path`, `is_dir`, `size`, `modified_at`) |
| `read_file(file_path, encoding)` | `Optional[Dict]` | 파일 읽기 (`file_path`, `content`, `size`, `encoding`) |
| `write_file(file_path, content, overwrite)` | `Dict` | 파일 쓰기 (부모 디렉토리 자동 생성) |
| `write_binary(file_path, data, overwrite)` | `Dict` | 바이너리 쓰기 |
| `delete_file(file_path)` | `bool` | 파일/디렉토리 삭제 (`shutil.rmtree` 사용) |
| `create_directory(dir_path)` | `Dict` | 디렉토리 생성 (재귀) |
| `get_info()` | `Dict` | 정보 (`path`, `exists`, `total_files`, `total_size`) |

### 세션 링크

| 메서드 | 설명 |
|--------|------|
| `link_to_session(session_storage_path, link_name="_shared")` | 심볼릭 링크/정션 생성 (기존 스테일 링크 자동 제거) |
| `unlink_from_session(session_storage_path, link_name="_shared")` | 링크 제거 |
| `update_path(new_path)` | 경로 변경 (파일 마이그레이션 없음) |

### 글로벌 접근

```python
get_shared_folder_manager()     # 지연 싱글턴
reset_shared_folder_manager()   # 싱글턴 리셋
```

---

## REST API

라우터 접두사: `/api/shared-folder`

| Method | 엔드포인트 | 설명 |
|--------|-----------|------|
| `GET` | `/info` | 공유 폴더 메타데이터 (경로, 존재여부, 파일 수, 크기) |
| `GET` | `/files?path=` | 파일 목록 (하위 경로 필터) |
| `GET` | `/files/{file_path}?encoding=` | 파일 읽기 |
| `POST` | `/files` | 파일 쓰기 (`{"file_path", "content", "encoding", "overwrite"}`) |
| `DELETE` | `/files/{file_path}` | 파일/디렉토리 삭제 |
| `POST` | `/upload` | 멀티파트 바이너리 업로드 |
| `POST` | `/directory` | 디렉토리 생성 |
| `GET` | `/download` | 전체 공유 폴더 ZIP 다운로드 (gitignore 인식 필터) |

---

## Config 연동

`SharedFolderConfig` 설정 변경 시:
- `enabled` 변경 → `apply_change` 콜백으로 기능 활성화/비활성화
- `shared_folder_path` 변경 → 실행 중인 `SharedFolderManager` 인스턴스 경로 갱신

자세한 설정은 [CONFIG.md](CONFIG.md) 참조.

---

## 관련 파일

```
service/shared_folder/
├── __init__.py              # 공개 API 내보내기
└── manager.py               # SharedFolderManager

controller/shared_folder_controller.py  # REST API 라우터
```
