# Shared Folder

> Shared directory for inter-session file sharing — symlinks + REST API

## Architecture Overview

```
SharedFolderManager (singleton)
    │
    ├── Shared folder      ── {STORAGE_ROOT}/_shared/
    │
    ├── Session links      ── {session_storage}/_shared → shared folder
    │   ├── Windows: mklink /J (directory junction, no admin required)
    │   └── Unix: Path.symlink_to()
    │
    └── REST API           ── /api/shared-folder/ (file CRUD + upload/download)
```

---

## How It Works

### Inter-Session File Exchange

1. On session creation, `link_to_session(session_storage_path)` is called
2. Creates symlink/junction: `{session_storage}/_shared` → global shared folder
3. All Claude CLI sessions can access `_shared/` from their working directory
4. Files placed by one session are immediately visible to all other sessions

### Security

All file operations first call `_validate_path(relative_path)`:

```python
target = (shared_root / relative_path).resolve()
target.relative_to(shared_root)  # ValueError → return None
```

Prevents directory traversal attacks (`../../etc/passwd` blocked).

---

## SharedFolderManager

### Path Resolution Priority

1. Constructor `shared_path` argument
2. Environment variable `GENY_SHARED_FOLDER_PATH`
3. Default: `{DEFAULT_STORAGE_ROOT}/_shared`

### File Operations

| Method | Return | Description |
|--------|--------|-------------|
| `list_files(subpath="")` | `List[Dict]` | File list (`name`, `path`, `is_dir`, `size`, `modified_at`) |
| `read_file(file_path, encoding)` | `Optional[Dict]` | Read file (`file_path`, `content`, `size`, `encoding`) |
| `write_file(file_path, content, overwrite)` | `Dict` | Write file (auto-creates parent directories) |
| `write_binary(file_path, data, overwrite)` | `Dict` | Binary write |
| `delete_file(file_path)` | `bool` | Delete file/directory (uses `shutil.rmtree`) |
| `create_directory(dir_path)` | `Dict` | Create directory (recursive) |
| `get_info()` | `Dict` | Info (`path`, `exists`, `total_files`, `total_size`) |

### Session Links

| Method | Description |
|--------|-------------|
| `link_to_session(session_storage_path, link_name="_shared")` | Create symlink/junction (auto-removes stale links) |
| `unlink_from_session(session_storage_path, link_name="_shared")` | Remove link |
| `update_path(new_path)` | Update path (no file migration) |

### Global Access

```python
get_shared_folder_manager()     # Lazy singleton
reset_shared_folder_manager()   # Reset singleton
```

---

## REST API

Router prefix: `/api/shared-folder`

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/info` | Shared folder metadata (path, exists, file count, size) |
| `GET` | `/files?path=` | File list (subpath filter) |
| `GET` | `/files/{file_path}?encoding=` | Read file |
| `POST` | `/files` | Write file (`{"file_path", "content", "encoding", "overwrite"}`) |
| `DELETE` | `/files/{file_path}` | Delete file/directory |
| `POST` | `/upload` | Multipart binary upload |
| `POST` | `/directory` | Create directory |
| `GET` | `/download` | Download entire shared folder as ZIP (gitignore-aware filter) |

---

## Config Integration

When `SharedFolderConfig` settings change:
- `enabled` change → `apply_change` callback enables/disables feature
- `shared_folder_path` change → updates running `SharedFolderManager` instance path

See [CONFIG.md](CONFIG.md) for detailed settings.

---

## Related Files

```
service/shared_folder/
├── __init__.py              # Public API exports
└── manager.py               # SharedFolderManager

controller/shared_folder_controller.py  # REST API router
```
