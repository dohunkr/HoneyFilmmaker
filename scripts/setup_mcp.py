"""HoneyFilmmaker MCP 자동 연결 (오픈코드 + 안티그래비티).

안전 규칙:
- 쓰기 전 항상 타임스탬프 백업 (기존 .bak을 덮어쓰지 않음)
- JSON 파싱 실패 시 해당 파일은 절대 건드리지 않고 중단
- 여러 번 실행해도 중복 등록 없음 (멱등)
"""
import argparse
import datetime
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WRAPPER = REPO / "MCP-stdio.bat"


def backup(path: Path) -> Path | None:
    if not path.is_file():
        return None
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    bak = path.with_name(path.name + f".{stamp}.bak")
    bak.write_bytes(path.read_bytes())
    return bak


def load_json(path: Path) -> tuple[dict | None, str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}, "not-found"
    except OSError as e:
        return None, f"읽기 실패: {e}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"JSON 파싱 실패(파일을 건드리지 않았습니다): {e}"
    if not isinstance(data, dict):
        return None, "최상위가 object가 아님(파일을 건드리지 않았습니다)"
    return data, "ok"


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def merge_opencode(path: Path) -> bool:
    data, msg = load_json(path)
    if data is None:
        print(f"  [오픈코드] {msg}\n  -> {path}")
        print("  수동 등록: mcp_opencode.snippet.json 참고")
        return False
    bak = backup(path)
    mcp = data.get("mcp")
    if not isinstance(mcp, dict):
        mcp = {}
        data["mcp"] = mcp
    mcp["honey-filmmaker-sfm"] = {
        "type": "local",
        "command": ["cmd", "/c", str(WRAPPER)],
        "enabled": True,
    }
    save_json(path, data)
    print(f"  [오픈코드] 연결 OK -> {path}")
    if bak:
        print(f"  (백업: {bak.name})")
    return True


def merge_antigravity(path: Path | None) -> bool:
    if path is None:
        return False
    data, msg = load_json(path)
    if data is None:
        print(f"  [안티그래비티] {msg}\n  -> {path}")
        return False
    bak = backup(path)
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers
    servers["honey-filmmaker-sfm"] = {"command": str(WRAPPER), "args": []}
    save_json(path, data)
    print(f"  [안티그래비티] 연결 OK -> {path}")
    if bak:
        print(f"  (백업: {bak.name})")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--opencode-path", default=None)
    ap.add_argument("--ag-path", default=None)
    a = ap.parse_args()

    print("== HoneyFilmmaker MCP 연결 ==")
    print(f"  위치: {REPO}")
    print("")
    if not WRAPPER.is_file():
        print(f"[오류] {WRAPPER} 없음. 압축을 완전히 푸셨는지 확인하세요.")
        return 1

    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    opencode = Path(a.opencode_path) if a.opencode_path else (
        home / ".config" / "opencode" / "opencode.json")
    ok1 = merge_opencode(opencode)

    ag_default = Path(os.environ.get("APPDATA", "")) / "Antigravity" / "mcp_config.json" \
        if os.environ.get("APPDATA") else None
    ag_path = Path(a.ag_path) if a.ag_path else ag_default
    ok2 = False
    if ag_path is not None and (ag_path.is_file() or (ag_path.parent.is_dir())):
        ok2 = merge_antigravity(ag_path)
    else:
        print("  [안티그래비티] 기존 설정 없음 -> 파일만 생성합니다")

    repo_ag = REPO / "mcp_antigravity.json"
    save_json(repo_ag, {"mcpServers": {
        "honey-filmmaker-sfm": {"command": str(WRAPPER), "args": []}}})
    print(f"  안티그래비티 수동 import용: {repo_ag}")

    print("")
    if ok1 or ok2:
        print("완료! 오픈코드/안티그래비티를 재시작하면 목록에 뜹니다.")
    print("확인: Start-HoneyFilmmaker.bat 실행 후 http://127.0.0.1:8765/health")
    return 0


if __name__ == "__main__":
    sys.exit(main())
