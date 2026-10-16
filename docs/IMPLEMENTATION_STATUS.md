# IMPLEMENTATION_STATUS (2026-10-16 전단계 실행 후)

## Phase 1 — 작동하는 기본 시스템 ✅
- MCP 서버 stdio+http(local-only), 42개 도구, 스키마 검증, jsonl 로그/타이밍
- SFM 연결 상태/세션 조회, honest `SFM_NOT_RUNNING/BRIDGE_NOT_INSTALLED`
- 에셋 스캔/검색/검사/호환, 경로 탈출 차단 (단일패스 스캔 2.4s/캐시 0.02s, 6182개)
- Analytic scene/model/transform/camera/light + SFM 큐 연동
- 테스트 26 passed (5.2s)

## Phase 2 — 자동 장면 제작 ✅ (analytic)
- 규칙 기반 story/storyboard/shot-list, 길이·보스·반전 파싱
- 키프레임 생성/블렌드/공간검증/리그호환(정직 unknown)
- 시네마틱 프리셋 6종 + 다양성 체크 + 조명
- 미리보기 HTML(`workdir/previews/<pid>/preview.html`) + 렌더 작업 상태 + 선택 재실행

## Phase 3 — AI 확장 ✅ (실동작, 외부모델 없이)
- `compose_combat` attack-hit-fall 체인, `compose_chase` 간격유지 검증
- `retarget_report` 베이스본 게이트, `find_motion_clips` .dmx/.smd 후보 탐색
- `MotionAdapter/LLMAdapter/TTSAdapter` 레지스트리 + 오프라인 fallback
- 오디오: `synth_silent_wav` + `synth_sfx_wav` stdlib 합성, `validate_wav` 통과하는 실파일 (silent/synthesized 명시, 가짜보이스 아님)
- 필요(유료/외부): Piper/Coqui TTS, 모션생성 API 연동 시 키·비용 문서화 후 어댑터에 주입

## Phase 4 — 장편 ✅ (실동작)
- 캐릭터 바이블(진영/외형/소품/상태/위치), 샷간 위치 연속성
- `run_full_auto` 15단계(요구→스토리→샷→에셋→씬→모션→카메라→오디오→프리뷰→QA→수정→렌더큐→결합→검증)
- 2분 샘플 실측: 15 shots, 2880 frames, QA before/after 0, preview 생성, combine는 SFM export 전이라 honest pending
- `apply_auto_fixes` 실제 지면상승/분리, `mark_shot_done` 수동export 등록, `resume_project` json 재개
- ffmpeg/ffprobe 탐색: PATH + `HONEY_FFMPEG` + roop-unleashed 번들 경로

## 제한 (실환경 미검증, 가짜성공 없음)
- SFM 미실행: 변형 명령은 큐에만 쌓이고 `connected:false` 보고
- Export Movie 무인 자동화 불가 → 샷별 수동 export 후 `mark_shot_done`+`combine_shots`
- TTS 실보이스·외부 모션모델 실연동은 어댑터 주입 후속 작업
