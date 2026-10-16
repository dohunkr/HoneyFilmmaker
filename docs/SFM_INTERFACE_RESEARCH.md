# SFM_INTERFACE_RESEARCH (verified 2026-10-16)

## 확인된 사실 (본 머신 실측)
- `D:\SteamLibrary\steamapps\common\SourceFilmmaker\game\sfm.exe` (104,960 bytes) 존재
- `game\sdktools\python\2.7\win32\python.exe` + `python27.dll` → 내장 Python 2.7
- `game\tf\{models,maps,materials,media}`, `game\hl2\{models,sound,particles,scenes}` 존재
- `game\platform\scripts\sfm` 관련 스크립트 경로 흔적
- `tasklist /FI "IMAGENAME eq sfm.exe"` 로 실행 감지 가능 (브리지에 구현)

## SFM 스크립팅 제약 (문서+커뮤니티 교차검증, 세션 내 검증 필요)
- SFM 내 `import sfm, vs, dm` 모듈은 **SFM Script Editor 안에서만** import 가능. 외부 python에서는 ImportError.
- 세션/샷/애니메이션셋 조작 API는 SFM 버전에 따라 시그니처가 다름 → 무작정 호출 금지.
  본 프로젝트는 `sfm.GetCurrentSession()` 존재 여부만 먼저 확인하고, 변형 명령은
  `sfm_in_app.py handle()`에 세션별 검증 코드 추가 방식으로 확장하도록 설계.
- 공식 headless 렌더 CLI 미제공. `File > Export > Movie` 수동 또는 세션 스크립트 Export가 현실적 경로.
  → RenderManager는 `pending_SFM` 상태로 기록하고 ffmpeg 결합만 자동화.

## 브리지 설계 (검증된 대체 수단)
- `workdir/bridge_queue/inbox/*.json` 명령 큐 + `outbox/*.json` 결과 + `heartbeat.json`
- SFM 내 `sfm_in_app.py`가 1초 폴링. 외부 MCP는 절대 SFM 메모리를 직접 건드리지 않음.
- 로컬 전용, 경로 탈출 차단, 허용 명령 화이트리스트.

## 미검증 (별도 표시)
- 본 세션에서 SFM을 직접 실행한 상태의 `sfm/vs/dm` 전체 API 덤프
- Export Movie 자동화 인자, 파티클/립싱크 세밀 제어
→ `IMPLEMENTATION_STATUS.md`의 제한사항 참조, 후속 작업으로 SFM 실행 중 `dir(sfm)` 덤프 예정.
