# INSTALL (Windows)

## 요구
- Windows 10/11, Python 3.10+ (본 머신 3.10.11 확인)
- Steam + Source Filmmaker (`D:\SteamLibrary\...\game\sfm.exe`)
- 선택: ffmpeg (영상 결합·검증용), ffprobe同梱

## 설치
```powershell
cd D:\Github\HoneyFilmmaker
copy .env.example .env
# pip는 stdlib-only라 필수는 아님
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

## 서버
```powershell
python scripts/run_server.py --transport http --port 8765
# 또는 stdio (MCP 클라이언트용)
python -m src.server.mcp_server --transport stdio
```

## SFM 연결
1. `D:\SteamLibrary\steamapps\common\SourceFilmmaker\game\sfm.exe` 실행
2. 세션 생성/열기
3. Script Editor → `src\bridge\sfm_in_app.py` → Run
4. `POST /mcp {"tool":"sfm_get_status"}` → connected 확인

## 오프라인 동작
- LLM 키 없음 → 규칙 기반 스토리/샷 생성
- TTS 없음 → cue 경로만 예약, missing 명시
- ffmpeg 없음 → combine 실패를 정직 보고, 입력 보존
