"""
부트스트랩 컨텍스트 파일 로더

OpenClaw의 resolveBootstrapContextFiles() 패턴을 참고하여
작업 디렉토리에서 프로젝트 컨텍스트 파일을 자동 탐색/로드합니다.

탐색 대상:
- AGENTS.md: 에이전트 관련 프로젝트 지침
- CLAUDE.md: Claude 전용 지침
- README.md: 프로젝트 설명 (선택적)
- .cursorrules / .windsurfrules 등: AI 지침 파일
"""

from __future__ import annotations

from logging import getLogger
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = getLogger(__name__)

# 자동 탐색할 파일 목록 (우선순위 순)
DEFAULT_CONTEXT_FILES: List[Tuple[str, str, int]] = [
    # (파일명, XML 태그, 최대 크기 bytes)
    ("AGENTS.md", "project-context", 50_000),
    ("CLAUDE.md", "ai-instructions", 50_000),
    (".claude", "ai-instructions", 50_000),
    (".cursorrules", "ai-instructions", 30_000),
    (".windsurfrules", "ai-instructions", 30_000),
    ("SOUL.md", "persona", 20_000),
]

# README.md는 명시적 요청 시에만 포함 (크기가 클 수 있음)
OPTIONAL_CONTEXT_FILES: List[Tuple[str, str, int]] = [
    ("README.md", "project-readme", 30_000),
    ("CONTRIBUTING.md", "project-contributing", 20_000),
]


class ContextLoader:
    """프로젝트 컨텍스트 파일 로더.

    작업 디렉토리에서 에이전트에게 유용한 프로젝트 컨텍스트 파일을
    자동으로 탐색하고 로드합니다.

    사용법:
        loader = ContextLoader(working_dir="/path/to/project")
        context_files = loader.load_context_files()
        # Returns: {"AGENTS.md": "file content...", "CLAUDE.md": "..."}
    """

    def __init__(
        self,
        working_dir: str,
        max_total_size: int = 100_000,
        include_readme: bool = False,
        custom_files: Optional[List[str]] = None,
    ):
        """
        Args:
            working_dir: 프로젝트 작업 디렉토리
            max_total_size: 전체 컨텍스트 파일 최대 크기 (bytes)
            include_readme: README.md를 포함할지 여부
            custom_files: 추가로 로드할 파일 경로 목록
        """
        self._working_dir = Path(working_dir)
        self._max_total_size = max_total_size
        self._include_readme = include_readme
        self._custom_files = custom_files or []

    def load_context_files(self) -> Dict[str, str]:
        """프로젝트 컨텍스트 파일을 자동 탐색하고 로드.

        Returns:
            {파일명: 내용} 딕셔너리
        """
        result: Dict[str, str] = {}
        total_size = 0

        # 1. 기본 컨텍스트 파일 탐색
        for filename, tag, max_size in DEFAULT_CONTEXT_FILES:
            content = self._try_load_file(filename, max_size)
            if content and (total_size + len(content)) <= self._max_total_size:
                result[filename] = content
                total_size += len(content)
                logger.info(f"Loaded context file: {filename} ({len(content)} chars)")

        # 2. 선택적 파일 (README.md 등)
        if self._include_readme:
            for filename, tag, max_size in OPTIONAL_CONTEXT_FILES:
                content = self._try_load_file(filename, max_size)
                if content and (total_size + len(content)) <= self._max_total_size:
                    result[filename] = content
                    total_size += len(content)
                    logger.info(f"Loaded optional context file: {filename} ({len(content)} chars)")

        # 3. 커스텀 파일
        for filepath in self._custom_files:
            content = self._try_load_file(filepath, 50_000)
            if content and (total_size + len(content)) <= self._max_total_size:
                result[filepath] = content
                total_size += len(content)
                logger.info(f"Loaded custom context file: {filepath} ({len(content)} chars)")

        logger.info(
            f"ContextLoader: loaded {len(result)} files, "
            f"total {total_size} chars from {self._working_dir}"
        )

        return result

    def get_context_file_tags(self) -> Dict[str, str]:
        """파일명→XML태그 매핑 반환."""
        mapping = {}
        for filename, tag, _ in DEFAULT_CONTEXT_FILES + OPTIONAL_CONTEXT_FILES:
            mapping[filename] = tag
        return mapping

    def _try_load_file(self, filename: str, max_size: int) -> Optional[str]:
        """파일을 안전하게 로드. 존재하지 않거나 크기 초과 시 None."""
        filepath = self._working_dir / filename

        # 상위 디렉토리도 탐색 (monorepo 패턴)
        if not filepath.exists():
            parent = self._working_dir.parent / filename
            if parent.exists():
                filepath = parent
            else:
                return None

        try:
            # 크기 확인
            file_size = filepath.stat().st_size
            if file_size > max_size:
                logger.warning(
                    f"Context file too large, skipping: {filename} "
                    f"({file_size} > {max_size} bytes)"
                )
                return None
            if file_size == 0:
                return None

            # 파일 읽기
            content = filepath.read_text(encoding="utf-8")
            return content.strip()

        except (OSError, UnicodeDecodeError) as e:
            logger.warning(f"Failed to load context file {filename}: {e}")
            return None

    def list_available_files(self) -> List[Dict[str, str]]:
        """사용 가능한 컨텍스트 파일 목록 반환 (디버깅용)."""
        available = []

        all_files = DEFAULT_CONTEXT_FILES + OPTIONAL_CONTEXT_FILES
        for filename, tag, max_size in all_files:
            filepath = self._working_dir / filename
            exists = filepath.exists()

            info = {
                "filename": filename,
                "tag": tag,
                "max_size": max_size,
                "exists": exists,
            }

            if exists:
                try:
                    info["size"] = filepath.stat().st_size
                except OSError:
                    info["size"] = -1

            available.append(info)

        return available
