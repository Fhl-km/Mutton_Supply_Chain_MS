"""一次性工具：把 FHLWEBSITE_TOKEN 写进仓库 Actions Secret（跑完即删）。

用法（项目根目录）：
    .venv\\Scripts\\python.exe scripts/_set_secret.py <PAT 文件> <仓库> <secret 名>

为什么要用 Python 而不是命令行：GitHub 的 actions/secrets 接口要求用仓库公钥做
libsodium sealed box 加密，命令行不好拼；另外 token 不落到命令行参数里，少一处泄漏面。

凭证来源：
  · 写 Secret 需要该仓库的管理权限 —— 用本机 git 凭据（gho_ 开头的 OAuth token）
  · 被写进去的值 —— 从命令行指定的文件读（读后立刻删除）

输出只打印长度/名称，绝不打印 token 本身。
"""

from __future__ import annotations

import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from nacl import encoding, public


def req(url: str, token: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Authorization", f"Bearer {token}")
    r.add_header("Accept", "application/vnd.github+json")
    r.add_header("X-GitHub-Api-Version", "2022-11-28")
    r.add_header("User-Agent", "mscm-secret-setter")
    if data:
        r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, timeout=30) as resp:
        raw = resp.read().decode() or "{}"
        return json.loads(raw)


def cred(path: Path) -> str:
    d = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k] = v
    return d.get("password", "")


def main() -> int:
    pat_file, repo, name = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    admin = cred(Path("scripts/_cred.txt"))
    value = pat_file.read_text(encoding="utf-8").strip()
    print(f"待写入 Secret：{name}（值长度 {len(value)}，前缀 {value[:11]}…）")

    # 1) 待写入的那个 token 是否真能读 FHLwebsite
    try:
        info = req("https://api.github.com/repos/Fhl-km/FHLwebsite", value)
        print(f"[1] 新 token 可访问：{info['full_name']}（private={info['private']}）")
    except urllib.error.HTTPError as e:
        code = e.code
        print(f"[1] ❌ 新 token 读不到 Fhl-km/FHLwebsite（HTTP {code}）—— 检查是否选了这个仓库、Contents 是否给了读权限")
        return 1

    # 2) 本机凭据是否有该仓库的管理权限
    try:
        me = req("https://api.github.com/repos/" + repo, admin)
    except urllib.error.HTTPError as e:
        print(f"[2] ❌ 本机 git 凭据读不到 {repo}（HTTP {e.code}），无法写 Secret")
        return 2
    perms = me.get("permissions") or {}
    print(f"[2] 仓库 {me['full_name']}：admin={perms.get('admin')} push={perms.get('push')}")
    if not (perms.get("admin") or perms.get("maintain")):
        print("[2] ❌ 凭据没有 admin 权限，写不了 Secrets（需要管理员）")
        return 2

    # 3) 取仓库公钥 → sealed box 加密 → PUT
    key = req(f"https://api.github.com/repos/{repo}/actions/secrets/public-key", admin)
    pk = public.PublicKey(key["key"].encode(), encoding.Base64Encoder())
    sealed = public.SealedBox(pk).encrypt(value.encode())
    payload = {"encrypted_value": base64.b64encode(sealed).decode(), "key_id": key["key_id"]}
    try:
        resp = req(f"https://api.github.com/repos/{repo}/actions/secrets/{name}", admin, "PUT", payload)
        print(f"[3] 写入结果：HTTP ok，返回 {resp or '{}'}")
    except urllib.error.HTTPError as e:
        print(f"[3] ❌ 写 Secret 失败 HTTP {e.code}：{e.read().decode()[:200]}")
        return 3

    # 4) 确认 Secret 出现在列表里（只读名称，不读值）
    lst = req(f"https://api.github.com/repos/{repo}/actions/secrets", admin)
    names = [s["name"] for s in lst.get("secrets", [])]
    print(f"[4] 现有 Secrets：{names}")
    ok = name in names
    print("[RESULT]", "OK" if ok else "FAIL")
    return 0 if ok else 4


if __name__ == "__main__":
    try:
        code = main()
    finally:
        for p in ("scripts/_cred.txt", "scripts/_pat.txt", "scripts/_cred.err"):
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass
    sys.exit(code)
