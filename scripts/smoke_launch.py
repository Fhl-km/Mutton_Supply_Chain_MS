"""启动入口冒烟：真正跑一遍 `python -m mscm`，5 秒后自动关掉。

用临时数据目录，避免污染工作区的 data/ 与 导出报表/。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
TMP = Path(tempfile.mkdtemp(prefix="mscm_run_"))

env = dict(os.environ)
env["PYTHONPATH"] = str(ROOT / "src")
env["MSCM_DATA_DIR"] = str(TMP / "data")
env["QT_QPA_PLATFORM"] = "offscreen"

proc = subprocess.Popen([str(PY), "-m", "mscm"], env=env, cwd=str(ROOT),
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
try:
    out, err = proc.communicate(timeout=6)
    code = proc.returncode
except subprocess.TimeoutExpired:
    proc.terminate()
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
