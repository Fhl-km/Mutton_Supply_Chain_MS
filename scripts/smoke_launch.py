"""启动入口冒烟：真正跑一遍 `python -m mscm`，等账套文件出现后自动关掉。

用临时数据目录，避免污染工作区的 data/ 与 导出报表/。

注意：不要用「固定 N 秒后杀进程」。冷启动时 import PySide6 + 建主窗口可能超过 6 秒，
杀掉时账套还没落盘，会偶发假失败。这里改成轮询等 mscm.mscm.json 出现（最多 20 秒）。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
TMP = Path(tempfile.mkdtemp(prefix="mscm_run_"))
DATA_FILE = TMP / "data" / "mscm.mscm.json"

env = dict(os.environ)
env["PYTHONPATH"] = str(ROOT / "src")
env["MSCM_DATA_DIR"] = str(TMP / "data")
env["QT_QPA_PLATFORM"] = "offscreen"

proc = subprocess.Popen([str(PY), "-m", "mscm"], env=env, cwd=str(ROOT),
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

deadline = time.time() + 20
while time.time() < deadline and proc.poll() is None and not DATA_FILE.exists():
    time.sleep(0.2)

# 账套已落盘 → 再给主窗口一点时间收尾，然后收工
if DATA_FILE.exists():
    time.sleep(0.5)
try:
    proc.terminate()
    out, err = proc.communicate(timeout=10)
except subprocess.TimeoutExpired:
    proc.kill()
    out, err = proc.communicate(timeout=5)
code = proc.returncode

print("[stdout]", out.strip())
print("[stderr]", err.strip()[:2000])
print("[exit]", code)
files = list((TMP / "data").glob("*"))
print("[data]", [f.name for f in files])
ok = any(f.name.endswith(".json") for f in files) and "Traceback" not in err
print("[RESULT]", "OK" if ok else "FAIL")
sys.exit(0 if ok else 1)
