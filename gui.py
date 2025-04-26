import sys
import logging
import os
import ebooklib
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QComboBox, QTextEdit, QMessageBox,
    QProgressBar, QGroupBox, QListWidget, QListWidgetItem, QSlider, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QMutex, QWaitCondition

# Backend imports
from epub_parser import parse_epub
from cost_estimator import estimate_abridgment_cost
from summarizer import SummarizationEngine
from epub_builder import build_epub
from llm_config import get_available_models, get_default_model

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(module)s] %(message)s')

class WorkerThread(QThread):
    parsing_complete = pyqtSignal(list)
    estimation_complete = pyqtSignal(dict, float)
    abridgment_complete = pyqtSignal(str)
    progress_update = pyqtSignal(int, str)
    error_occurred = pyqtSignal(str)

    def __init__(self, input_path, output_path, provider, model, temperature, skip_estimation):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self.skip_estimation = skip_estimation
        self.mutex = QMutex()
        self.wait = QWaitCondition()
        self._continue = False

    def run(self):
        try:
            # Stage 1: Parse EPUB
            self.progress_update.emit(0, "Parsing EPUB...")
            chapters, metadata = parse_epub(self.input_path)
            if not chapters:
                raise ValueError("No chapters parsed.")
            chapter_info = [
                {"title": doc.metadata['chapter_title'], "tokens": doc.metadata.get('token_count')} 
                for doc in chapters
            ]
            self.parsing_complete.emit(chapter_info)

            # Stage 2: Cost estimation
            if not self.skip_estimation:
                self.progress_update.emit(5, "Estimating cost and tokens...")
                est_model = self.model or get_default_model(self.provider)
                tokens, cost = estimate_abridgment_cost(chapters, est_model)
                self.estimation_complete.emit(tokens, cost)
                # wait for user confirmation
                self.mutex.lock()
                self.wait.wait(self.mutex)
                if not self._continue:
                    raise InterruptedError("Cancelled after estimation.")
                self.mutex.unlock()
            else:
                self.progress_update.emit(5, "Skipping estimation...")

            # Stage 3: Summarization
            self.progress_update.emit(10, "Starting chapter summaries...")
            engine = SummarizationEngine(
                llm_provider=self.provider,
                llm_model_name=self.model,
                temperature=self.temperature
            )
            chapter_summaries = engine.abridge_documents(chapters)
            total = len(chapter_summaries)
            for idx, _ in enumerate(chapter_summaries, start=1):
                pct = 10 + int((idx / total) * 80)
                self.progress_update.emit(pct, f"Chapter {idx}/{total} summarized")
            self.progress_update.emit(90, "Chapters summarized.")

            # Stage 4: Overall summary
            self.progress_update.emit(90, "Generating overall summary...")
            overall = engine.summarize_book_overall(chapter_summaries)
            self.progress_update.emit(95, "Overall summary done.")

            # Stage 5: Build EPUB
            self.progress_update.emit(95, "Building EPUB...")
            original_book = ebooklib.epub.read_epub(self.input_path)
            success = build_epub(
                chapter_summaries=chapter_summaries,
                overall_summary=overall,
                parsed_docs=chapters,
                original_book=original_book,
                output_path=self.output_path
            )
            if not success:
                raise ValueError("Failed to build output EPUB.")

            # Completion
            self.progress_update.emit(100, "Process complete!")
            self.abridgment_complete.emit(self.output_path)

        except Exception as e:
            logging.error(f"Worker error: {e}", exc_info=True)
            self.error_occurred.emit(str(e))

    def resume_after_estimation(self, proceed: bool):
        self.mutex.lock()
        self._continue = proceed
        self.wait.wakeAll()
        self.mutex.unlock()

class AbridgerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Ebook Abridger")
        self.setGeometry(100, 100, 600, 600)
        self.input_file = None
        self.output_file = None
        self.worker = None
        self._init_ui()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Input/Output selection
        file_group = QGroupBox("Input / Output")
        fl = QVBoxLayout(file_group)
        self.input_btn = QPushButton("Select Input EPUB")
        self.input_btn.clicked.connect(self.select_input_file)
        self.input_label = QLabel("No input selected.")
        self.output_btn = QPushButton("Select Output EPUB Location")
        self.output_btn.clicked.connect(self.select_output_file)
        self.output_label = QLabel("No output selected.")
        fl.addWidget(self.input_btn)
        fl.addWidget(self.input_label)
        fl.addWidget(self.output_btn)
        fl.addWidget(self.output_label)
        main_layout.addWidget(file_group)

        # LLM Configuration
        llm_group = QGroupBox("LLM Configuration")
        ll = QHBoxLayout(llm_group)
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["google", "ollama", "openrouter"])
        self.provider_combo.currentTextChanged.connect(self.update_model_defaults)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.update_model_defaults(self.provider_combo.currentText())
        ll.addWidget(QLabel("Provider:")); ll.addWidget(self.provider_combo)
        ll.addWidget(QLabel("Model:")); ll.addWidget(self.model_combo)
        main_layout.addWidget(llm_group)

        # Temperature slider
        temp_group = QGroupBox("Temperature (0.0 - 1.0)")
        tl = QHBoxLayout(temp_group)
        self.temp_slider = QSlider(Qt.Orientation.Horizontal)
        self.temp_slider.setMinimum(0); self.temp_slider.setMaximum(100); self.temp_slider.setValue(30)
        self.temp_slider.valueChanged.connect(self._on_temp_change)
        self.temp_label = QLabel("0.30")
        tl.addWidget(self.temp_slider);
        tl.addWidget(self.temp_label)
        main_layout.addWidget(temp_group)

        # Skip estimation
        self.skip_chk = QCheckBox("Skip cost estimation")
        self.skip_chk.setChecked(True)
        main_layout.addWidget(self.skip_chk)

        # Chapter info
        chap_group = QGroupBox("Chapter Information")
        cl = QVBoxLayout(chap_group)
        self.chapter_list_widget = QListWidget()
        cl.addWidget(self.chapter_list_widget)
        main_layout.addWidget(chap_group)

        # Estimation results
        est_group = QGroupBox("Estimation Results")
        el = QVBoxLayout(est_group)
        self.estimation_display = QTextEdit(); self.estimation_display.setReadOnly(True); self.estimation_display.setFixedHeight(80)
        el.addWidget(self.estimation_display)
        main_layout.addWidget(est_group)

        # Control buttons
        ctrl = QHBoxLayout()
        self.start_btn = QPushButton("Estimate & Abridge")
        self.start_btn.clicked.connect(self.start_processing); self.start_btn.setEnabled(False)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_processing); self.cancel_btn.setEnabled(False)
        ctrl.addWidget(self.start_btn); ctrl.addWidget(self.cancel_btn)
        main_layout.addLayout(ctrl)

        # Progress bar and status
        pl = QHBoxLayout()
        self.progress_bar = QProgressBar(); self.progress_bar.setValue(0)
        self.status_label = QLabel("Status: Idle"); self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        pl.addWidget(self.progress_bar); pl.addWidget(self.status_label)
        main_layout.addLayout(pl)

    def _on_temp_change(self, val):
        t = val / 100.0
        self.temp_label.setText(f"{t:.2f}")

    def select_input_file(self):
        fp, _ = QFileDialog.getOpenFileName(self, "Select Input EPUB", "", "EPUB Files (*.epub)")
        if fp:
            self.input_file = fp
            self.input_label.setText(f"Input: {os.path.basename(fp)}")
            base, ext = os.path.splitext(fp)
            out = f"{base}-abridged{ext}"
            self.output_file = out
            self.output_label.setText(f"Output: {os.path.basename(out)}")
            self.start_btn.setEnabled(True)

    def select_output_file(self):
        fp, _ = QFileDialog.getSaveFileName(self, "Select Output EPUB Location", self.output_file or "", "EPUB Files (*.epub)")
        if fp:
            if not fp.lower().endswith('.epub'):
                fp += '.epub'
            self.output_file = fp
            self.output_label.setText(f"Output: {os.path.basename(fp)}")

    def update_model_defaults(self, provider):
        self.model_combo.clear()
        avail = get_available_models(provider)
        if avail:
            self.model_combo.addItems(avail)
            self.model_combo.setCurrentIndex(0)
        else:
            logging.warning(f"No models for provider '{provider}'")

    def start_processing(self):
        if not self.input_file or not self.output_file:
            QMessageBox.warning(self, "Missing Files", "Please select input and output EPUB files.")
            return
        provider = self.provider_combo.currentText()
        model = self.model_combo.currentText().strip() or None
        temp = self.temp_slider.value() / 100.0
        skip = self.skip_chk.isChecked()

        self.start_btn.setEnabled(False); self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0); self.status_label.setText("Status: Starting...")
        self.estimation_display.setText("Processing started...")

        self.worker = WorkerThread(
            self.input_file, self.output_file,
            provider, model, temp, skip
        )
        self.worker.parsing_complete.connect(self.handle_parsing_complete)
        self.worker.estimation_complete.connect(self.handle_estimation_results)
        self.worker.progress_update.connect(self.update_progress)
        self.worker.abridgment_complete.connect(self.handle_abridgment_success)
        self.worker.error_occurred.connect(self.handle_error)
        self.worker.start()

    def handle_parsing_complete(self, chapter_info_list):
        self.chapter_list_widget.clear()
        for info in chapter_info_list:
            self.chapter_list_widget.addItem(QListWidgetItem(f"{info['title']} (Tokens: {info['tokens']})"))

    def handle_estimation_results(self, tokens, cost):
        if not self.skip_chk.isChecked():
            self.status_label.setText("Status: Waiting for confirmation...")
            msg = "".join([f"{k}: {v}\n" for k,v in tokens.items()]) + f"Cost: ${cost:.4f}"
            resp = QMessageBox.question(self, 'Confirm', msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            proceed = (resp == QMessageBox.StandardButton.Yes)
            self.worker.resume_after_estimation(proceed)
            if not proceed:
                self.cancel_processing()
        else:
            self.worker.resume_after_estimation(True)

    def update_progress(self, val, msg):
        self.progress_bar.setValue(val)
        self.status_label.setText(f"Status: {msg}")

    def handle_abridgment_success(self, path):
        self.status_label.setText("Status: Complete!")
        self.progress_bar.setValue(100)
        self.start_btn.setEnabled(True); self.cancel_btn.setEnabled(False)
        QMessageBox.information(self, "Success", f"Saved to: {path}")

    def handle_error(self, error_msg):
        self.status_label.setText("Status: Error!")
        self.progress_bar.setValue(0)
        self.start_btn.setEnabled(True); self.cancel_btn.setEnabled(False)
        QMessageBox.critical(self, "Error", error_msg)

    def cancel_processing(self):
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
        self.start_btn.setEnabled(True); self.cancel_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.status_label.setText("Status: Cancelled.")

    def closeEvent(self, event):
        self.cancel_processing()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = AbridgerWindow()
    window.show()
    sys.exit(app.exec())
