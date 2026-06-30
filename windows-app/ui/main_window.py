"""
RouteBuddy main window.
"""
import sys
from pathlib import Path
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QLineEdit, QFileDialog, QTableWidget, QTableWidgetItem,
    QMessageBox, QProgressBar, QSplitter, QGroupBox, QCheckBox,
    QHeaderView, QAbstractItemView, QStatusBar, QDialog,
    QComboBox, QDialogButtonBox, QTextEdit, QApplication,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QMimeData
from PyQt6.QtGui import QColor, QFont, QDragEnterEvent, QDropEvent

from core import config as cfg_module
from core.route_optimizer import Stop, optimize
from core.geocoder import get_geocoder, GeocodeError
from core.photo_extractor import extract_from_photo
from core import csv_importer


# ── Worker thread for geocoding (keeps UI responsive) ──────────────────────
class GeocodeWorker(QThread):
    progress = pyqtSignal(int, int, str)   # current, total, address
    finished = pyqtSignal(list)            # list[Stop] with lat/lng filled

    def __init__(self, stops: list[Stop], city_bias: str):
        super().__init__()
        self.stops = stops
        self.city_bias = city_bias

    def run(self):
        geocoder = get_geocoder(self.city_bias)
        total = len(self.stops)
        for i, stop in enumerate(self.stops):
            self.progress.emit(i + 1, total, stop.raw_address)
            try:
                result = geocoder.geocode(stop.raw_address)
                stop.lat = result.lat
                stop.lng = result.lng
            except GeocodeError as e:
                stop.geocode_error = str(e)
        self.finished.emit(self.stops)


# ── Column mapping dialog (CSV import) ─────────────────────────────────────
class ColumnMappingDialog(QDialog):
    def __init__(self, columns: list[str], guess: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Map Spreadsheet Columns")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Tell RouteBuddy which columns contain each field.\nThis will be remembered for next time."))

        self.combos = {}
        fields = [("address", "Street Address *"), ("customer_name", "Customer Name"), ("notes", "Notes / Gate Codes")]
        for field, label in fields:
            row = QHBoxLayout()
            row.addWidget(QLabel(label + ":"))
            combo = QComboBox()
            combo.addItem("(none)")
            for col in columns:
                combo.addItem(col)
            if guess.get(field) in columns:
                combo.setCurrentText(guess[field])
            row.addWidget(combo)
            layout.addLayout(row)
            self.combos[field] = combo

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_mapping(self) -> dict:
        result = {}
        for field, combo in self.combos.items():
            val = combo.currentText()
            result[field] = val if val != "(none)" else None
        return result


# ── Photo review dialog ─────────────────────────────────────────────────────
class PhotoReviewDialog(QDialog):
    def __init__(self, extracted: list[dict], skip_struck: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review Extracted Addresses")
        self.setMinimumSize(700, 500)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            "Claude extracted the addresses below from your photo.\n"
            "Review and correct anything misread before adding to route.\n"
            "Struck-through rows (grey) are marked as completed — uncheck to include them."
        ))

        self.table = QTableWidget(len(extracted), 4)
        self.table.setHorizontalHeaderLabels(["Include", "Customer", "Address", "Notes"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        for row, entry in enumerate(extracted):
            struck = entry.get("struck_through", False)

            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Unchecked if (struck and skip_struck) else Qt.CheckState.Checked)
            self.table.setItem(row, 0, chk)

            for col, key in [(1, "customer_name"), (2, "address"), (3, "notes")]:
                item = QTableWidgetItem(entry.get(key, ""))
                if struck:
                    item.setForeground(QColor("#999999"))
                self.table.setItem(row, col, item)

        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_selected(self) -> list[dict]:
        result = []
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked:
                result.append({
                    "customer_name": self.table.item(row, 1).text().strip(),
                    "address": self.table.item(row, 2).text().strip(),
                    "notes": self.table.item(row, 3).text().strip(),
                })
        return result


# ── Main window ─────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = cfg_module.load()
        self.stops: list[Stop] = []
        self.optimized: list[Stop] = []
        self.failed: list[Stop] = []
        self._worker = None
        self.setWindowTitle("RouteBuddy — Route Optimizer")
        self.setMinimumSize(1000, 700)
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)

        # ── Top toolbar ──
        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel("City / Area:"))
        self.city_input = QLineEdit(self.cfg.get("city_bias", ""))
        self.city_input.setPlaceholderText("e.g. Okotoks, AB  or  Calgary, AB")
        self.city_input.setFixedWidth(220)
        self.city_input.textChanged.connect(self._save_city)
        toolbar.addWidget(self.city_input)

        toolbar.addSpacing(16)

        btn_photo = QPushButton("Import from Photo")
        btn_photo.setToolTip("Take/select a photo of your paper route list")
        btn_photo.clicked.connect(self._import_photo)
        toolbar.addWidget(btn_photo)

        btn_csv = QPushButton("Import CSV / Excel")
        btn_csv.clicked.connect(self._import_csv)
        toolbar.addWidget(btn_csv)

        btn_clear = QPushButton("Clear All")
        btn_clear.clicked.connect(self._clear)
        toolbar.addWidget(btn_clear)

        toolbar.addStretch()

        btn_optimize = QPushButton("▶  Optimize Route")
        btn_optimize.setStyleSheet("font-weight: bold; padding: 4px 16px;")
        btn_optimize.clicked.connect(self._run_optimize)
        toolbar.addWidget(btn_optimize)

        btn_export = QPushButton("Export Route")
        btn_export.clicked.connect(self._export)
        toolbar.addWidget(btn_export)

        btn_settings = QPushButton("⚙ Settings")
        btn_settings.clicked.connect(self._open_settings)
        toolbar.addWidget(btn_settings)

        root.addLayout(toolbar)

        # ── Main split: original | optimized ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_box = QGroupBox("Imported Stops (original order)")
        left_layout = QVBoxLayout(left_box)
        self.orig_table = self._make_table()
        left_layout.addWidget(self.orig_table)
        splitter.addWidget(left_box)

        right_box = QGroupBox("Optimized Route")
        right_layout = QVBoxLayout(right_box)
        self.opt_table = self._make_table(show_stop_num=True)
        right_layout.addWidget(self.opt_table)
        splitter.addWidget(right_box)

        splitter.setSizes([480, 480])
        root.addWidget(splitter, stretch=1)

        # ── Progress + status ──
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready — import a photo or CSV to begin.")

    def _make_table(self, show_stop_num: bool = False) -> QTableWidget:
        headers = (["#", "Customer", "Address", "Notes", "Status"] if show_stop_num
                   else ["#", "Customer", "Address", "Notes"])
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        t.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.verticalHeader().setDefaultSectionSize(24)
        t.setAlternatingRowColors(True)
        return t

    # ── Import handlers ──────────────────────────────────────────────────────

    def _import_photo(self):
        if not self.cfg.get("claude_api_key"):
            QMessageBox.warning(self, "API Key Required",
                "A Claude API key is needed for photo extraction.\n"
                "Go to ⚙ Settings to add your key.")
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Select Route Photo", "",
            "Images (*.jpg *.jpeg *.png *.webp);;All Files (*)")
        if not path:
            return

        self.status.showMessage("Extracting addresses from photo…")
        QApplication.processEvents()
        try:
            extracted = extract_from_photo(path, self.cfg["claude_api_key"])
        except Exception as e:
            QMessageBox.critical(self, "Extraction Failed", str(e))
            self.status.showMessage("Photo extraction failed.")
            return

        if not extracted:
            QMessageBox.warning(self, "Nothing Found", "No addresses were found in the photo.")
            return

        dlg = PhotoReviewDialog(extracted, self.cfg.get("skip_struck_through", True), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        selected = dlg.get_selected()
        if not selected:
            return

        city = self.city_input.text().strip()
        for i, entry in enumerate(selected):
            addr = entry["address"]
            if city and not any(c in addr.lower() for c in [",", "ab", "alberta"]):
                addr = f"{addr}, {city}"
            stop = Stop(
                index=len(self.stops) + i,
                raw_address=addr,
                customer_name=entry.get("customer_name", ""),
                notes=entry.get("notes", ""),
            )
            self.stops.append(stop)

        self._refresh_orig_table()
        self.status.showMessage(f"Added {len(selected)} stops from photo. Click 'Optimize Route' when ready.")

    def _import_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select CSV or Excel File", "",
            "Spreadsheets (*.csv *.xlsx *.xls);;All Files (*)")
        if not path:
            return

        try:
            df = csv_importer.load_file(path)
        except Exception as e:
            QMessageBox.critical(self, "Import Error", str(e))
            return

        columns = list(df.columns)
        saved = csv_importer.load_saved_mapping()
        if saved and set(saved["source_columns"]) == set(columns):
            mapping = saved["mapping"]
        else:
            guess = csv_importer.guess_mapping(columns)
            dlg = ColumnMappingDialog(columns, guess, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            mapping = dlg.get_mapping()
            csv_importer.save_mapping(mapping, columns)

        try:
            rows, skipped = csv_importer.apply_mapping(df, mapping)
        except ValueError as e:
            QMessageBox.critical(self, "Mapping Error", str(e))
            return

        city = self.city_input.text().strip()
        for i, row in enumerate(rows):
            addr = row["address"]
            if city and not any(c in addr.lower() for c in [",", "ab", "alberta"]):
                addr = f"{addr}, {city}"
            self.stops.append(Stop(
                index=len(self.stops) + i,
                raw_address=addr,
                customer_name=row.get("customer_name", ""),
                notes=row.get("notes", ""),
            ))

        self._refresh_orig_table()
        msg = f"Imported {len(rows)} stops."
        if skipped:
            msg += f"  {len(skipped)} blank rows skipped (rows {', '.join(str(r) for r in skipped[:5])}{'…' if len(skipped) > 5 else ''})."
        self.status.showMessage(msg)

    # ── Geocoding + optimization ─────────────────────────────────────────────

    def _run_optimize(self):
        if not self.stops:
            QMessageBox.information(self, "No Stops", "Import some addresses first.")
            return

        ungeooded = [s for s in self.stops if s.lat is None and s.geocode_error is None]
        if not ungeooded:
            self._do_optimize()
            return

        city = self.city_input.text().strip()
        if not city:
            reply = QMessageBox.question(self, "No City Set",
                "No city/area is set — geocoding may resolve to wrong province.\n\nProceed anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.progress_bar.setMaximum(len(ungeooded))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)

        self._worker = GeocodeWorker(ungeooded, city)
        self._worker.progress.connect(self._on_geocode_progress)
        self._worker.finished.connect(self._on_geocode_done)
        self._worker.start()

    def _on_geocode_progress(self, current: int, total: int, address: str):
        self.progress_bar.setValue(current)
        self.status.showMessage(f"Geocoding {current}/{total}: {address}")

    def _on_geocode_done(self, stops: list[Stop]):
        self.progress_bar.setVisible(False)
        self._do_optimize()

    def _do_optimize(self):
        optimized, failed = optimize(self.stops)
        self.optimized = optimized
        self.failed = failed

        self.opt_table.setRowCount(0)
        for stop_num, stop in enumerate(optimized, 1):
            row = self.opt_table.rowCount()
            self.opt_table.insertRow(row)
            self.opt_table.setItem(row, 0, QTableWidgetItem(str(stop_num)))
            self.opt_table.setItem(row, 1, QTableWidgetItem(stop.customer_name))
            self.opt_table.setItem(row, 2, QTableWidgetItem(stop.raw_address))
            self.opt_table.setItem(row, 3, QTableWidgetItem(stop.notes))
            self.opt_table.setItem(row, 4, QTableWidgetItem("✓ Ready"))

        for stop in failed:
            row = self.opt_table.rowCount()
            self.opt_table.insertRow(row)
            self.opt_table.setItem(row, 0, QTableWidgetItem("!"))
            self.opt_table.setItem(row, 1, QTableWidgetItem(stop.customer_name))
            self.opt_table.setItem(row, 2, QTableWidgetItem(stop.raw_address))
            self.opt_table.setItem(row, 3, QTableWidgetItem(stop.notes))
            err_item = QTableWidgetItem(f"GEOCODE FAILED: {stop.geocode_error}")
            err_item.setForeground(QColor("#cc0000"))
            self.opt_table.setItem(row, 4, err_item)
            for col in range(5):
                if self.opt_table.item(row, col):
                    self.opt_table.item(row, col).setBackground(QColor("#fff0f0"))

        msg = f"Optimized {len(optimized)} stops."
        if failed:
            msg += f"  ⚠ {len(failed)} address(es) could not be geocoded — shown in red at the bottom."
        self.status.showMessage(msg)

        if failed:
            names = "\n".join(f"  • {s.raw_address}  ({s.geocode_error})" for s in failed)
            QMessageBox.warning(self, "Geocoding Failures",
                f"{len(failed)} address(es) could not be located and are placed at the end of the route:\n\n{names}\n\n"
                "Check for typos or try a more specific address.")

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _refresh_orig_table(self):
        self.orig_table.setRowCount(0)
        for i, stop in enumerate(self.stops, 1):
            row = self.orig_table.rowCount()
            self.orig_table.insertRow(row)
            self.orig_table.setItem(row, 0, QTableWidgetItem(str(i)))
            self.orig_table.setItem(row, 1, QTableWidgetItem(stop.customer_name))
            self.orig_table.setItem(row, 2, QTableWidgetItem(stop.raw_address))
            self.orig_table.setItem(row, 3, QTableWidgetItem(stop.notes))

    def _clear(self):
        self.stops.clear()
        self.optimized.clear()
        self.failed.clear()
        self.orig_table.setRowCount(0)
        self.opt_table.setRowCount(0)
        self.status.showMessage("Cleared.")

    def _save_city(self, text: str):
        self.cfg["city_bias"] = text
        cfg_module.save(self.cfg)

    def _export(self):
        if not self.optimized:
            QMessageBox.information(self, "Nothing to Export", "Optimize a route first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Route", "route.txt", "Text Files (*.txt);;CSV (*.csv)")
        if not path:
            return
        lines = ["OPTIMIZED ROUTE\n" + "=" * 40]
        for i, stop in enumerate(self.optimized, 1):
            line = f"{i:3}. {stop.raw_address}"
            if stop.customer_name:
                line += f"  [{stop.customer_name}]"
            if stop.notes:
                line += f"  — {stop.notes}"
            lines.append(line)
        if self.failed:
            lines.append("\nCOULD NOT GEOCODE (verify manually):")
            for stop in self.failed:
                lines.append(f"  ✗ {stop.raw_address}  ({stop.geocode_error})")
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        self.status.showMessage(f"Exported to {path}")

    def _open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.cfg.update(dlg.get_values())
            self.city_input.setText(self.cfg.get("city_bias", ""))
            cfg_module.save(self.cfg)


# ── Settings dialog ──────────────────────────────────────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(450)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Claude API Key (for photo extraction):"))
        self.api_key = QLineEdit(cfg.get("claude_api_key", ""))
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("sk-ant-…")
        layout.addWidget(self.api_key)

        layout.addWidget(QLabel("Default City / Area:"))
        self.city = QLineEdit(cfg.get("city_bias", ""))
        self.city.setPlaceholderText("e.g. Okotoks, AB")
        layout.addWidget(self.city)

        self.skip_struck = QCheckBox("Skip struck-through addresses in photos (treat as completed)")
        self.skip_struck.setChecked(cfg.get("skip_struck_through", True))
        layout.addWidget(self.skip_struck)

        layout.addWidget(QLabel(
            "\nNote: The Claude API key is stored locally in\n~/.routebuddy/config.json and never sent anywhere\nexcept Anthropic's API for photo processing.",
            styleSheet="color: #666; font-size: 11px;"
        ))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self) -> dict:
        return {
            "claude_api_key": self.api_key.text().strip(),
            "city_bias": self.city.text().strip(),
            "skip_struck_through": self.skip_struck.isChecked(),
        }
