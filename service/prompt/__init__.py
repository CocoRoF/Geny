"""
Prompt Builder System

OpenClaw의 25+ 섹션 모듈러 프롬프트 설계를 참고하여
Claude Control에 적합한 구조적 프롬프트 빌더를 구현합니다.

사용 예:
    from service.prompt import PromptBuilder, PromptMode

    builder = PromptBuilder(mode=PromptMode.FULL)
    prompt = (builder
        .add_identity("DevWorker", role=SessionRole.WORKER)
        .add_capabilities(tools=["read_file", "write_file"])
        .add_safety_guidelines()
        .add_execution_protocol(autonomous=True)
        .add_completion_protocol()
        .add_runtime_line(model="claude-sonnet-4", session_id="abc")
        .build())
"""

from service.prompt.builder import PromptBuilder, PromptMode, PromptSection
from service.prompt.sections import SectionLibrary
from service.prompt.protocols import ExecutionProtocol, CompletionProtocol, ErrorRecoveryProtocol
from service.prompt.context_loader import ContextLoader

__all__ = [
    "PromptBuilder",
    "PromptMode",
    "PromptSection",
    "SectionLibrary",
    "ExecutionProtocol",
    "CompletionProtocol",
    "ErrorRecoveryProtocol",
    "ContextLoader",
]
