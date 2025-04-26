import sys
import os
import json
import logging

import ebooklib
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QComboBox, QTextEdit, QMessageBox,
    QProgressBar, QGroupBox, QListWidget, QListWidgetItem, QSlider,
    QCheckBox, QDialog, QFormLayout, QSpinBox, QDialogButtonBox, QMenuBar
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QMutex, QWaitCondition

from epub_parser import parse_epub
from cost_estimator import estimate_abridgment_cost
from summarizer import SummarizationEngine
from epub_builder import build_epub
from llm_config import (
    get_available_models, get_default_model,
    DEFAULT_TEMPERATURE, SHORT_CHAPTER_WORD_LIMIT
)

# ------------------------------------------------------------------
# Constants for settings persistence
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "user_settings.json")
# ------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(module)s] %(message)s'
)

def load_user_settings() -> dict:
    """Load per-user GUI overrides, or fall back to config defaults."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            logging.warning("Could not read user_settings.json; using defaults.")
    # defaults from config
    return {
        "provider":    "google",
        "model":       get_default_model("google") or "",
        "temperature": DEFAULT_TEMPERATURE,
        "skip_estimation": True,
        "short_chapter_word_limit": SHORT_CHAPTER_WORD_LIMIT
    }

def save_user_settings(settings: dict):
    """Persist user settings to disk."""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        logging.info("User settings saved.")
    except Exception as e:
        logging.error(f"Failed to save user settings: {e}")

# ------------------------------------------------------------------
# Settings Dialog
class SettingsDialog(QDialog):
    def __init__(self, parent, current_settings):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.settings = current_settings.copy()

        layout = QFormLayout(self)

        # Provider & Model
        self.provider_cb = QComboBox()
        self.provider_cb.addItems(["google", "ollama", "openrouter"])
        self.provider_cb.setCurrentText(self.settings["provider"])
        self.provider_cb.currentTextChanged.connect(self._on_provider_change)
        layout.addRow("Default Provider:", self.provider_cb)

        self.model_cb = QComboBox()
        self.model_cb.setEditable(True)
        layout.addRow("Default Model:", self.model_cb)

        # Temperature slider
        self.temp_slider = QSlider(Qt.Orientation.Horizontal)
        self.temp_slider.setRange(0,100)
        self.temp_slider.setValue(int(self.settings["temperature"]*100))
        self.temp_label = QLabel(f"{self.settings['temperature']:.2f}")
        self.temp_slider.valueChanged.connect(self._on_temp_change)
        hl = QHBoxLayout()
        hl.addWidget(self.temp_slider); hl.addWidget(self.temp_label)
        layout.addRow("Default Temperature:", hl)

        # Short chapter word limit
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(10, 1000)
        self.limit_spin.setValue(self.settings["short_chapter_word_limit"])
        layout.addRow("Short‐chapter word limit:", self.limit_spin)

        # Skip estimation default
        self.skip_chk = QCheckBox("Skip cost estimation by default")
        self.skip_chk.setChecked(self.settings["skip_estimation"])
        layout.addRow(self.skip_chk)

        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        # Initialize model list for current provider
        self._on_provider_change(self.settings["provider"])

    def _on_provider_change(self, prov):
        self.model_cb.clear()
        avail = get_available_models(prov)
        if avail:
            self.model_cb.addItems(avail)
            # pick either saved model or default
            m = self.settings.get("model")
            if m in avail:
                self.model_cb.setCurrentText(m)
            else:
                self.model_cb.setCurrentText(get_default_model(prov) or avail[0])

    def _on_temp_change(self, val):
        t = val / 100.0
        self.temp_label.setText(f"{t:.2f}")

    def accept(self):
        # gather back into settings dict
        self.settings["provider"] = self.provider_cb.currentText()
        self.settings["model"]    = self.model_cb.currentText().strip()
        self.settings["temperature"] = self.temp_slider.value() / 100.0
        self.settings["short_chapter_word_limit"] = self.limit_spin.value()
        self.settings["skip_estimation"] = self.skip_chk.isChecked()
        super().accept()

# ------------------------------------------------------------------
# Worker Thread (updated to accept word_limit)
class WorkerThread(QThread):
    parsing_complete    = pyqtSignal(list)
    estimation_complete = pyqtSignal(dict, float)
    abridgment_complete = pyqtSignal(str)
    progress_update     = pyqtSignal(int, str)
    error_occurred      = pyqtSignal(str)

    def __init__(
        self,
        input_path: str,
        output_path: str,
        provider: str,
        model: str,
        temperature: float,
        skip_estimation: bool,
        short_chapter_word_limit: int
    ):
        super().__init__()
        self.input_path  = input_path
        self.output_path = output_path
        self.provider    = provider
        self.model       = model
        self.temperature = temperature
        self.skip_estimation = skip_estimation
        self.short_chapter_word_limit = short_chapter_word_limit

        self.mutex = QMutex()
        self.wait  = QWaitCondition()
        self._continue = False

    def run(self):
        try:
            # 1) Parse
            self.progress_update.emit(0, "Parsing EPUB...")
            chapters, metadata = parse_epub(self.input_path)
            if not chapters:
                raise ValueError("No chapters parsed.")
            info = [{"title": d.metadata['chapter_title'], "tokens": d.metadata.get('token_count')}
                    for d in chapters]
            self.parsing_complete.emit(info)

            # 2) Cost estimation
            if not self.skip_estimation:
                self.progress_update.emit(5, "Estimating cost...")
                est_model = self.model or get_default_model(self.provider)
                tokens, cost = estimate_abridgment_cost(chapters, est_model)
                self.estimation_complete.emit(tokens, cost)
                self.mutex.lock()
                self.wait.wait(self.mutex)
                if not self._continue:
                    raise InterruptedError("Cancelled after estimation.")
                self.mutex.unlock()
            else:
                self.progress_update.emit(5, "Skipping estimation...")

            # 3) Summarization
            self.progress_update.emit(25, "Summarizing chapters...")
            engine = SummarizationEngine(
                llm_provider=self.provider,
                llm_model_name=self.model,
                temperature=self.temperature,
                chapter_word_limit=self.short_chapter_word_limit
            )
            summaries = engine.abridge_documents(chapters)
            for idx, _ in enumerate(summaries, start=1):
                pct = 25 + int((idx/len(summaries))*60)
                self.progress_update.emit(pct, f"Chapter {idx}/{len(summaries)} done")
            self.progress_update.emit(85, "Chapters summarized.")

            # 4) Overall summary
            self.progress_update.emit(85, "Overall summary...")
            overall = engine.summarize_book_overall(summaries)
            self.progress_update.emit(95, "Overall summary done.")

            # 5) Build EPUB
            self.progress_update.emit(95, "Building EPUB...")
            orig = ebooklib.epub.read_epub(self.input_path)
            success = build_epub(
                chapter_summaries=summaries,
                overall_summary=overall,
                parsed_docs=chapters,
                original_book=orig,
                epub_metadata=metadata,
                output_path=self.output_path
            )
            if not success:
                raise ValueError("EPUB build failed.")

            self.progress_update.emit(100, "Complete!")
            self.abridgment_complete.emit(self.output_path)

        except Exception as e:
            logging.error(f"WorkerThread error: {e}", exc_info=True)
            self.error_occurred.emit(str(e))

    def resume_after_estimation(self, proceed: bool):
        self.mutex.lock()
        self._continue = proceed
        self.wait.wakeAll()
        self.mutex.unlock()

# ------------------------------------------------------------------
# Main Window
class AbridgerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Ebook Abridger")
        self.resize(600, 600)

        # load or initialize settings
        self.settings = load_user_settings()

        self.input_file  = None
        self.output_file = None
        self.worker      = None

        self._init_ui()
        self._apply_settings_to_ui()

    def _init_ui(self):
        # Menu
        menubar = QMenuBar(self)
        settings_act = QAction("Settings", self)
        settings_act.triggered.connect(self.open_settings_dialog)
        menubar.addAction(settings_act)
        self.setMenuBar(menubar)

        central = QWidget()
        self.setCentralWidget(central)
        ml = QVBoxLayout(central)

        # I/O group
        fg = QGroupBox("Input / Output")
        fl = QVBoxLayout(fg)
        self.input_btn = QPushButton("Select Input EPUB")
        self.input_btn.clicked.connect(self.select_input_file)
        self.input_label = QLabel("No input selected.")
        self.output_btn = QPushButton("Select Output EPUB")
        self.output_btn.clicked.connect(self.select_output_file)
        self.output_label = QLabel("No output selected.")
        for w in (self.input_btn, self.input_label, self.output_btn, self.output_label):
            fl.addWidget(w)
        ml.addWidget(fg)

        # LLM config
        lg = QGroupBox("LLM Configuration")
        ll = QHBoxLayout(lg)
        self.provider_cb = QComboBox()
        self.provider_cb.addItems(["google","ollama","openrouter"])
        self.provider_cb.currentTextChanged.connect(self._on_provider_change_main)
        self.model_cb = QComboBox()
        self.model_cb.setEditable(True)
        ll.addWidget(QLabel("Provider:")); ll.addWidget(self.provider_cb)
        ll.addWidget(QLabel("Model:"));    ll.addWidget(self.model_cb)
        ml.addWidget(lg)

        # Temperature
        tg = QGroupBox("Temperature")
        tl = QHBoxLayout(tg)
        self.temp_slider = QSlider(Qt.Orientation.Horizontal)
        self.temp_slider.setRange(0,100)
        self.temp_slider.valueChanged.connect(self._update_temp_label)
        self.temp_label  = QLabel("0.30")
        tl.addWidget(self.temp_slider); tl.addWidget(self.temp_label)
        ml.addWidget(tg)

        # Skip estimation
        self.skip_chk = QCheckBox("Skip cost estimation")
        ml.addWidget(self.skip_chk)

        # Chapter list
        cg = QGroupBox("Chapters")
        cl = QVBoxLayout(cg)
        self.chapter_list = QListWidget()
        cl.addWidget(self.chapter_list)
        ml.addWidget(cg)

        # Estimation display
        eg = QGroupBox("Estimation")
        el = QVBoxLayout(eg)
        
        self.est_text = QTextEdit()
        self.est_text.setReadOnly(True)
        self.est_text.setFixedHeight(80)
        el.addWidget(self.est_text)
        ml.addWidget(eg)

        # Buttons
        hl = QHBoxLayout()
        self.start_btn  = QPushButton("Estimate & Abridge")
        self.start_btn.clicked.connect(self.start_processing)
        self.start_btn.setEnabled(False)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_processing)
        self.cancel_btn.setEnabled(False)
        hl.addWidget(self.start_btn); hl.addWidget(self.cancel_btn)
        ml.addLayout(hl)

        # Progress
        pl = QHBoxLayout()
        self.progress = QProgressBar()
        self.status_lbl = QLabel("Idle"); self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        pl.addWidget(self.progress); pl.addWidget(self.status_lbl)
        ml.addLayout(pl)

    def _apply_settings_to_ui(self):
        s = self.settings
        # LLM
        self.provider_cb.setCurrentText(s["provider"])
        self._on_provider_change_main(s["provider"])
        self.model_cb.setCurrentText(s["model"])
        # Temp
        self.temp_slider.setValue(int(s["temperature"]*100))
        self._update_temp_label(s["temperature"]*100)
        # Skip
        self.skip_chk.setChecked(s["skip_estimation"])

    def _on_provider_change_main(self, prov):
        self.model_cb.clear()
        avail = get_available_models(prov)
        if avail:
            self.model_cb.addItems(avail)
            # leave selection if matches
            cur = self.settings.get("model")
            if cur in avail:
                self.model_cb.setCurrentText(cur)
            else:
                self.model_cb.setCurrentText(get_default_model(prov) or avail[0])
        else:
            logging.warning(f"No models for provider '{prov}'")

    def _update_temp_label(self, val):
        t = (val/100) if isinstance(val, (int,float)) else (self.temp_slider.value()/100)
        self.temp_label.setText(f"{t:.2f}")

    def open_settings_dialog(self):
        dlg = SettingsDialog(self, self.settings)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # update in-memory settings
            self.settings.update(dlg.settings)
            save_user_settings(self.settings)
            # re-apply to UI
            self._apply_settings_to_ui()

    def select_input_file(self):
        fp, _ = QFileDialog.getOpenFileName(self, "Select Input EPUB", "", "EPUB Files (*.epub)")
        if not fp: return
        self.input_file = fp
        self.input_label.setText(f"Input: {os.path.basename(fp)}")
        base, ext = os.path.splitext(fp)
        out = f"{base}-abridged{ext}"
        self.output_file = out
        self.output_label.setText(f"Output: {os.path.basename(out)}")
        self.start_btn.setEnabled(True)

    def select_output_file(self):
        fp, _ = QFileDialog.getSaveFileName(self, "Select Output EPUB", self.output_file or "", "EPUB Files (*.epub)")
        if not fp: return
        if not fp.lower().endswith(".epub"):
            fp += ".epub"
        self.output_file = fp
        self.output_label.setText(f"Output: {os.path.basename(fp)}")

    def start_processing(self):
        if not (self.input_file and self.output_file):
            QMessageBox.warning(self, "Missing Files", "Select both input and output EPUB.")
            return

        # gather current settings
        prov  = self.provider_cb.currentText()
        model= self.model_cb.currentText().strip() or None
        temp = self.temp_slider.value()/100.0
        skip = self.skip_chk.isChecked()
        limit = self.settings["short_chapter_word_limit"]

        # disable UI
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setValue(0)
        self.status_lbl.setText("Starting...")

        # launch worker
        self.worker = WorkerThread(
            self.input_file, self.output_file,
            prov, model, temp, skip, limit
        )
        self.worker.parsing_complete.connect(self._on_parsed)
        self.worker.estimation_complete.connect(self._on_estimation)
        self.worker.progress_update.connect(self._on_progress)
        self.worker.abridgment_complete.connect(self._on_success)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

    def _on_parsed(self, info_list):
        self.chapter_list.clear()
        for info in info_list:
            self.chapter_list.addItem(QListWidgetItem(f"{info['title']} (Tokens: {info['tokens']})"))

    def _on_estimation(self, tokens, cost):
        if not self.skip_chk.isChecked():
            msg = "\n".join(f"{k}: {v}" for k,v in tokens.items()) + f"\nCost: ${cost:.4f}"
            resp = QMessageBox.question(self, "Confirm", msg,
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            cont = (resp == QMessageBox.StandardButton.Yes)
            self.worker.resume_after_estimation(cont)
            if not cont:
                self.cancel_processing()
        else:
            self.worker.resume_after_estimation(True)

    def _on_progress(self, val, text):
        self.progress.setValue(val)
        self.status_lbl.setText(text)

    def _on_success(self, path):
        self.status_lbl.setText("Complete!")
        self.progress.setValue(100)
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        QMessageBox.information(self, "Done", f"Abridged book saved to:\n{path}")

    def _on_error(self, err):
        self.status_lbl.setText("Error")
        self.progress.setValue(0)
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        QMessageBox.critical(self, "Error", err)

    def cancel_processing(self):
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.setValue(0)
        self.status_lbl.setText("Cancelled")

    def closeEvent(self, event):
        self.cancel_processing()
        super().closeEvent(event)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    win = AbridgerWindow()
    win.show()
    sys.exit(app.exec())
