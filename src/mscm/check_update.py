"""自动更新网络层：读版本文本 → 比版本 → 下载安装包 → 启动安装。

版本文本格式与 F HamLog 一致，一行三段（第三段可省）：:

    <版本号> <安装包直链> [64位小写sha256]

例：``1.7.0 https://.../Mutton_Supply_Chain_MS_setup.exe abc123...``

本模块只碰网络 / 文件 / 进程，不 import Qt，可独立跑：:

    python -m mscm.check_update

版本号唯一真源取 ``config.APP_VERSION``；检查地址取 ``config.UPDATE_CHECK_URL``。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from mscm import config

# 状态
PREVIEW = "preview"
ERROR = "error"
LATEST = "latest"
NEW = "new"

# 请求参数：带浏览器 UA 绕过 CDN 的 403；永久错误码不必重试
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
TIMEOUT = 10
MAX_RETRIES = 3
MAX_BACKOFF = 5.0
PERMANENT_CODES = (400, 401, 404, 410, 451)
READ_BLOCK = 64 * 1024

# 预览版标记：含这些字样就不参与自动更新
PREVIEW_MARKERS = ("UTC", "Preview", "preview")


class Cancelled(Exception):
    """下载被用户取消。"""


def is_preview_version() -> bool:
    return any(m in config.APP_VERSION for m in PREVIEW_MARKERS)


def _version_tuple(text: str) -> tuple:
    """'1.7.0' → (1, 7, 0)；非纯数字段按字符串原样比。"""
    parts = []
    for seg in str(text or "").strip().split("."):
        parts.append((1, int(seg)) if seg.isdigit() else (0, seg))
    return tuple(parts)


def _same_or_older(remote: str, local: str) -> bool:
    """远端版本 <= 本地版本即视为无需更新。"""
    a, b = _version_tuple(remote), _version_tuple(local)
    n = max(len(a), len(b))
    a += ((0, ""),) * (n - len(a))
    b += ((0, ""),) * (n - len(b))
    return a <= b


def configured() -> bool:
    """是否配置了检查地址。没给网址前所有更新动作都当"未配置"。"""
    return bool((config.UPDATE_CHECK_URL or "").strip())


def get_text(retry: int = 0) -> str:
    """拉取版本文本；网络失败返回空串（调用方据此判 error）。"""
    if not configured():
        return ""
    err: Exception | None = None
    while True:
        try:
            req = urllib.request.Request(config.UPDATE_CHECK_URL, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read().decode("utf-8", errors="replace").strip()
        except urllib.error.HTTPError as e:
            err = e
            if e.code in PERMANENT_CODES:
                return ""
        except Exception as e:  # noqa: BLE001 - 网络层什么异常都可能冒出来
            err = e
        if retry >= MAX_RETRIES:
            _log(f"取版本文本失败：{err}")
            return ""
        retry += 1
        time.sleep(min(0.5 * 2 ** (retry - 1), MAX_BACKOFF))


def parse_text(text: str) -> tuple[str, str, str]:
    """``'1.7.0 https://x/setup.exe [sha256]'`` → (版本, 地址, 摘要)。

    第三段不是 64 位小写十六进制就当没写，免得摘要写错把更新卡死。
    """
    parts = str(text or "").split()
    if len(parts) < 2:
        raise ValueError("版本信息格式不正确：%r" % (text,))
    digest = parts[2].strip().lower() if len(parts) > 2 else ""
    if digest and not re.fullmatch(r"[0-9a-f]{64}", digest):
        digest = ""
    return parts[0], parts[1], digest


def check() -> dict:
    """检查更新，返回 ``dict(status, version, url, sha256, detail)``。

    status 取值：``preview`` / ``error`` / ``latest`` / ``new``。
    只返回结果，不弹窗、不下载 —— UI 决策交给调用方。
    """
    info = {"status": ERROR, "version": "", "url": "", "sha256": "", "detail": ""}
    if not configured():
        info["detail"] = "尚未配置更新地址"
        return info
    if is_preview_version():
        info.update(status=PREVIEW, version=config.APP_VERSION, detail="预览版不参与自动更新")
        return info

    text = get_text()
    if not text:
        info["detail"] = "无法获取版本信息（网络错误或服务器不可用）"
        return info
    try:
        version, url, digest = parse_text(text)
    except ValueError as e:
        info["detail"] = str(e)
        return info

    info.update(
        version=version,
        url=url,
        sha256=digest,
        status=LATEST if _same_or_older(version, config.APP_VERSION) else NEW,
    )
    return info


# ---------------------------------------------------------------- 缓存 / 下载
def update_dir() -> Path:
    """安装包缓存目录：环境变量 MSCM_UPDATE_DIR > LOCALAPPDATA > 系统临时目录。"""
    env = os.environ.get("MSCM_UPDATE_DIR")
    if env:
        p = Path(env)
    else:
        local = os.environ.get("LOCALAPPDATA")
        p = (Path(local) / config.APP_NAME / "update") if local else (Path(os.environ.get("TEMP", "/tmp")) / "mscm_update")
    p.mkdir(parents=True, exist_ok=True)
    return p


def installer_name(url: str) -> str:
    """从直链取文件名；取不到就用固定名。"""
    name = os.path.basename(urllib.parse.urlparse(url).path) or "setup.exe"
    return name if name.lower().endswith((".exe", ".msi")) else name + ".exe"


def _sha256_of(path: Path, cancel: Callable[[], bool] | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            if cancel and cancel():
                raise Cancelled()
            block = f.read(READ_BLOCK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _read_meta(dest: Path) -> dict:
    try:
        return json.loads(dest.with_suffix(dest.suffix + ".json").read_text("utf-8"))
    except Exception:
        return {}


def _write_meta(dest: Path, url: str, version: str, sha256: str) -> None:
    try:
        payload = {"url": url, "version": version, "sha256": sha256}
        dest.with_suffix(dest.suffix + ".json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    except Exception as e:  # 元数据写失败不影响安装包本身
        _log(f"写更新元数据失败：{e}")


def find_installer(url: str, sha256: str = "", version: str = "") -> Path | None:
    """找本地已下好的安装包：文件名对上、摘要对上（给了摘要时）就复用。"""
    dest = update_dir() / installer_name(url)
    if not dest.exists() or dest.stat().st_size == 0:
        return None
    if sha256 and _sha256_of(dest) != sha256:
        return None
    if version:
        meta = _read_meta(dest)
        if meta.get("version") and meta["version"] != version:
            return None
    return dest


def download(
    url: str,
    progress: Callable[[int, int], None] | None = None,
    cancel: Callable[[], bool] | None = None,
    sha256: str = "",
    version: str = "",
    force: bool = False,
) -> Path:
    """下载安装包到缓存目录，成功返回本地路径。

    progress(done, total)：total 为 0 表示未知；cancel() 返回 True 即中止。
    force=True 时忽略本地缓存强制重下。
    """
    if not force:
        cached = find_installer(url, sha256, version)
        if cached is not None:
            _log(f"复用已下载的安装包：{cached}")
            return cached

    dest = update_dir() / installer_name(url)
    tmp = dest.with_suffix(dest.suffix + ".part")
    if tmp.exists():
        tmp.unlink(missing_ok=True)

    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            if progress:
                progress(0, total)
            while True:
                if cancel and cancel():
                    raise Cancelled()
                block = r.read(READ_BLOCK)
                if not block:
                    break
                f.write(block)
                done += len(block)
                if progress:
                    progress(done, total)

        if sha256:
            if cancel and cancel():
                raise Cancelled()
            actual = _sha256_of(tmp, cancel)
            if actual != sha256:
                raise ValueError("安装包摘要校验失败，可能下载不完整或被篡改")
        os.replace(tmp, dest)
    except Cancelled:
        tmp.unlink(missing_ok=True)
        raise
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    _write_meta(dest, url, version, sha256)
    return dest


def run_installer(path: str | Path, silent: bool = True) -> subprocess.Popen:
    """运行 Inno Setup 安装包；调用方一般紧接着退出主程序。"""
    path = str(Path(path).resolve())
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    args = [path]
    if silent:
        args += ["/SILENT", "/CLOSEAPPLICATIONS", "/NORESTART"]
    return subprocess.Popen(args, cwd=os.path.dirname(path) or ".", close_fds=True)


def _log(message: str) -> None:
    try:
        if os.environ.get("MSCM_UPDATE_DEBUG") and sys.stdout is not None:
            print("[update] " + message, flush=True)
    except Exception:
        pass


if __name__ == "__main__":
    print(config.APP_NAME, config.APP_VERSION)
    print(check())
