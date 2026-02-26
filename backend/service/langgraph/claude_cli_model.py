"""
LangGraph + Claude CLI 통합

기존 ClaudeProcess의 세션 관리와 실행 로직을 그대로 활용하면서
LangGraph의 상태 관리 기능을 통합합니다.

사용 예:
    from service.langgraph import ClaudeCLIChatModel

    # 새 세션으로 모델 생성
    model = ClaudeCLIChatModel(
        working_dir="/path/to/project",
        model_name="claude-sonnet-4-20250514"
    )
    await model.initialize()  # 세션 초기화 필수

    # 기존 ClaudeProcess 세션을 사용
    model = ClaudeCLIChatModel.from_process(existing_process)

    # LangGraph Agent로 사용
    from langgraph.prebuilt import create_react_agent
    agent = create_react_agent(model, tools=[])
"""

import asyncio
import json
from logging import getLogger
from typing import Any, Callable, Dict, List, Optional, Sequence, Union, AsyncIterator

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    AIMessageChunk,
)
from langchain_core.outputs import ChatGeneration, ChatResult, ChatGenerationChunk
from langchain_core.callbacks.manager import (
    CallbackManagerForLLMRun,
    AsyncCallbackManagerForLLMRun,
)
from langchain_core.tools import BaseTool
from langchain_core.runnables import Runnable, RunnablePassthrough, RunnableLambda
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field, PrivateAttr

from service.claude_manager.process_manager import ClaudeProcess
from service.claude_manager.models import MCPConfig
from service.claude_manager.constants import CLAUDE_DEFAULT_TIMEOUT

logger = getLogger(__name__)


class ClaudeCLIChatModel(BaseChatModel):
    """
    Claude CLI를 LangChain ChatModel로 래핑.

    내부적으로 ClaudeProcess를 사용하여 CLI 세션을 관리합니다.
    ClaudeProcess의 모든 기능(MCP 연동, 파일 관리, 세션 유지)을 그대로 활용합니다.

    주요 특징:
    - ClaudeProcess.execute()를 통한 CLI 호출
    - CLI의 --resume 옵션으로 대화 컨텍스트 유지
    - CLI의 MCP 서버 연동 (.mcp.json)
    - CLI의 파일 시스템 접근 기능
    - LangGraph의 상태 관리, 체크포인팅 지원

    사용법:
    ```python
    # 새 세션 생성
    model = ClaudeCLIChatModel(
        working_dir="/path/to/project",
        model_name="claude-sonnet-4-20250514"
    )
    await model.initialize()  # 세션 초기화 필수

    # 직접 호출
    response = await model.ainvoke([HumanMessage(content="Hello")])

    # 기존 ClaudeProcess 사용
    model = ClaudeCLIChatModel.from_process(existing_process)

    # LangGraph와 함께 사용
    from langgraph.prebuilt import create_react_agent
    agent = create_react_agent(model, tools=[])
    ```
    """

    # === Pydantic Configuration Fields ===
    session_id: Optional[str] = Field(
        default=None,
        description="Session ID (auto-generated if not provided)"
    )
    session_name: Optional[str] = Field(
        default=None,
        description="Human-readable session name"
    )
    working_dir: Optional[str] = Field(
        default=None,
        description="Working directory for CLI execution (None = use session storage path)"
    )
    model_name: Optional[str] = Field(
        default=None,
        description="Claude model to use (e.g., claude-sonnet-4-20250514)"
    )
    max_turns: int = Field(
        default=100,
        description="Maximum turns per execution"
    )
    timeout: float = Field(
        default=CLAUDE_DEFAULT_TIMEOUT,
        description="Execution timeout in seconds"
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="System prompt to append"
    )
    env_vars: Dict[str, str] = Field(
        default_factory=dict,
        description="Additional environment variables"
    )
    mcp_config: Optional[MCPConfig] = Field(
        default=None,
        description="MCP configuration for tool servers"
    )

    # === Private Attributes ===
    _process: Optional[ClaudeProcess] = PrivateAttr(default=None)
    _initialized: bool = PrivateAttr(default=False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._process = None
        self._initialized = False

    @classmethod
    def from_process(cls, process: ClaudeProcess) -> "ClaudeCLIChatModel":
        """
        기존 ClaudeProcess를 사용하여 모델 생성.

        Args:
            process: 초기화된 ClaudeProcess 인스턴스

        Returns:
            ClaudeCLIChatModel 인스턴스
        """
        model = cls(
            session_id=process.session_id,
            session_name=process.session_name,
            working_dir=process.working_dir,
            model_name=process.model,
            max_turns=process.max_turns,
            timeout=process.timeout,
            system_prompt=process.system_prompt,
            env_vars=process.env_vars or {},
            mcp_config=process.mcp_config,
        )
        model._process = process
        model._initialized = True
        return model

    @property
    def process(self) -> Optional[ClaudeProcess]:
        """내부 ClaudeProcess 인스턴스 반환"""
        return self._process

    @property
    def is_initialized(self) -> bool:
        """세션 초기화 여부"""
        return self._initialized

    @property
    def _llm_type(self) -> str:
        return "claude-cli"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id or (self._process.session_id if self._process else None),
            "model_name": self.model_name,
            "working_dir": self.working_dir,
            "max_turns": self.max_turns,
        }

    async def initialize(self) -> bool:
        """
        세션 초기화.

        ClaudeProcess를 생성하고 초기화합니다.
        from_process()로 생성한 경우 이미 초기화되어 있습니다.

        Returns:
            초기화 성공 여부
        """
        if self._initialized and self._process:
            logger.info(f"Session already initialized: {self._process.session_id}")
            return True

        import uuid

        # 세션 ID 생성
        session_id = self.session_id or str(uuid.uuid4())

        # ClaudeProcess 생성
        self._process = ClaudeProcess(
            session_id=session_id,
            session_name=self.session_name,
            working_dir=self.working_dir,
            env_vars=self.env_vars,
            model=self.model_name,
            max_turns=self.max_turns,
            timeout=self.timeout,
            mcp_config=self.mcp_config,
            system_prompt=self.system_prompt,
        )

        # 초기화 실행
        success = await self._process.initialize()

        if success:
            self._initialized = True
            self.session_id = session_id
            logger.info(f"ClaudeCLIChatModel initialized: {session_id}")
        else:
            logger.error(f"Failed to initialize ClaudeCLIChatModel: {self._process.error_message}")

        return success

    async def cleanup(self):
        """
        세션 정리.

        ClaudeProcess를 정리하고 리소스를 해제합니다.
        """
        if self._process:
            await self._process.stop()
            await self._process.cleanup_storage()
            self._process = None
            self._initialized = False
            logger.info(f"ClaudeCLIChatModel cleaned up: {self.session_id}")

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """
        동기 생성 메서드 (LangChain 필수 구현).
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self._agenerate(messages, stop, None, **kwargs)
                    )
                    return future.result()
            else:
                return loop.run_until_complete(
                    self._agenerate(messages, stop, None, **kwargs)
                )
        except RuntimeError:
            return asyncio.run(self._agenerate(messages, stop, None, **kwargs))

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """
        비동기 생성 메서드.

        ClaudeProcess.execute()를 호출하여 응답을 생성합니다.
        """
        # 자동 초기화
        if not self._initialized:
            success = await self.initialize()
            if not success:
                error_msg = self._process.error_message if self._process else "Initialization failed"
                message = AIMessage(
                    content=f"Error: {error_msg}",
                    additional_kwargs={"error": True, "error_message": error_msg}
                )
                return ChatResult(generations=[ChatGeneration(message=message)])

        prompt = self._messages_to_prompt(messages)

        # kwargs에서 오버라이드 파라미터 추출
        system_prompt = kwargs.get("system_prompt", self.system_prompt)
        max_turns = kwargs.get("max_turns", self.max_turns)
        timeout = kwargs.get("timeout", self.timeout)
        resume = kwargs.get("resume")  # None이면 자동 결정

        # ClaudeProcess.execute() 호출
        result = await self._process.execute(
            prompt=prompt,
            timeout=timeout,
            system_prompt=system_prompt,
            max_turns=max_turns,
            resume=resume,
        )

        if result.get("success"):
            content = result.get("output", "")

            additional_kwargs = {
                "execution_count": result.get("execution_count", 0),
                "duration_ms": result.get("duration_ms", 0),
                "session_id": self._process.session_id,
                "conversation_id": self._process._conversation_id,
            }

            message = AIMessage(
                content=content,
                additional_kwargs=additional_kwargs
            )
        else:
            error_msg = result.get("error", "Unknown error")
            message = AIMessage(
                content=f"Error: {error_msg}",
                additional_kwargs={
                    "error": True,
                    "error_message": error_msg,
                    "output": result.get("output", ""),
                }
            )

        generation = ChatGeneration(message=message)
        return ChatResult(generations=[generation])

    def _messages_to_prompt(self, messages: List[BaseMessage]) -> str:
        """
        LangChain 메시지를 프롬프트 문자열로 변환.

        첫 실행 또는 resume이 비활성화된 경우 전체 대화를 포함하고,
        resume 모드에서는 마지막 HumanMessage만 전달합니다.
        """
        if not messages:
            return ""

        # 첫 실행이면 전체 대화 포함
        if self._process and self._process._execution_count == 0:
            parts = []
            for msg in messages:
                if isinstance(msg, SystemMessage):
                    parts.append(f"[System]: {msg.content}")
                elif isinstance(msg, HumanMessage):
                    parts.append(f"[User]: {msg.content}")
                elif isinstance(msg, AIMessage):
                    parts.append(f"[Assistant]: {msg.content}")
                elif isinstance(msg, ToolMessage):
                    parts.append(f"[Tool Result]: {msg.content}")
            return "\n\n".join(parts)

        # Resume 모드: 마지막 HumanMessage만 전달
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                return str(msg.content)

        return str(messages[-1].content)

    # === Streaming Support ===

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """
        비동기 스트리밍 생성.

        현재는 전체 응답을 받은 후 청크로 나누어 반환합니다.
        """
        result = await self._agenerate(messages, stop, run_manager, **kwargs)

        if result.generations:
            content = result.generations[0].message.content
            chunk_size = 100
            for i in range(0, len(content), chunk_size):
                chunk_content = content[i:i + chunk_size]
                chunk = ChatGenerationChunk(
                    message=AIMessageChunk(content=chunk_content)
                )
                yield chunk

    # === Tool Binding Support ===

    def bind_tools(
        self,
        tools: Sequence[Union[Dict[str, Any], type, Callable, BaseTool]],
        *,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> Runnable:
        """
        도구를 모델에 바인딩합니다.

        Claude CLI는 자체 도구 처리 시스템(MCP)을 사용하므로,
        이 메서드는 도구 정의를 시스템 프롬프트에 추가하여
        CLI가 도구를 인식하도록 합니다.

        Args:
            tools: 바인딩할 도구 목록
            tool_choice: 도구 선택 모드 (optional)
            **kwargs: 추가 인자

        Returns:
            도구가 바인딩된 Runnable
        """
        # 도구 정의를 JSON 스키마로 변환
        tool_descriptions = []
        for tool in tools:
            try:
                tool_schema = convert_to_openai_tool(tool)
                tool_descriptions.append(tool_schema)
            except Exception as e:
                logger.warning(f"Failed to convert tool: {e}")
                continue

        # 도구 설명을 시스템 프롬프트에 추가
        tools_prompt = self._format_tools_prompt(tool_descriptions)

        # 새 인스턴스 생성 with updated system_prompt
        bound_model = ClaudeCLIChatModel(
            session_id=None,  # 새 세션
            session_name=self.session_name,
            working_dir=self.working_dir,
            model_name=self.model_name,
            max_turns=self.max_turns,
            timeout=self.timeout,
            system_prompt=self._merge_system_prompt(tools_prompt),
            env_vars=self.env_vars,
            mcp_config=self.mcp_config,
        )

        return bound_model

    def _format_tools_prompt(self, tool_schemas: List[Dict]) -> str:
        """도구 스키마를 프롬프트 형식으로 변환"""
        if not tool_schemas:
            return ""

        lines = ["You have access to the following tools:"]
        for schema in tool_schemas:
            func = schema.get("function", {})
            name = func.get("name", "unknown")
            desc = func.get("description", "No description")
            params = func.get("parameters", {})

            lines.append(f"\n### {name}")
            lines.append(f"Description: {desc}")
            if params.get("properties"):
                lines.append("Parameters:")
                for pname, pdef in params["properties"].items():
                    ptype = pdef.get("type", "any")
                    pdesc = pdef.get("description", "")
                    lines.append(f"  - {pname} ({ptype}): {pdesc}")

        lines.append("\nWhen you need to use a tool, describe what you're doing and execute it.")
        return "\n".join(lines)

    def _merge_system_prompt(self, additional: str) -> str:
        """시스템 프롬프트 병합"""
        if not additional:
            return self.system_prompt or ""
        if not self.system_prompt:
            return additional
        return f"{self.system_prompt}\n\n{additional}"

    def with_structured_output(
        self,
        schema: Union[Dict[str, Any], type],
        *,
        include_raw: bool = False,
        **kwargs: Any,
    ) -> Runnable:
        """
        구조화된 출력을 생성하도록 모델을 구성합니다.

        Claude CLI의 응답을 지정된 스키마에 맞게 파싱합니다.

        Args:
            schema: Pydantic 모델 또는 JSON 스키마
            include_raw: 원본 응답 포함 여부
            **kwargs: 추가 인자

        Returns:
            구조화된 출력을 생성하는 Runnable
        """
        # 스키마 정보 추출
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            schema_json = schema.model_json_schema()
            schema_name = schema.__name__
        else:
            schema_json = schema
            schema_name = schema.get("title", "Response")

        # 스키마를 프롬프트에 추가
        schema_prompt = f"""
Please respond with a JSON object that matches this schema:
```json
{json.dumps(schema_json, indent=2)}
```
Only output the JSON object, no additional text."""

        # 새 모델 생성 with schema prompt
        structured_model = ClaudeCLIChatModel(
            session_id=None,
            session_name=self.session_name,
            working_dir=self.working_dir,
            model_name=self.model_name,
            max_turns=self.max_turns,
            timeout=self.timeout,
            system_prompt=self._merge_system_prompt(schema_prompt),
            env_vars=self.env_vars,
            mcp_config=self.mcp_config,
        )

        # 파싱 함수
        def parse_output(response: AIMessage) -> Union[Dict, BaseModel]:
            content = response.content
            # JSON 블록 추출 시도
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                if end > start:
                    content = content[start:end].strip()
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                if end > start:
                    content = content[start:end].strip()

            try:
                parsed = json.loads(content)
                if isinstance(schema, type) and issubclass(schema, BaseModel):
                    return schema.model_validate(parsed)
                return parsed
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Failed to parse structured output: {e}")
                return {"raw": response.content, "error": str(e)}

        if include_raw:
            def with_raw(response: AIMessage) -> Dict:
                return {
                    "raw": response,
                    "parsed": parse_output(response),
                }
            return structured_model | RunnableLambda(with_raw)
        else:
            return structured_model | RunnableLambda(parse_output)

    # === Utility Methods ===

    def get_storage_path(self) -> Optional[str]:
        """세션 스토리지 경로 반환"""
        return self._process.storage_path if self._process else None

    def list_storage_files(self, subpath: str = "") -> List[Dict]:
        """세션 스토리지의 파일 목록 반환"""
        if self._process:
            return self._process.list_storage_files(subpath)
        return []

    def read_storage_file(self, filepath: str) -> Optional[str]:
        """세션 스토리지의 파일 내용 읽기"""
        if self._process:
            return self._process.read_storage_file(filepath)
        return None
