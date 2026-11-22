import os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
TMP = Path(tempfile.mkdtemp(prefix="mscm_grab_"))
os.environ["MSCM_DATA_DIR"] = str(TMP / "data")
os.environ["QT_QPA_PLATFORM"] = "windows"
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from mscm.core import bootstrap
from mscm.core.db import open_database
from mscm.ui import theme
from mscm.ui.main_window import MainWindow
SHOTS = ROOT / "scripts" / "_shots_real"; SHOTS.mkdir(exist_ok=True)
app = QApplication(sys.argv); theme.apply_theme(app)
conn = open_database(TMP / "data" / "g.mscm.json"); bootstrap.ensure_seed_data(conn)
win = MainWindow(conn); win.resize(1560, 940); win.show()
def go():
    for key in ["dashboard","feed","breeding","slaughter","slaughter_out","store-1-in","store-1-sale","store-1-stock","check","batches","products","stores","settings"]:
        win.show_page(key); app.processEvents()
        win.grab().save(str(SHOTS / f"{key}.png"))
    app.quit()
QTimer.singleShot(600, go)
app.exec()
conn.close(); print("done", TMP)
