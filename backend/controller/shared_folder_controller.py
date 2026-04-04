"""
Shared Folder Controller

REST API endpoints for the shared folder feature.
All sessions share access to a common folder for file exchange.

Endpoints:
    GET    /api/shared-folder/info            — shared folder info (path, stats)
    GET    /api/shared-folder/files            — list files
    GET    /api/shared-folder/files/{path}     — read file content
    POST   /api/shared-folder/files            — write / create a file
    DELETE /api/shared-folder/files/{path}     — delete a file or directory
    POST   /api/shared-folder/upload           — upload a file (multipart)
    POST   /api/shared-folder/directory        — create a directory
    GET    /api/shared-folder/download         — download as ZIP
"""

import io
import os
import zipfile
from logging import getLogger
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from service.auth.auth_middleware import require_auth
from service.shared_folder import get_shared_folder_manager

logger = getLogger(__name__)

router = APIRouter(prefix="/api/shared-folder", tags=["shared-folder"])


# ============================================================================
# Request / Response Models
# ============================================================================


class SharedFolderInfoResponse(BaseModel):
    """Shared folder metadata."""
    path: str
    exists: bool
    total_files: int
    total_size: int


class SharedFileItem(BaseModel):
    """Single file entry."""
    name: str
    path: str
    is_dir: bool = False
    size: int = 0
    modified_at: Optional[str] = None


class SharedFileListResponse(BaseModel):
    """File listing response."""
    shared_path: str
    files: list[SharedFileItem]
    total: int


class SharedFileContentResponse(BaseModel):
    """File content response."""
    file_path: str
    content: str
    size: int
    encoding: str = "utf-8"


class WriteFileRequest(BaseModel):
    """Write / create file request."""
    file_path: str = Field(..., description="Relative path within the shared folder")
    content: str = Field(..., description="File content (string)")
    encoding: str = Field(default="utf-8", description="File encoding")
    overwrite: bool = Field(default=True, description="Overwrite if exists")


class WriteFileResponse(BaseModel):
    """Write file response."""
    success: bool
    file_path: str
    size: int
    created_at: str


class CreateDirectoryRequest(BaseModel):
    """Create directory request."""
    path: str = Field(..., description="Relative directory path to create")


class CreateDirectoryResponse(BaseModel):
    """Create directory response."""
    success: bool
    path: str
    created_at: str


class DeleteResponse(BaseModel):
    """Delete file / directory response."""
    success: bool
    path: str


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/info", response_model=SharedFolderInfoResponse)
async def get_shared_folder_info():
    """
    Get shared folder metadata.

    Returns path, existence, file count, and total size.
    """
    mgr = get_shared_folder_manager()
    info = mgr.get_info()
    return SharedFolderInfoResponse(**info)


@router.get("/files", response_model=SharedFileListResponse)
async def list_shared_files(
    path: str = Query("", description="Subdirectory path (empty for root)")
):
    """
    List files in the shared folder.
    """
    mgr = get_shared_folder_manager()
    files_data = mgr.list_files(subpath=path)

    files = [
        SharedFileItem(
            name=f["name"],
            path=f["path"],
            is_dir=f.get("is_dir", False),
            size=f.get("size", 0),
            modified_at=f["modified_at"].isoformat() if f.get("modified_at") else None,
        )
        for f in files_data
    ]

    return SharedFileListResponse(
        shared_path=mgr.shared_path,
        files=files,
        total=len(files),
    )


@router.get("/files/{file_path:path}", response_model=SharedFileContentResponse)
async def read_shared_file(
    file_path: str,
    encoding: str = Query("utf-8", description="File encoding"),
):
    """
    Read a file from the shared folder.
    """
    mgr = get_shared_folder_manager()
    result = mgr.read_file(file_path, encoding=encoding)

    if not result:
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    return SharedFileContentResponse(
        file_path=result["file_path"],
        content=result["content"],
        size=result["size"],
        encoding=result["encoding"],
    )


@router.post("/files", response_model=WriteFileResponse)
async def write_shared_file(request: WriteFileRequest, auth: dict = Depends(require_auth)):
    """
    Write or create a file in the shared folder.
    """
    mgr = get_shared_folder_manager()

    try:
        result = mgr.write_file(
            file_path=request.file_path,
            content=request.content,
            encoding=request.encoding,
            overwrite=request.overwrite,
        )
        return WriteFileResponse(
            success=True,
            file_path=result["file_path"],
            size=result["size"],
            created_at=result["created_at"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to write file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/files/{file_path:path}", response_model=DeleteResponse)
async def delete_shared_file(file_path: str, auth: dict = Depends(require_auth)):
    """
    Delete a file or directory from the shared folder.
    """
    mgr = get_shared_folder_manager()
    deleted = mgr.delete_file(file_path)

    if not deleted:
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    return DeleteResponse(success=True, path=file_path)


@router.post("/upload", response_model=WriteFileResponse)
async def upload_shared_file(
    file: UploadFile = File(...),
    path: str = Query("", description="Subdirectory to place the file in"),
    overwrite: bool = Query(True, description="Overwrite if exists"),
    auth: dict = Depends(require_auth),
):
    """
    Upload a file to the shared folder (multipart form).
    """
    mgr = get_shared_folder_manager()

    filename = file.filename or "uploaded_file"
    relative_path = f"{path}/{filename}" if path else filename

    try:
        data = await file.read()
        result = mgr.write_binary(
            file_path=relative_path,
            data=data,
            overwrite=overwrite,
        )
        return WriteFileResponse(
            success=True,
            file_path=result["file_path"],
            size=result["size"],
            created_at=result["created_at"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/directory", response_model=CreateDirectoryResponse)
async def create_shared_directory(request: CreateDirectoryRequest, auth: dict = Depends(require_auth)):
    """
    Create a directory in the shared folder.
    """
    mgr = get_shared_folder_manager()

    try:
        result = mgr.create_directory(request.path)
        return CreateDirectoryResponse(
            success=True,
            path=result["path"],
            created_at=result["created_at"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/download")
async def download_shared_folder():
    """
    Download the entire shared folder as a ZIP archive.
    """
    mgr = get_shared_folder_manager()
    folder = mgr.shared_path

    if not os.path.isdir(folder):
        raise HTTPException(status_code=404, detail="Shared folder does not exist")

    # Build ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        from service.claude_manager.storage_utils import (
            DEFAULT_IGNORE_PATTERNS,
            load_gitignore_patterns,
            should_ignore_path,
        )

        ignore_patterns = list(DEFAULT_IGNORE_PATTERNS) + load_gitignore_patterns(folder)
        from pathlib import Path as FilePath
        root = FilePath(folder)

        for item in root.rglob("*"):
            if not item.is_file():
                continue
            rel = str(item.relative_to(root)).replace("\\", "/")
            if should_ignore_path(rel, ignore_patterns):
                continue
            zf.write(item, arcname=rel)

    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=shared-folder.zip"
        },
    )
