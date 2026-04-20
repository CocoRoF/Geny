# Analysis Index — Tool/MCP Integration

`geny-executor` 가 외부 도구/MCP 를 받아들이는 **host 인터페이스**, Geny 가
built-in tool 을 거기에 얹는 **consumer 등록 경로**, 그리고 둘 사이의 **간극**
을 사실 기반으로 기록한다. 모든 항목은 실제 파일 경로와 라인 번호로 뒷받침한다.

## 문서

- [01_symptom_and_reproduction.md](01_symptom_and_reproduction.md) —
  `news_search (parse error)` 증상, 재현 경로, 그리고 "`(parse error)` 는 사실
  logging swallower 의 부산물이며 진짜 원인은 다른 곳에 있다" 는 결론.
- [02_executor_host_interface.md](02_executor_host_interface.md) —
  `geny-executor` 의 tool host 구조: `Tool` ABC / `ToolRegistry` /
  `ToolComposer` / `MCPManager` / Stage 6 → 9 → 10 의 dispatch 경로.
- [03_geny_consumer_registration.md](03_geny_consumer_registration.md) —
  Geny 의 `BaseTool` → `ToolLoader` → `build_geny_tool_registry` →
  `_GenyToolAdapter` → `AgentSession._build_pipeline` 로 이어지는 등록 사슬.
- [04_manifest_vs_runtime_registration_gap.md](04_manifest_vs_runtime_registration_gap.md) —
  `env_id` 경로 (`Pipeline.from_manifest`) 와 legacy 경로 (`GenyPresets.*(tools=...)`)
  가 분기되어 **manifest 기반 세션에서 Geny built-in 이 레지스트리에 영영
  안 들어가는** 원인 분석.
- [05_fragility_catalogue.md](05_fragility_catalogue.md) —
  입력 스키마 미검증, 알 수 없는 tool 의 문자열 반환, MCP 결과 이중 인코딩,
  logging swallower 등 흩어져 있는 취약점 목록.

## 작업 원칙

- "추측" 금지. 확인되지 않은 동작은 "TBD" 로 명시하고 근거 파일 경로를 덧붙인다.
- `geny-executor` 의 Python 구조가 변경될 수 있으므로 모든 인용은 **현재 레포
  경로의 스냅샷** 이며, 라이브러리 버전은 각 문서 본문에 명시한다.
- 같은 용어가 repo 간에 다른 의미로 쓰이면 ("session", "tool", "context") 반드시
  표시한다.
