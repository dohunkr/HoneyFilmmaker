# HoneyFilmmaker — SFM AI Animation MCP (42 tools)

> 처음이세요? **FRIEND-START-HERE.md** 하나만 읽으세요. bat 3번 더블클릭이면 끝납니다.
> 1. `Install-Windows.bat` → 2. `Setup-MCP.bat` → 3. `Start-HoneyFilmmaker.bat`

자연어 프롬프트 하나로 3D 애니메이션 기획→장면→모션→카메라→사운드→렌더→검수까지

자연어 프롬프트 하나로 3D 애니메이션 기획→장면→모션→카메라→사운드→렌더→검수까지
자동화하는 로컬 MCP 시스템. Windows + Source Filmmaker 우선, 오프라인 fallback 지원.

> 정직 원칙: SFM 미실행·에셋 없음·외부모델 없음이면 가짜 성공을 반환하지 않고
> `ok:false + code + hint`를 반환한다.

## 검증된 환경 (2026-10-16, 본 머신)
- SFM 설치: `D:\SteamLibrary\steamapps\common\SourceFilmmaker\game\sfm.exe` 존재 확인
- 내장 Python: `game\sdktools\python\2.7\win32\python.exe` (Python 2.7)
- 콘텐츠: `game\tf\models|maps|materials`, `game\hl2\models|sound|particles` 존재
- SFM은 공식 headless 렌더 CLI·원격 API가 없음 → 파일 큐 브리지(`workdir/bridge_queue`) + SFM 내 스크립트(`src/bridge/sfm_in_app.py`) 방식 사용

## MCP 연결 (오픈코드 / 안티그래비티)
- 자동: `Setup-MCP.bat` 더블클릭 (opencode.json 병합 + `mcp_antigravity.json` 생성)
- 수동 오픈코드: `mcp_opencode.snippet.json`의 경로를 내 폴더로 바꿔 opencode.json의 `mcp`에 추가
- 수동 안티그래비티: `mcp_antigravity.json`의 `PUT_REPO_PATH_HERE`를 내 폴더로 바꿔 설정에 import
- 직접 실행 원형: `MCP-stdio.bat` (stdout은 JSON-RPC만, 더블클릭 금지)

## 빠른 시작 (개발자용)
```powershell
python -m unittest discover -s tests -v
python scripts/run_server.py --transport http --port 8765
# health
Invoke-RestMethod http://127.0.0.1:8765/health | ConvertTo-Json -Depth 5
```

## MCP 연결
- stdio: `python -m src.server.mcp_server --transport stdio` (설정 예: `mcp_client_config.example.json`)
- http (로컬 전용): `POST http://127.0.0.1:8765/mcp` with `{"tool": "...", "args": {...}}`
- 도구 목록: `GET /tools`

## SFM 브리지 연결
1. SFM 실행 → 세션 열기
2. SFM Script Editor에서 `src/bridge/sfm_in_app.py` 열기 → Run
   - `HONEY_WORKDIR` env가 다르면 파일 상단 WORKDIR 수정
3. `sfm_get_status` → `connected:true` 확인
4. 씬 명령은 `workdir/bridge_queue/inbox/*.json`에 쌓이고 SFM 스크립트가 1초 폴링으로 처리

## 파이프라인
prompt → story → storyboard → shot list → asset scan → analytic scene/motion/camera/cues → SFM 큐 → Export Movie(수동) → ffmpeg combine → verify → QA

장편: 샷 단위 분할·재실행·`workdir/projects/*.json` 재개 지원. 거대 단일 명령 금지.

## 문서
- `docs/INSTALL.md` 설치·실행
- `docs/SFM_INTERFACE_RESEARCH.md` 검증 결과와 한계
- `docs/IMPLEMENTATION_STATUS.md` 구현 상태
- `examples/sample_prompts.md` 샘플 프롬프트
