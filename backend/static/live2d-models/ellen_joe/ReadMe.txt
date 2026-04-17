=== Ellen Joe (艾莲·乔) — Live2D Model ===

Character      : Ellen Joe (艾莲·乔)
Origin IP      : 『Zenless Zone Zero』(絶区零 / ZZZ) — © miHoYo / HoYoverse
Creator        : Artist 神宫凉子 + Modeler 杨小唸 (공동 제작, 팬 작품)
Distribution   : bilibili @神宫凉子 (UID 13737731) — 유일한 공식 배포 채널

=== License (원본 동봉 문서 번역 요약) ===

원본 파일 `⚡高亮⚡使用教程与注意事项.txt`에 명시된 사용 조건:

  1. 저작권은 miHoYo에 귀속. 본 모델은 팬 제작물(爱发电)이며 전 플랫폼 무료 배포.
  2. ZZZ 관련 2차 창작 영상 제작에 사용 가능 (공식 2차 창작 가이드라인 준수 필수).
  3. ❌ 禁止商用 — **상업적 이용 금지**
  4. ❌ 禁止盈利 — **수익화 금지** (후원·굿즈·유료 방송 등 일체 불가)
  5. ❌ 禁止倒卖 — 재판매 금지
  6. ❌ 禁止二改 — 2차 개조 금지 (파생 모델 제작 불가)
  7. 정치 선전에 사용 불가
  8. 위반 시 사용자 본인이 책임 (제작자 면책)

=== 운영상 주의 ===

- Geny가 상업 서비스로 런칭될 경우, **본 모델은 프로덕션에서 제거**하거나 유료 라이선스 협상 필요.
- 방송/시연은 비영리 프로모션 범위 내에서만 허용됨을 UI 쪽에도 반영 권장.

=== Asset notes ===

- `shuiyin.exp3.json` (水印 = watermark) 표정은 파일명이 "水印"이지만 실제 내용은 `Paramheadxy: 30` (머리 위치)
  한 줄뿐이며, 워터마크 토글과 무관합니다. 원본 구성 보존 차원에서 삭제하지 않았습니다.
- 표정 파일(`black`, `red`, `shock`, `shou`, `shuiyin`, `tang`)은 원본 이름을 보존. `shou`/`tang`의 의미는 불확실.
- 원본 `model3.json`의 Motions가 빈 그룹명("")이었으나, Geny의 `idleMotionGroupName: "Idle"` 컨벤션에 맞춰 `"Idle"` 그룹으로 재구성.
- Cubism SDK / Pixi 렌더링 테스트 후 `model_registry.json`의 `emotionMap` 미세 조정.

=== 워터마크 Part 숨김 처리 ===

- `cdi3.json` 상 `Part17` (Name: "水印组合" = 워터마크 조합) 이 실제 배포 서명·로고 드로어블을 묶고 있습니다.
  Ellen Joe는 Part17 하나로 모든 워터마크 요소가 결합되어 있으며, 해당 Part opacity를 0으로 두면 화면에 표시되지 않습니다.
- Geny는 텍스처를 수정하지 않고 런타임에 Part opacity를 강제로 0으로 덮어쓰는 방식을 사용합니다:
    `model_registry.json` 의 해당 엔트리에 `"hiddenParts": ["Part17"]` 을 지정하면,
    `Live2DCanvas.tsx` 가 프레임마다 `coreModel.setPartOpacityByIndex(Part17, 0)` 을 호출합니다.
- 이 방식은 **텍스처·moc3 원본을 건드리지 않으므로** 2차 개조 금지 조항(禁止二改)에 저촉되지 않는다는 해석이 가능하나,
  라이선스상 상업 이용 자체가 금지되어 있으므로 **본 설정은 비영리/개인 개발 환경 전용**입니다.
