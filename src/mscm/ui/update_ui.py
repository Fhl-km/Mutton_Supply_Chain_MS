"""软件更新的 UI 编排：后台检查 / 下载线程 + 弹窗流程。

网络 / 文件动作全在 mscm.check_update，这里只负责"什么时候弹什么窗"。
设置页的「检查更新」按钮和启动自动检查都走这套入口，行为一致。
"""

from __future__ import annotations

import os
import threading
import urllib.parse
import webbrowser

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QApplication, QProgressDialog

from mscm import check_update, config
from mscm.core import repo
from mscm.ui.dialogs import confirm, info

# 线程保活：QThread 被 GC 而 C++ 对象还在跑会 qFatal，切模块级强引用留住。
_live: set[QThread] = set()
_progress: QProgressDialog | None = None
SETTING_AUTO_UPDATE = "auto_update"


def auto_update_enabled(conn) -> bool:
    """设置里是否勾了「自动更新」，默认开。"""
    return repo.get_setting(conn, SETTING_AUTO_UPDATE, "1") != "0"


def set_auto_update(conn, enabled: bool) -> None:
    repo.set_setting(conn, SETTING_AUTO_UPDATE, "1" if enabled else "0")


# ---------------------------------------------------------------- 线程
class _CheckThread(QThread):
    """后台查版本：check() 内部有重试，绝不能放在 UI 线程跑。"""

    result = Signal(object)

    def run(self) -> None:  # noqa: D102
        try:
            data = check_update.check()
        except Exception as e:  # noqa: BLE001
            data = {"status": check_update.ERROR, "version": "", "url": "",
                    "sha256": "", "detail": str(e)}
        self.result.emit(data)


class _DownloadThread(QThread):
    """后台下载安装包，进度 / 完成 / 失败都发信号回 UI 线程。"""

    progressed = Signal(int, int)   # (已下载字节, 总字节；0 表示未知)
    done = Signal(str)              # 下载完成 → 本地路径
    failed = Signal(str)            # 失败原因；空串表示用户取消

    def __init__(self, url: str, sha256: str = "", version: str = "",
                 force: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._url = url
        self._sha256 = sha256
        self._version = version
        self._force = force
        self._cancel = threading.Event()

    def run(self) -> None:  # noqa: D102
        def progress(done: int, total: int) -> None:
            self.progressed.emit(int(done), int(total))

        try:
            path = check_update.download(
                self._url, progress=progress, cancel=self._cancel.is_set,
                sha256=self._sha256, version=self._version, force=self._force)
        except check_update.Cancelled:
            self.failed.emit("")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
        else:
            self.done.emit(str(path))

    def stop(self) -> None:
        self._cancel.set()


def _keep(thread: QThread) -> None:
    _live.add(thread)
    thread.finished.connect(lambda: _live.discard(thread))


def _alive(thread: QThread | None) -> bool:
    return thread is not None and thread.isRunning()


def stop_all() -> None:
    """退出前收尾：停掉在跑的下载线程，关掉进度窗。"""
    global _progress
    for t in list(_live):
        if isinstance(t, _DownloadThread) and t.isRunning():
            t.stop()
    if _progress is not None:
        _progress.close()
        _progress = None


# ---------------------------------------------------------------- 检查入口
def start_check(window, button=None, auto: bool = False) -> None:
    """发起一次版本检查。手动点按钮 auto=False；启动自动检查 auto=True。"""
    if not check_update.configured():
        if not auto:
            info(window, "检查更新", "尚未配置更新地址，暂不能使用自动更新。")
        return
    if check_update.is_preview_version():
        if not auto:
            info(window, "检查更新", "当前是预览版，不参与自动更新。")
        return
    if any(isinstance(t, _CheckThread) and _alive(t) for t in _live):
        return

    if button is not None:
        button.setText("检查中…")

    thread = _CheckThread(window)
    _keep(thread)

    def finished(data: dict) -> None:
        if button is not None:
            button.setText("检查更新")
        _on_checked(window, data, auto=auto)

    thread.result.connect(finished)
    thread.start()


def start_auto_check(window, conn) -> None:
    """启动时调用：开了自动更新且配了地址才在后台查。"""
    if not auto_update_enabled(conn):
        return
    start_check(window, auto=True)


# ---------------------------------------------------------------- 检查结果
def _on_checked(window, data: dict, auto: bool = False) -> None:
    data = data or {}
    status = data.get("status")

    if status == check_update.ERROR:
        if not auto:
            info(window, "检查更新", "检查更新失败：" + (data.get("detail") or "网络不可用"))
        return
    if status == check_update.PREVIEW:
        return
    if status == check_update.LATEST:
        if not auto:
            info(window, "检查更新", f"已是最新版本（v{config.APP_VERSION}）。")
        return
    if status != check_update.NEW:
        return

    version = data.get("version") or "?"
    url = data.get("url") or ""
    if not _is_installer(url):
        if confirm(window, "发现新版本",
                   f"发现新版本 {version}，当前版本 {config.APP_VERSION}。\n是否打开下载页面？"):
            webbrowser.open(url)
        return

    # 本地已有安装包就先用它，省一次下载
    cached = check_update.find_installer(url, data.get("sha256") or "", version)
    if cached is not None:
        if confirm(window, "发现新版本",
                   f"发现新版本 {version}，本地已下载好安装包：\n{cached}\n\n是否直接安装？"):
            _install_update(window, cached, version, confirm_install=False)
        return

    if confirm(window, "发现新版本",
               f"发现新版本 {version}，当前版本 {config.APP_VERSION}。\n是否下载并安装？"):
        _start_download(window, version, url, data.get("sha256") or "")


def _is_installer(url: str) -> bool:
    return os.path.splitext(urllib.parse.urlparse(str(url)).path)[1].lower() in (".exe", ".msi")


# ---------------------------------------------------------------- 下载 / 安装
def _start_download(window, version: str, url: str, sha256: str, force: bool = False) -> None:
    global _progress
    if _progress is not None:
        _progress.close()

    dlg = QProgressDialog("正在下载更新…", "取消", 0, 100, None)
    dlg.setWindowTitle("下载更新")
    dlg.setWindowModality(Qt.NonModal)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    dlg.setMinimumWidth(380)
    dlg.resize(420, dlg.height())
    dlg.show()
    _progress = dlg

    thread = _DownloadThread(url, sha256, version, force, window)
    _keep(thread)

    def on_progress(done: int, total: int) -> None:
        if total > 0:
            if dlg.maximum() != 100:
                dlg.setRange(0, 100)
            dlg.setValue(int(done * 100 / total))
            dlg.setLabelText(f"正在下载 {version}… {_size(done)} / {_size(total)}")
        else:
            if dlg.maximum() != 0:
                dlg.setRange(0, 0)
            dlg.setLabelText(f"正在下载 {version}… 已下载 {_size(done)}")

    def cleanup() -> None:
        dlg.close()
        if _progress is dlg:
            _progress = None

    def on_failed(reason: str) -> None:
        cleanup()
        if reason:
            info(window, "下载失败", reason)

    def on_done(path: str) -> None:
        cleanup()
        _install_update(window, path, version)

    thread.progressed.connect(on_progress)
    thread.failed.connect(on_failed)
    thread.done.connect(on_done)
    thread.finished.connect(cleanup)
    dlg.canceled.connect(thread.stop)
    thread.start()


def _install_update(window, path: str, version: str, confirm_install: bool = True) -> None:
    if confirm_install and not confirm(
            window, "安装更新",
            f"安装包已下载（{version}）：\n{path}\n\n是否立即安装？\n"
            "安装程序会关闭本系统，装完后请重新打开。"):
        return
    try:
        check_update.run_installer(path)
    except Exception as e:  # noqa: BLE001
        info(window, "安装失败", f"无法运行安装包：{e}")
        return
    app = QApplication.instance()
    if app is not None:
        app.quit()


def _size(n: int) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
