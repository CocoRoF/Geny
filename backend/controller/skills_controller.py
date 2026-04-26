"""Skills Controller — REST API for the SKILL.md registry (G7.4).

Read-only endpoint that surfaces every loaded skill (bundled + user)
so the frontend slash-command panel knows which ``/<skill-id>``
commands resolve. The actual SkillTool invocation happens through
the regular tool_use path (the frontend rewrites ``/<skill-id> args``
into a ``skill__<id>`` tool call before sending the prompt).

PR-F.2.1 added a single-skill detail endpoint (``GET /{skill_id}``)
returning frontmatter + body for the SkillPanel chip detail modal.
PR-F.2.3 added user-skill CRUD (``POST/PUT/DELETE /user``) so the
SkillsTab editor can write into ``~/.geny/skills/`` without leaving
the UI.
"""

from __future__ import annotations

import re
from logging import getLogger
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from controller.auth_controller import require_auth
from service.skills import list_skills, user_skills_dir

logger = getLogger(__name__)

router = APIRouter(prefix="/api/skills", tags=["skills"])


class SkillSummary(BaseModel):
    id: Optional[str] = Field(None, description="Skill id — used as slash command")
    name: Optional[str] = Field(None, description="Display name")
    description: Optional[str] = Field(None, description="Short description")
    model: Optional[str] = Field(None, description="Optional model override")
    allowed_tools: List[str] = Field(default_factory=list)
    # PR-D.3.3 — richer SKILL.md schema fields shipped in executor 1.2.0
    # (PR-B.4.1). Optional + default so older skills without these
    # fields still serialise cleanly.
    category: Optional[str] = Field(None, description="Discovery category")
    effort: Optional[str] = Field(None, description="Token+time hint: low|medium|high")
    examples: List[str] = Field(default_factory=list, description="Example invocations")


class SkillListResponse(BaseModel):
    skills: List[SkillSummary]


@router.get("/list", response_model=SkillListResponse)
async def list_skills_endpoint(_auth: dict = Depends(require_auth)):
    """Return every skill currently registered for this Geny instance.

    Bundled skills always appear; user skills (under ``~/.geny/skills/``)
    appear only when ``GENY_ALLOW_USER_SKILLS=1`` was set when the
    process started — the env var is read at request time so a
    re-export takes effect on the next call without process restart.
    """
    return SkillListResponse(skills=[_to_summary(s) for s in list_skills()])


# ── Single-skill detail (PR-F.2.1) ─────────────────────────────────


class SkillDetailResponse(BaseModel):
    id: str
    name: Optional[str] = None
    description: Optional[str] = None
    model: Optional[str] = None
    allowed_tools: List[str] = Field(default_factory=list)
    category: Optional[str] = None
    effort: Optional[str] = None
    examples: List[str] = Field(default_factory=list)
    body: str = Field(
        "",
        description="The markdown body of SKILL.md (frontmatter excluded).",
    )
    source: Optional[str] = Field(
        None,
        description="Path the skill was loaded from. None for in-code bundled skills.",
    )
    is_user_skill: bool = Field(
        False,
        description="True when the skill lives under ~/.geny/skills/ (editable).",
    )


def _resolve_skill_object(skill_id: str):
    """Return the live ``Skill`` instance for ``skill_id`` or None."""
    try:
        from service.skills.install import install_skill_registry
    except Exception:
        return None
    _, skills = install_skill_registry()
    for s in skills:
        if getattr(s, "id", None) == skill_id:
            return s
    return None


@router.get("/{skill_id}", response_model=SkillDetailResponse)
async def get_skill(skill_id: str, _auth: dict = Depends(require_auth)):
    """Return one skill's metadata + body (PR-F.2.1).

    Used by the SkillPanel chip detail modal. The body is the markdown
    after the frontmatter — i.e. what the LLM sees when the skill is
    invoked.
    """
    skill = _resolve_skill_object(skill_id)
    if skill is None:
        raise HTTPException(404, f"Skill not found: {skill_id}")
    metadata = getattr(skill, "metadata", None)

    def _get(name: str, default=None):
        if metadata is not None and hasattr(metadata, name):
            return getattr(metadata, name)
        return getattr(skill, name, default)

    src = getattr(skill, "source", None)
    src_path = str(src) if src else None
    user_dir = str(user_skills_dir())
    is_user = bool(src_path and src_path.startswith(user_dir))

    return SkillDetailResponse(
        id=str(getattr(skill, "id", skill_id)),
        name=_get("name"),
        description=_get("description"),
        model=_get("model_override") or getattr(skill, "model", None),
        allowed_tools=list(_get("allowed_tools", []) or []),
        category=_get("category"),
        effort=_get("effort"),
        examples=list(_get("examples", []) or []),
        body=getattr(skill, "body", "") or "",
        source=src_path,
        is_user_skill=is_user,
    )


# ── User-skill CRUD (PR-F.2.3) ─────────────────────────────────────
#
# Writes only to ``~/.geny/skills/<id>/SKILL.md``. Bundled skills are
# read-only. The opt-in env GENY_ALLOW_USER_SKILLS still gates whether
# user skills are *loaded*, but the editor lets operators prepare them
# either way.


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


class UserSkillUpsertRequest(BaseModel):
    id: str = Field(..., min_length=2, max_length=64)
    name: str
    description: str
    body: str = ""
    model_override: Optional[str] = None
    allowed_tools: List[str] = Field(default_factory=list)
    category: Optional[str] = None
    effort: Optional[str] = None
    examples: List[str] = Field(default_factory=list)
    # K.1 (cycle 20260426_2) — fields previously omitted but supported
    # by ``geny_executor.skills.SkillMetadata``.
    version: Optional[str] = None
    execution_mode: Optional[str] = Field(
        None,
        description='"inline" | "fork" — defaults to "inline" if absent',
    )
    extras: dict = Field(
        default_factory=dict,
        description="Free-form host-specific metadata persisted as YAML",
    )


class UserSkillUpsertResponse(BaseModel):
    id: str
    path: str


def _user_skill_path(skill_id: str) -> Path:
    if not _ID_RE.match(skill_id):
        raise HTTPException(
            400,
            f"invalid skill id {skill_id!r}; use lower-case alnum/dash/underscore (2-64 chars)",
        )
    return user_skills_dir() / skill_id / "SKILL.md"


_VALID_EXECUTION_MODES = {"inline", "fork"}


def _build_skill_md(req: UserSkillUpsertRequest) -> str:
    """Emit a SKILL.md body from the upsert request. YAML
    frontmatter + markdown body (or empty body).

    K.1 (cycle 20260426_2): emits ``version``, ``execution_mode``, and
    ``extras`` when supplied. Extras are written as a nested YAML
    mapping so the executor's frontmatter parser preserves them.
    """
    if req.execution_mode and req.execution_mode not in _VALID_EXECUTION_MODES:
        raise HTTPException(
            400,
            f"execution_mode must be one of {sorted(_VALID_EXECUTION_MODES)} or empty; "
            f"got {req.execution_mode!r}",
        )
    fm_lines: List[str] = ["---"]
    fm_lines.append(f"name: {req.name}")
    fm_lines.append(f"description: {req.description}")
    if req.version:
        fm_lines.append(f"version: {req.version}")
    if req.execution_mode:
        fm_lines.append(f"execution_mode: {req.execution_mode}")
    if req.model_override:
        fm_lines.append(f"model_override: {req.model_override}")
    if req.allowed_tools:
        fm_lines.append("allowed_tools:")
        for tool in req.allowed_tools:
            fm_lines.append(f"  - {tool}")
    if req.category:
        fm_lines.append(f"category: {req.category}")
    if req.effort:
        fm_lines.append(f"effort: {req.effort}")
    if req.examples:
        fm_lines.append("examples:")
        for ex in req.examples:
            fm_lines.append(f"  - {ex}")
    if req.extras:
        # Nested mapping; only string keys / scalar values supported in
        # this minimal serialiser. Operators with deeper structures
        # should still hand-edit the SKILL.md.
        fm_lines.append("extras:")
        for k, v in req.extras.items():
            if not isinstance(k, str):
                continue
            if isinstance(v, (str, int, float, bool)):
                fm_lines.append(f"  {k}: {v}")
            else:
                # Skip unsupported shapes silently — operator can edit
                # the file by hand for nested structures.
                continue
    fm_lines.append("---")
    body = req.body.strip()
    return "\n".join(fm_lines) + ("\n\n" + body + "\n" if body else "\n")


@router.post("/user", response_model=UserSkillUpsertResponse)
async def create_user_skill(
    req: UserSkillUpsertRequest,
    _auth: dict = Depends(require_auth),
):
    path = _user_skill_path(req.id)
    if path.exists():
        raise HTTPException(409, f"skill {req.id!r} already exists at {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_build_skill_md(req), encoding="utf-8")
    return UserSkillUpsertResponse(id=req.id, path=str(path))


@router.put("/user/{skill_id}", response_model=UserSkillUpsertResponse)
async def replace_user_skill(
    skill_id: str,
    req: UserSkillUpsertRequest,
    _auth: dict = Depends(require_auth),
):
    if req.id != skill_id:
        raise HTTPException(400, "URL skill_id differs from body id")
    path = _user_skill_path(skill_id)
    if not path.exists():
        raise HTTPException(404, f"skill {skill_id!r} not found at {path}")
    path.write_text(_build_skill_md(req), encoding="utf-8")
    return UserSkillUpsertResponse(id=skill_id, path=str(path))


@router.delete("/user/{skill_id}")
async def delete_user_skill(
    skill_id: str,
    _auth: dict = Depends(require_auth),
):
    path = _user_skill_path(skill_id)
    if not path.exists():
        raise HTTPException(404, f"skill {skill_id!r} not found at {path}")
    path.unlink()
    # Drop the now-empty directory if there's nothing else in it.
    try:
        if path.parent.exists() and not any(path.parent.iterdir()):
            path.parent.rmdir()
    except OSError:
        pass
    return {"deleted": True, "id": skill_id}


def _to_summary(skill_dict: dict) -> SkillSummary:
    """Map a list_skills() row into the API model. The row may carry
    extra keys (extras / source / etc.) — pydantic ignores them, so
    we only need to coerce the few that have type-divergent shapes."""
    examples_raw = skill_dict.get("examples")
    if isinstance(examples_raw, tuple):
        examples = list(examples_raw)
    elif isinstance(examples_raw, list):
        examples = examples_raw
    else:
        examples = []
    return SkillSummary(
        id=skill_dict.get("id"),
        name=skill_dict.get("name"),
        description=skill_dict.get("description"),
        model=skill_dict.get("model"),
        allowed_tools=list(skill_dict.get("allowed_tools") or []),
        category=skill_dict.get("category"),
        effort=skill_dict.get("effort"),
        examples=examples,
    )
