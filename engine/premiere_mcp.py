"""프리미어 MCP 서버(premiere-pro)를 stdio 로 직접 호출하는 클라이언트.

Claude Code 세션에 `mcp__premiere-pro__*` 툴이 안 올라와 있어도(경로 오류·재시작 전 등)
이걸로 바로 프리미어를 읽을 수 있다. **비블 수정본을 EDL 로 재내보내지 않고
열려 있는 프로젝트에서 직접 읽는 게 학습 루프의 표준 경로다.**

전제: ① 프리미어가 실행 중 ② CEP 브리지 패널 설치
     (`C:\\Program Files (x86)\\Common Files\\Adobe\\CEP\\extensions\\cep-plugin`)
     ③ 서버 빌드 완료 (`npm install && npm run build`)

    python engine/premiere_mcp.py get_project_info
    python engine/premiere_mcp.py get_full_sequence_info '{"sequenceId":"..."}'

주요 툴 (총 281개):
    list_sequences            시퀀스 id·이름·길이·트랙수
    get_full_sequence_info    트랙별 클립 전체 — start/end/inPoint/outPoint (초)
    read_sequence_captions    캡션 트랙 자막
    list_clip_effects         클립 이펙트(Lumetri 색보정 등)
    get_clip_properties       클립 속성
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

def _find_server():
    """MCP 서버(dist/index.js)를 찾는다 — PC 마다 설치 위치가 다르다.

    ① 환경변수 `PREMIERE_MCP_SERVER`
    ② Claude 설정(`~/.claude.json`)의 mcpServers 에 등록된 경로
    ③ 홈/다운로드 아래 흔한 폴더명
    """
    env = os.environ.get("PREMIERE_MCP_SERVER")
    if env and os.path.exists(env):
        return env

    cfg = Path.home() / ".claude.json"
    if cfg.exists():
        try:
            servers = json.loads(cfg.read_text(encoding="utf-8")).get("mcpServers") or {}
            for name, spec in servers.items():
                if "premiere" not in name.lower():
                    continue
                for arg in spec.get("args") or []:
                    if str(arg).endswith(".js") and os.path.exists(arg):
                        return arg
        except (ValueError, OSError):
            pass

    home = Path.home()
    for base in (home, home / "Downloads", home / "Documents", Path("/opt"), Path("/usr/local")):
        for name in ("Adobe_Premiere_Pro_MCP", "Adobe_Premiere_Pro_MCP-main",
                     "premiere-pro-mcp", "mcp-adobe-premiere-pro"):
            p = base / name / "dist" / "index.js"
            if p.exists():
                return str(p)
    return ""


def _default_temp():
    """CEP 브리지가 파일을 주고받는 폴더. 패널의 Temp Directory 와 **같아야 한다.**

    안 맞으면 서버는 명령 파일을 쓰고 패널은 다른 폴더를 보고 있어서 'Bridge response
    timeout' 만 난다 — 패널은 멀쩡히 떠 있는데 붙지 않는다(맥에서 실제로 겪었다.
    설치 스크립트는 /tmp 를 만드는데 서버 기본값은 $TMPDIR 아래였다).

    그래서 **패널이 남긴 config.json 을 먼저 믿는다.** 패널이 Save Configuration 을
    누를 때 자기 Temp Directory 를 거기에 적어 둔다.
    """
    for cand in ("/tmp/premiere-mcp-bridge",
                 str(Path(tempfile.gettempdir()) / "premiere-mcp-bridge"),
                 r"C:\temp\premiere-mcp-bridge"):
        cfg = Path(cand) / "config.json"
        if cfg.exists():
            try:
                d = json.loads(cfg.read_text(encoding="utf-8")).get("tempDirectory")
                if d and os.path.isdir(d):
                    return d
            except (ValueError, OSError):
                pass
    if os.name == "nt":
        return r"C:\temp\premiere-mcp-bridge"
    return str(Path(tempfile.gettempdir()) / "premiere-mcp-bridge")


SERVER = _find_server()
TEMP = os.environ.get("PREMIERE_TEMP_DIR", _default_temp())


class Premiere:
    """MCP 서버를 자식 프로세스로 띄우고 JSON-RPC 로 대화한다."""

    def __init__(self):
        if not SERVER:
            raise SystemExit(
                "프리미어 MCP 서버를 못 찾았다.\n"
                "  ① 리포지토리를 받아 `npm install && npm run build` (dist/index.js 생성)\n"
                "  ② 경로를 알려준다:  set PREMIERE_MCP_SERVER=<...>\\dist\\index.js\n"
                "  (mac/linux: export PREMIERE_MCP_SERVER=<...>/dist/index.js)")
        self.p = subprocess.Popen(
            ["node", SERVER],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1,
            env=dict(os.environ, PREMIERE_TEMP_DIR=TEMP),
        )
        self._id = 0
        self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "premiere_mcp.py", "version": "1"},
        })
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    def _send(self, obj):
        self.p.stdin.write(json.dumps(obj) + "\n")
        self.p.stdin.flush()

    def _rpc(self, method, params):
        self._id += 1
        self._send({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError(
                    "MCP 서버가 응답 없이 종료됐다 — 서버 빌드(dist/index.js)를 확인할 것")
            msg = json.loads(line)
            if msg.get("id") == self._id:
                return msg

    def call(self, tool, **args):
        """툴 호출. 결과가 JSON 이면 dict, 아니면 {'_text': ...}"""
        msg = self._rpc("tools/call", {"name": tool, "arguments": args})
        if "error" in msg:
            return {"_error": msg["error"]}
        result = msg.get("result", {})
        raw = "\n".join(c.get("text", "") for c in result.get("content", [])
                        if c.get("type") == "text")
        try:
            return json.loads(raw)
        except ValueError:
            return {"_text": raw, "_isError": result.get("isError")}

    def tools(self):
        return [t["name"] for t in self._rpc("tools/list", {})["result"]["tools"]]

    def close(self):
        self.p.kill()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def clips(seq_info, track_type="videoTracks", index=0):
    """get_full_sequence_info 결과에서 한 트랙의 클립 리스트를 꺼낸다."""
    return seq_info["data"][track_type][index]["clips"]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    with Premiere() as pr:
        print(json.dumps(pr.call(sys.argv[1], **args), ensure_ascii=False, indent=1))
