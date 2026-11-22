"""校验 .github/workflows 下的工作流：YAML 语法 + 内嵌 PowerShell 语法。

Windows runner 用 pwsh（PS7），本机只有 Windows PowerShell 5.1；两者语法高度重合，
用 5.1 的 parser 做纯语法校验足够把「少个括号 / 多个管道」这类错误挡在推仓库之前。

用法（项目根目录）：
    .venv\\Scripts\\python.exe scripts\\_ci_check_workflow.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WF_DIR = ROOT / ".github" / "workflows"


def check_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise SystemExit(f"[FAIL] {path.name}: 顶层不是映射")
    # YAML 1.1 把裸写的 on 解析成布尔 True（GitHub 能认，解析器不认），统一改回字符串键
    if True in data and "on" not in data:
        data["on"] = data.pop(True)
    for key in ("name", "on", "jobs"):
        if key not in data:
            raise SystemExit(f"[FAIL] {path.name}: 缺少顶层键 {key}")
    return data


def collect_runs(data: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for job_id, job in (data.get("jobs") or {}).items():
        for idx, step in enumerate(job.get("steps") or [], 1):
            script = step.get("run")
            if isinstance(script, str) and script.strip():
                out.append((f"{job_id}-{idx:02d}-{step.get('name', 'run')}", script))
    return out


def main() -> int:
    files = sorted(WF_DIR.glob("*.yml")) + sorted(WF_DIR.glob("*.yaml"))
    if not files:
        raise SystemExit("[FAIL] 没有找到工作流文件")

    tmp = Path(tempfile.mkdtemp(prefix="ci_check_"))
    try:
        return _run(files, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run(files: list[Path], TMP: Path) -> int:
    jobs: list[dict] = []
    for path in files:
        data = check_yaml(path)
        runs = collect_runs(data)
        print(f"[OK] {path.name}: YAML 合法，{len(data.get('jobs') or {})} 个 job，{len(runs)} 段脚本")

        for i, (label, script) in enumerate(runs):
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)[:60]
            ps1 = TMP / f"{path.stem}_{i:02d}_{safe}.ps1"
            ps1.write_text(script, encoding="utf-8-sig")
            jobs.append({"label": label, "path": str(ps1)})

    payload = TMP / "_check.json"
    payload.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
    ps = (
        "$jobs = Get-Content -Raw -Encoding UTF8 '" + str(payload) + "' | ConvertFrom-Json;"
        "$bad = 0;"
        "foreach ($j in $jobs) {"
        "  $errs = $null;"
        "  [void][System.Management.Automation.Language.Parser]::ParseFile($j.path, [ref]$null, [ref]$errs);"
        "  if ($errs -and $errs.Count -gt 0) { $bad++; Write-Host \"[FAIL] $($j.label)\";"
        "    foreach ($e in $errs) { Write-Host ('    ' + $e.Extent.StartLineNumber + ': ' + $e.Message) } }"
        "  else { Write-Host \"[OK]   $($j.label)\" } };"
        "if ($bad -gt 0) { exit 1 } else { Write-Host '所有脚本语法通过'; exit 0 }"
    )
    res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(res.stdout.strip())
    if res.returncode != 0:
        print(res.stderr.strip())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
