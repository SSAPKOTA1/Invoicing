# -*- mode: python ; coding: utf-8 -*-
# PyInstaller one-folder build. Two launchers share one folder:
#   SupplierApp.exe         windowed (double-click)
#   SupplierAppConsole.exe  console (for --selfcheck / --reset-pin)
# Tesseract is copied next to the executables by scripts/build_exe.ps1 (folder "tesseract").
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent
datas = [
    (str(ROOT / "supplier_app" / "i18n" / "de.json"), "supplier_app/i18n"),
    (str(ROOT / "supplier_app" / "i18n" / "en.json"), "supplier_app/i18n"),
    (str(ROOT / "supplier_app" / "views" / "themes" / "dark.qss"), "supplier_app/views/themes"),
    (str(ROOT / "supplier_app" / "views" / "themes" / "light.qss"), "supplier_app/views/themes"),
]
datas += collect_data_files("pymupdf", include_py_files=False)
hidden = [
    "supplier_app.database.migrations.m001_core",
    "supplier_app.database.migrations.m002_references_search",
    "supplier_app.database.migrations.m003_reporting_indexes",
    "PySide6.QtCharts",
    "PySide6.QtPrintSupport",
]
excludes = ["tkinter", "pytest", "matplotlib", "scipy", "pandas", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore",
            "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtMultimedia"]

a = Analysis([str(ROOT / "run_supplierapp.py")], pathex=[str(ROOT)], datas=datas, hiddenimports=hidden,
             excludes=excludes, noarchive=False)
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SupplierApp", console=False, debug=False, upx=False)
console = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SupplierAppConsole", console=True, debug=False, upx=False)
coll = COLLECT(gui, console, a.binaries, a.datas, strip=False, upx=False, name="SupplierApp")
