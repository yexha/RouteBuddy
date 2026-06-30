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
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from core import config as cfg_module
from core.route_optimizer import Stop, optimize
from core.geocoder import get_geocoder, GeocodeError
from core.photo_extractor import extract_from_photo
from core import csv_importer


# ── Worker: geocoding (runs off UI thread) ─────────────────────────────────
class GeocodeWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)

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


# ── Worker: OCR photo (can be slow on first run while model loads) ──────────
class PhotoWorker(QThread):
    finished = pyqtSignal(list, list, str)   # (addresses, skipped, error_message)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        try:
            addresses, skipped = extract_from_photo(self.path)
            self.finished.emit(addresses, skipped, "")
        except Exception as e:
            self.finished.emit([], [], str(e))


# ── Column mapping dialog ───────────────────────────────────────────────────
class ColumnMappingDialog(QDialog):
    def __init__(self, columns: list[str], guess: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Map Spreadsheet Columns")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Tell RouteBuddy which columns contain each field.\n"
            "This will be remembered for next time."
        ))
        self.combos = {}
        for field, label in [("address", "Street Address *"), ("customer_name", "Customer Name"), ("notes", "Notes / Gate Codes")]:
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
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_mapping(self) -> dict:
        return {f: (c.currentText() if c.currentText() != "(none)" else None) for f, c in self.combos.items()}


# ── Photo review dialog ─────────────────────────────────────────────────────
class PhotoReviewDialog(QDialog):
    def __init__(self, addresses: list[dict], skipped: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review Addresses")
        self.setMinimumSize(560, 540)
        layout = QVBoxLayout(self)

        info = QLabel(
            "RouteBuddy read these addresses from your photo.\n"
            "Grey rows were crossed out on the paper (already done) — included so you\n"
            "can verify, but unchecked by default.\n\n"
            "Double-click an address to fix a misread before adding it to the route."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.table = QTableWidget(len(addresses), 2)
        self.table.setHorizontalHeaderLabels(["Include", "Address"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 70)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        DONE_BG = QColor("#e8e8e8")
        DONE_FG = QColor("#888888")

        for row, entry in enumerate(addresses):
            struck = entry.get("struck_through", False)

            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            # Struck-through = already done → unchecked by default, but included so driver can verify
            chk.setCheckState(Qt.CheckState.Unchecked if struck else Qt.CheckState.Checked)
            self.table.setItem(row, 0, chk)

            item = QTableWidgetItem(entry.get("address", ""))
            if struck:
                item.setBackground(DONE_BG)
                item.setForeground(DONE_FG)
            self.table.setItem(row, 1, item)

        layout.addWidget(self.table)

        if skipped:
            note = QLabel(
                f"⚠ {len(skipped)} line(s) had a number but no readable address and were "
                f"left out:\n  " + "\n  ".join(skipped[:6]) +
                ("\n  …" if len(skipped) > 6 else "")
            )
            note.setWordWrap(True)
            note.setStyleSheet("color: #cc6600; font-size: 11px;")
            layout.addWidget(note)

        # Select/deselect all buttons
        btn_row = QHBoxLayout()
        btn_all = QPushButton("Check All")
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none = QPushButton("Uncheck All")
        btn_none.clicked.connect(lambda: self._set_all(False))
        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_none)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _set_all(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(state)

    def get_selected(self) -> list[dict]:
        results = []
        for row in range(self.table.rowCount()):
            results.append({
                "include": self.table.item(row, 0).checkState() == Qt.CheckState.Checked,
                "address": self.table.item(row, 1).text().strip(),
            })
        return results


# ── Settings dialog ──────────────────────────────────────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Default City / Area:"))
        self.city = QLineEdit(cfg.get("city_bias", ""))
        self.city.setPlaceholderText("e.g. Okotoks, AB")
        layout.addWidget(self.city)

        layout.addWidget(QLabel(
            "\nPhoto OCR runs locally on your computer — no internet or API key needed.\n"
            "First load takes ~30 seconds while the OCR model initialises.",
            styleSheet="color: #555; font-size: 11px;"
        ))

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_values(self) -> dict:
        return {"city_bias": self.city.text().strip()}


# ── Main window ─────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = cfg_module.load()
        self.stops: list[Stop] = []
        self.optimized: list[Stop] = []
        self.failed: list[Stop] = []
        self._geo_worker = None
        self._photo_worker = None
        self.setWindowTitle("RouteBuddy — Route Optimizer")
        self.setMinimumSize(1050, 720)
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)

        # ── Toolbar ──
        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel("City / Area:"))
        self.city_input = QLineEdit(self.cfg.get("city_bias", ""))
        self.city_input.setPlaceholderText("e.g. Okotoks, AB  or  Calgary, AB")
        self.city_input.setFixedWidth(230)
        self.city_input.textChanged.connect(self._save_city)
        toolbar.addWidget(self.city_input)

        toolbar.addSpacing(12)

        self.btn_photo = QPushButton("📷  Import from Photo")
        self.btn_photo.setToolTip("Select a photo of your paper route list — OCR runs locally, no internet needed")
        self.btn_photo.clicked.connect(self._import_photo)
        toolbar.addWidget(self.btn_photo)

        btn_csv = QPushButton("📄  Import CSV / Excel")
        btn_csv.clicked.connect(self._import_csv)
        toolbar.addWidget(btn_csv)

        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self._clear)
        toolbar.addWidget(btn_clear)

        toolbar.addStretch()

        self.btn_optimize = QPushButton("▶  Optimize Route")
        self.btn_optimize.setStyleSheet("font-weight: bold; padding: 4px 18px; background: #2a6ebb; color: white;")
        self.btn_optimize.clicked.connect(self._run_optimize)
        toolbar.addWidget(self.btn_optimize)

        btn_export = QPushButton("Export")
        btn_export.clicked.connect(self._export)
        toolbar.addWidget(btn_export)

        root.addLayout(toolbar)

        # ── City hint label ──
        self.city_hint = QLabel("")
        self.city_hint.setStyleSheet("color: #cc6600; font-size: 11px; padding-left: 4px;")
        root.addWidget(self.city_hint)
        self._update_city_hint()
        self.city_input.textChanged.connect(lambda _: self._update_city_hint())

        # ── Split: original | optimized ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_box = QGroupBox("Imported Stops — original order")
        left_layout = QVBoxLayout(left_box)
        self.orig_table = self._make_table(["#", "Customer", "Address", "Notes"])
        left_layout.addWidget(self.orig_table)
        splitter.addWidget(left_box)

        right_box = QGroupBox("Optimized Route — right-side sweep")
        right_layout = QVBoxLayout(right_box)
        self.opt_table = self._make_table(["#", "Customer", "Address", "Notes", "Status"])
        right_layout.addWidget(self.opt_table)
        splitter.addWidget(right_box)

        splitter.setSizes([490, 490])
        root.addWidget(splitter, stretch=1)

        # ── Progress ──
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("font-size: 11px; color: #444;")
        root.addWidget(self.progress_bar)
        root.addWidget(self.progress_label)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready — set your city above, then import a photo or CSV.")

    def _make_table(self, headers: list[str]) -> QTableWidget:
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        addr_col = 2 if len(headers) >= 3 else 0
        t.horizontalHeader().setSectionResizeMode(addr_col, QHeaderView.ResizeMode.Stretch)
        t.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.verticalHeader().setDefaultSectionSize(22)
        t.setAlternatingRowColors(True)
        return t

    def _update_city_hint(self):
        if not self.city_input.text().strip():
            self.city_hint.setText("⚠  Set a city/area so addresses resolve to the right location in Alberta.")
        else:
            self.city_hint.setText("")

    # ── Photo import ─────────────────────────────────────────────────────────

    def _import_photo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Route Photo", "",
            "Images (*.jpg *.jpeg *.png *.webp *.bmp);;All Files (*)")
        if not path:
            return

        self.btn_photo.setEnabled(False)
        self.btn_photo.setText("Reading photo…")
        self.progress_label.setText("Loading OCR model (first time takes ~30 sec)…")
        QApplication.processEvents()

        self._photo_worker = PhotoWorker(path)
        self._photo_worker.finished.connect(self._on_photo_done)
        self._photo_worker.start()

    def _on_photo_done(self, addresses: list, skipped: list, error: str):
        self.btn_photo.setEnabled(True)
        self.btn_photo.setText("📷  Import from Photo")
        self.progress_label.setText("")

        if error:
            QMessageBox.critical(self, "Photo Read Failed",
                f"Could not read addresses from photo:\n\n{error}")
            self.status.showMessage("Photo import failed.")
            return

        if not addresses:
            extra = ""
            if skipped:
                extra = ("\n\nLines with text but no readable address:\n  "
                         + "\n  ".join(skipped[:8]))
            QMessageBox.warning(self, "No Addresses Found",
                "No addresses could be read from the photo. Try a clearer, "
                "straight-on photo with good lighting." + extra)
            return

        dlg = PhotoReviewDialog(addresses, skipped, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        selected = dlg.get_selected()
        added = 0
        city = self.city_input.text().strip()

        for entry in selected:
            addr = entry["address"]
            if not addr:
                continue
            if city and "," not in addr:
                addr = f"{addr}, {city}"

            stop = Stop(
                index=len(self.stops),
                raw_address=addr,
                customer_name="",
                notes="",
                is_done=not entry["include"],
            )
            self.stops.append(stop)
            added += 1

        self._refresh_orig_table()
        msg = f"Added {added} address(es) from photo. Click '▶ Optimize Route' when ready."
        if skipped:
            msg += f"  ({len(skipped)} unreadable line(s) left out.)"
        self.status.showMessage(msg)

    # ── CSV import ────────────────────────────────────────────────────────────

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
        for row in rows:
            addr = row["address"]
            if city and "," not in addr:
                addr = f"{addr}, {city}"
            self.stops.append(Stop(
                index=len(self.stops),
                raw_address=addr,
                customer_name=row.get("customer_name", ""),
                notes=row.get("notes", ""),
            ))

        self._refresh_orig_table()
        msg = f"Imported {len(rows)} stops."
        if skipped:
            msg += f"  {len(skipped)} blank rows skipped."
        self.status.showMessage(msg)

    # ── Optimize ──────────────────────────────────────────────────────────────

    def _run_optimize(self):
        if not self.stops:
            QMessageBox.information(self, "No Stops", "Import some addresses first.")
            return

        city = self.city_input.text().strip()
        if not city:
            reply = QMessageBox.question(self, "No City Set",
                "No city/area is set.\nGeocoding may pick the wrong location.\n\nProceed anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return

        ungeooded = [s for s in self.stops if s.lat is None and not s.geocode_error]
        if not ungeooded:
            self._do_optimize()
            return

        self.btn_optimize.setEnabled(False)
        self.progress_bar.setMaximum(len(ungeooded))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.progress_label.setText(f"Geocoding 0/{len(ungeooded)}…")

        self._geo_worker = GeocodeWorker(ungeooded, city)
        self._geo_worker.progress.connect(self._on_geo_progress)
        self._geo_worker.finished.connect(self._on_geo_done)
        self._geo_worker.start()

    def _on_geo_progress(self, current: int, total: int, address: str):
        self.progress_bar.setValue(current)
        self.progress_label.setText(f"Geocoding {current}/{total}: {address}")

    def _on_geo_done(self, _):
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")
        self.btn_optimize.setEnabled(True)
        self._do_optimize()

    def _do_optimize(self):
        optimized, failed = optimize(self.stops)
        self.optimized = optimized
        self.failed = failed

        DONE_BG = QColor("#e8e8e8")
        DONE_FG = QColor("#888888")
        ERROR_BG = QColor("#fff0f0")
        ERROR_FG = QColor("#cc0000")

        self.opt_table.setRowCount(0)
        stop_num = 0

        for stop in optimized:
            stop_num += 1
            row = self.opt_table.rowCount()
            self.opt_table.insertRow(row)

            num_item = QTableWidgetItem(str(stop_num))
            if stop.is_done:
                num_item.setText(f"✓{stop_num}")
            self.opt_table.setItem(row, 0, num_item)
            self.opt_table.setItem(row, 1, QTableWidgetItem(stop.customer_name))
            self.opt_table.setItem(row, 2, QTableWidgetItem(stop.raw_address))
            self.opt_table.setItem(row, 3, QTableWidgetItem(stop.notes))
            status = QTableWidgetItem("Done" if stop.is_done else "")
            self.opt_table.setItem(row, 4, status)

            if stop.is_done:
                for col in range(5):
                    if self.opt_table.item(row, col):
                        self.opt_table.item(row, col).setBackground(DONE_BG)
                        self.opt_table.item(row, col).setForeground(DONE_FG)

        for stop in failed:
            row = self.opt_table.rowCount()
            self.opt_table.insertRow(row)
            self.opt_table.setItem(row, 0, QTableWidgetItem("!"))
            self.opt_table.setItem(row, 1, QTableWidgetItem(stop.customer_name))
            self.opt_table.setItem(row, 2, QTableWidgetItem(stop.raw_address))
            self.opt_table.setItem(row, 3, QTableWidgetItem(stop.notes))
            self.opt_table.setItem(row, 4, QTableWidgetItem(f"GEOCODE FAILED: {stop.geocode_error}"))
            for col in range(5):
                if self.opt_table.item(row, col):
                    self.opt_table.item(row, col).setBackground(ERROR_BG)
                    self.opt_table.item(row, col).setForeground(ERROR_FG)

        msg = f"Optimized {len(optimized)} stops."
        if failed:
            msg += f"  ⚠ {len(failed)} address(es) could not be geocoded — shown in red."
        self.status.showMessage(msg)

        if failed:
            names = "\n".join(f"  • {s.raw_address}  ({s.geocode_error})" for s in failed)
            QMessageBox.warning(self, "Geocoding Failures",
                f"{len(failed)} address(es) could not be located:\n\n{names}\n\n"
                "Check for typos. They appear at the bottom of the route list.")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _refresh_orig_table(self):
        self.orig_table.setRowCount(0)
        for i, stop in enumerate(self.stops, 1):
            row = self.orig_table.rowCount()
            self.orig_table.insertRow(row)
            self.orig_table.setItem(row, 0, QTableWidgetItem(str(i)))
            self.orig_table.setItem(row, 1, QTableWidgetItem(stop.customer_name))
            self.orig_table.setItem(row, 2, QTableWidgetItem(stop.raw_address))
            self.orig_table.setItem(row, 3, QTableWidgetItem(stop.notes))
            if stop.is_done:
                for col in range(4):
                    if self.orig_table.item(row, col):
                        self.orig_table.item(row, col).setForeground(QColor("#999999"))

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
        lines = ["OPTIMIZED ROUTE — RouteBuddy", "=" * 50]
        for i, stop in enumerate(self.optimized, 1):
            status = " [DONE]" if stop.is_done else ""
            line = f"{i:3}.{status} {stop.raw_address}"
            if stop.customer_name:
                line += f"  [{stop.customer_name}]"
            if stop.notes:
                line += f"  — {stop.notes}"
            lines.append(line)
        if self.failed:
            lines += ["", "COULD NOT GEOCODE — verify manually:"]
            for stop in self.failed:
                lines.append(f"  ✗ {stop.raw_address}  ({stop.geocode_error})")
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        self.status.showMessage(f"Route exported to {path}")
