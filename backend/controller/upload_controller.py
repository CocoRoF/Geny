"""Upload controller — multipart file/image uploads for chat attachments.

Files are stored under ``backend/static/uploads/<sha256-prefix>/<sha256>.<ext>``
with content-addressable hashing so duplicates are de-duplicated server-side.
The returned ``url`` is a stable HTTP URL (``/static/uploads/...``) suitable
for direct embedding in chat messages or for passing to
``geny-executor`` as an ``attachments[].url`` reference.

Limits / policy
---------------
- Max single file size: ``MAX_UPLOAD_BYTES`` (default 10 MiB).
- Allowed image MIME types: PNG, JPEG, WEBP, GIF, HEIC.
- Other file types are accepted but routed as ``kind=file`` on the
  client side. PDF / docx / etc. are TODO: their text extraction and
  multimodal handling is not implemented yet (see ``geny_executor``
  ``s01_input.MultimodalNormalizer._make_file_block``).
- Per-user / per-room rate limiting is TODO (Phase 4+).
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from service.auth.auth_middleware import require_auth

logger = logging.getLogger("upload-controller")

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Configuration
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB hard cap per file

ALLOWED_IMAGE_MIMES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
        "image/heic",
        "image/heif",
    }
)

# 파일 처리는 P1 스코프에선 모양만 잡아둔다 (TODO). 일단 image 외 타입도
# 업로드 자체는 허용하되 클라이언트가 ``kind=file`` 로 라우팅한다.
ALLOWED_FILE_MIMES = frozenset(
    {
        "application/pdf",
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/json",
        "application/zip",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)


# ``backend/static/uploads`` — created lazily on first upload.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_UPLOAD_ROOT = _BACKEND_DIR / "static" / "uploads"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Schemas
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class UploadedFile(BaseModel):
    """Single upload result returned to the client."""

    attachment_id: str  # sha256 hex digest
    kind: str  # "image" | "file"
    name: str  # original filename
    mime_type: str
    size: int
    sha256: str
    url: str  # absolute path served by the static mount, e.g. "/static/uploads/ab/abcd...png"


class UploadResponse(BaseModel):
    files: List[UploadedFile]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _ext_for(mime: str, original_name: str) -> str:
    """Pick a file extension. Prefer the original name's, fall back to MIME."""
    _, ext = os.path.splitext(original_name)
    if ext and len(ext) <= 8:
        return ext.lower()
    guess = mimetypes.guess_extension(mime) or ""
    return guess.lower()


def _classify(mime: str) -> str:
    if mime in ALLOWED_IMAGE_MIMES:
        return "image"
    return "file"


def _validate_mime(mime: str) -> None:
    if mime in ALLOWED_IMAGE_MIMES:
        return
    if mime in ALLOWED_FILE_MIMES:
        # TODO: 본격적인 파일 파이프라인 구현 (텍스트 추출, OCR, chunking).
        # 지금은 업로드 + URL 발급만 지원하고, executor 측은 메타데이터만
        # 노출한다.
        return
    raise HTTPException(
        status_code=415,
        detail=f"Unsupported media type: {mime}",
    )


async def _store_one(upload: UploadFile) -> UploadedFile:
    if not upload.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    mime = upload.content_type or mimetypes.guess_type(upload.filename)[0] or "application/octet-stream"
    _validate_mime(mime)

    # Hash + size in a single streaming pass — never load > MAX bytes into RAM.
    hasher = hashlib.sha256()
    size = 0
    chunks: list[bytes] = []
    while True:
        chunk = await upload.read(1024 * 64)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds {MAX_UPLOAD_BYTES} bytes",
            )
        hasher.update(chunk)
        chunks.append(chunk)

    sha = hasher.hexdigest()
    ext = _ext_for(mime, upload.filename)
    shard = sha[:2]
    target_dir = _UPLOAD_ROOT / shard
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{sha}{ext}"

    # Content-addressable: if the file already exists, skip the rewrite.
    if not target_path.exists():
        with open(target_path, "wb") as f:
            for chunk in chunks:
                f.write(chunk)

    url = f"/static/uploads/{shard}/{sha}{ext}"
    return UploadedFile(
        attachment_id=sha,
        kind=_classify(mime),
        name=upload.filename,
        mime_type=mime,
        size=size,
        sha256=sha,
        url=url,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Endpoints
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("", response_model=UploadResponse)
@router.post("/", response_model=UploadResponse)
async def upload_files(
    request: Request,
    files: List[UploadFile] = File(...),
    auth: dict = Depends(require_auth),
) -> UploadResponse:
    """Multipart upload of one or more files.

    Returns a stable ``attachment_id`` (sha256) and a ``/static/uploads/...``
    URL that the client can embed in chat broadcasts as
    ``attachments[].url`` / ``attachments[].attachment_id``.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    if len(files) > 16:
        raise HTTPException(status_code=400, detail="Too many files (max 16 per request)")

    out: list[UploadedFile] = []
    for f in files:
        out.append(await _store_one(f))
    logger.info(
        "uploads: user=%s saved %d file(s) (%d bytes total)",
        auth.get("sub"),
        len(out),
        sum(o.size for o in out),
    )
    return UploadResponse(files=out)
