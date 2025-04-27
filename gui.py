import sys
import os
import json
import logging

import ebooklib
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTextEdit, QMessageBox,
    QProgressBar, QGroupBox, QListWidget, QListWidgetItem,
    QDialog, QFormLayout, QSpinBox, QDialogButtonBox, QMenuBar,
    QComboBox, QCheckBox
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QMutex, QWaitCondition

import yaml
from config_loader import load_config
from epub_parser import parse_epub
from cost_estimator import estimate_abridgment_cost
from summarizer import SummarizationEngine
from epub_builder import build_epub
from llm_config import get_available_models, get_default_model, DEFAULT_TEMPERATURE, SHORT_CHAPTER_WORD_LIMIT

# ------------------------------------------------------------------
# Load application config for summary lengths
CONFIG = load_config(os.path.join(os.path.dirname(__file__), 'config.yaml'))
CHAPTER_SUMMARY_LENGTHS = list(CONFIG.get('chapter_summary_lengths', {}).keys())
DEFAULT_CHAPTER_SUMMARY_LENGTH = CONFIG.get('default_chapter_summary_length')

# Constants for settings persistence
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'user_settings.json')
# ------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(module)s] %(message)s'
)

def load_user_settings() -> dict:
    defaults = {
        'provider': 'google',
        'model': get_default_model('google'),
        'temperature': DEFAULT_TEMPERATURE,
        'skip_estimation': True,
        'short_chapter_word_limit': SHORT_CHAPTER_WORD_LIMIT,
        'summary_length_key': DEFAULT_CHAPTER_SUMMARY_LENGTH
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                loaded = json.load(f)
            for k, v in defaults.items():
                loaded.setdefault(k, v)
            return loaded
        except Exception:
            logging.warning('Could not read user_settings.json; using defaults.')
    return defaults.copy()

def save_user_settings(settings: dict):
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        logging.info('User settings saved.')
    except Exception as e:
        logging.error(f'Failed to save user settings: {e}')

# ------------------------------------------------------------------
# Settings Dialog
class SettingsDialog(QDialog):
    def __init__(self, parent, current_settings):
        super().__init__(parent)
        self.setWindowTitle('Settings')
        self.settings = current_settings.copy()
        layout = QFormLayout(self)

        # Provider
        self.provider_cb = QComboBox()
        self.provider_cb.addItems(['google', 'ollama', 'openrouter'])
        self.provider_cb.setCurrentText(self.settings['provider'])
        self.provider_cb.currentTextChanged.connect(self._on_provider_change)
        layout.addRow('Default Provider:', self.provider_cb)

        # Model
        self.model_cb = QComboBox()
        self.model_cb.setEditable(True)
        layout.addRow('Default Model:', self.model_cb)
        self._on_provider_change(self.settings['provider'])

        # Temperature
        temp_layout = QHBoxLayout()
        self.temp_spin = QSpinBox()
        self.temp_spin.setRange(0, 100)
        self.temp_spin.setValue(int(self.settings['temperature'] * 100))
        self.temp_label = QLabel(f"{self.settings['temperature']:.2f}")
        self.temp_spin.valueChanged.connect(self._on_temp_change)
        temp_layout.addWidget(self.temp_spin)
        temp_layout.addWidget(self.temp_label)
        layout.addRow('Default Temperature:', temp_layout)

        # Short-chapter word limit
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(10, 1000)
        self.limit_spin.setValue(self.settings['short_chapter_word_limit'])
        layout.addRow('Short-chapter word limit:', self.limit_spin)

        # Chapter summary length
        self.length_cb = QComboBox()
        self.length_cb.addItems(CHAPTER_SUMMARY_LENGTHS)
        self.length_cb.setCurrentText(self.settings['summary_length_key'])
        layout.addRow('Chapter summary length:', self.length_cb)

        # Skip estimation
        self.skip_chk = QCheckBox('Skip cost estimation')
        self.skip_chk.setChecked(self.settings['skip_estimation'])
        layout.addRow(self.skip_chk)

        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _on_provider_change(self, prov):
        self.model_cb.clear()
        avail = get_available_models(prov)
        if avail:
            self.model_cb.addItems(avail)
            cur = self.settings.get('model')
            self.model_cb.setCurrentText(cur if cur in avail else get_default_model(prov) or avail[0])

    def _on_temp_change(self, val):
        t = val / 100.0
        self.temp_label.setText(f"{t:.2f}")

    def accept(self):
        self.settings['provider'] = self.provider_cb.currentText()
        self.settings['model'] = self.model_cb.currentText().strip() or None
        self.settings['temperature'] = self.temp_spin.value() / 100.0
        self.settings['short_chapter_word_limit'] = self.limit_spin.value()
        self.settings['summary_length_key'] = self.length_cb.currentText()
        self.settings['skip_estimation'] = self.skip_chk.isChecked()
        super().accept()

# ------------------------------------------------------------------
# Worker Thread
class WorkerThread(QThread):
    parsing_complete       = pyqtSignal(list)
    estimation_complete    = pyqtSignal(dict, float)
    summarization_details  = pyqtSignal(list)
    abridgment_complete    = pyqtSignal(str)
    progress_update        = pyqtSignal(int, str)
    error_occurred         = pyqtSignal(str)

    def __init__(self, input_path, output_path, settings: dict):
        super().__init__()
        self.input_path  = input_path
        self.output_path = output_path
        self.settings    = settings
        self.mutex = QMutex()
        self.wait  = QWaitCondition()
        self._continue = False

    def run(self):
        try:
            # 1) Parse
            self.progress_update.emit(0, 'Parsing EPUB...')
            chapters, metadata = parse_epub(self.input_path)
            info = [
                {'title': d.metadata['chapter_title'], 'tokens': d.metadata.get('token_count')}
                for d in chapters
            ]
            self.parsing_complete.emit(info)

            # 2) Cost estimation
            if not self.settings['skip_estimation']:
                self.progress_update.emit(5, 'Estimating cost...')
                tokens, cost = estimate_abridgment_cost(chapters, self.settings['model'])
                self.estimation_complete.emit(tokens, cost)
                self.mutex.lock()
                self.wait.wait(self.mutex)
                if not self._continue:
                    raise InterruptedError('Cancelled after estimation.')
                self.mutex.unlock()
            else:
                self.progress_update.emit(5, 'Skipping estimation...')

            # 3) Summarization
            self.progress_update.emit(25, 'Summarizing chapters...')
            engine = SummarizationEngine(
                llm_provider=self.settings['provider'],
                llm_model_name=self.settings['model'],
                temperature=self.settings['temperature'],
                short_chapter_word_limit=self.settings['short_chapter_word_limit'],
                summary_length_key=self.settings['summary_length_key']
            )
            summaries = engine.abridge_documents(chapters)

            # Build per-chapter details
            details = []
            for doc, summary in zip(chapters, summaries):
                title   = doc.metadata['chapter_title']
                orig    = len(doc.page_content.split())
                summ    = len(summary.split())
                skipped = (summary.strip() == doc.page_content.strip())
                error   = summary.startswith('[Error summarizing')
                details.append({
                    'title': title,
                    'orig_wc': orig,
                    'sum_wc': summ,
                    'skipped': skipped,
                    'error': error
                })
            self.summarization_details.emit(details)

            for idx, _ in enumerate(summaries, start=1):
                pct = 25 + int((idx / len(summaries)) * 60)
                self.progress_update.emit(pct, f'Chapter {idx}/{len(summaries)} done')
            self.progress_update.emit(85, 'Chapters summarized.')

            # 4) Build EPUB
            self.progress_update.emit(95, 'Building EPUB...')
            orig_book = ebooklib.epub.read_epub(self.input_path)
            success = build_epub(
                chapter_summaries=summaries,
                overall_summary=engine.summarize_book_overall(summaries),
                parsed_docs=chapters,
                original_book=orig_book,
                epub_metadata=metadata,
                output_path=self.output_path
            )
            if not success:
                raise ValueError('EPUB build failed.')

            self.progress_update.emit(100, 'Complete!')
            self.abridgment_complete.emit(self.output_path)

        except Exception as e:
            logging.error(f'WorkerThread error: {e}', exc_info=True)
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
        self.setWindowTitle('AI Ebook Abridger')
        self.resize(600, 600)

        self.settings = load_user_settings()
        self.input_file = None
        self.output_file = None
        self.worker = None

        self._init_ui()

    def _init_ui(self):
        menubar = QMenuBar(self)
        settings_act = QAction('Settings', self)
        settings_act.triggered.connect(self.open_settings_dialog)
        about_act    = QAction('About', self)
        about_act.triggered.connect(self.show_about_dialog)
        menubar.addAction(settings_act)
        menubar.addAction(about_act)
        self.setMenuBar(menubar)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # I/O
        group_io = QGroupBox('Input / Output')
        v_io = QVBoxLayout(group_io)
        self.input_btn = QPushButton('Select Input EPUB')
        self.input_btn.clicked.connect(self.select_input_file)
        self.input_label = QLabel('No input selected.')
        self.output_btn = QPushButton('Select Output EPUB')
        self.output_btn.clicked.connect(self.select_output_file)
        self.output_label = QLabel('No output selected.')
        for w in (self.input_btn, self.input_label, self.output_btn, self.output_label):
            v_io.addWidget(w)
        layout.addWidget(group_io)

        # Chapters
        group_ch = QGroupBox('Chapters')
        v_ch = QVBoxLayout(group_ch)
        self.chapter_list = QListWidget()
        v_ch.addWidget(self.chapter_list)
        layout.addWidget(group_ch)

        # Summary Stats
        group_stats = QGroupBox('Summary Stats')
        v_stats = QVBoxLayout(group_stats)
        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        self.stats_text.setFixedHeight(150)
        v_stats.addWidget(self.stats_text)
        layout.addWidget(group_stats)

        # Controls
        h_btn = QHBoxLayout()
        self.start_btn = QPushButton('Abridge')
        self.start_btn.clicked.connect(self.start_processing)
        self.cancel_btn = QPushButton('Cancel')
        self.cancel_btn.clicked.connect(self.cancel_processing)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        h_btn.addWidget(self.start_btn)
        h_btn.addWidget(self.cancel_btn)
        layout.addLayout(h_btn)

        # Progress
        h_prog = QHBoxLayout()
        self.progress = QProgressBar()
        self.status_lbl = QLabel('Idle')
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        h_prog.addWidget(self.progress)
        h_prog.addWidget(self.status_lbl)
        layout.addLayout(h_prog)

    def show_about_dialog(self):
        text = (
            "<b>eBook Abridger</b><br>"
            "Version 1.0<br><br>"
            "Contact: rejozacharia@gmail.com<br>"
            "GitHub: <a href=\"https://github.com/rejozacharia/ebook-abridger\">https://github.com/rejozacharia/ebook-abridger</a>"
        )
        QMessageBox.about(self, 'About eBook Abridger', text)

    def open_settings_dialog(self):
        dlg = SettingsDialog(self, self.settings)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.settings.update(dlg.settings)
            save_user_settings(self.settings)

    def select_input_file(self):
        fp, _ = QFileDialog.getOpenFileName(self, 'Select Input EPUB', '', 'EPUB Files (*.epub)')
        if fp:
            self.input_file = fp
            self.input_label.setText(f'Input: {os.path.basename(fp)}')
            base, ext = os.path.splitext(fp)
            self.output_file = f'{base}-abridged{ext}'
            self.output_label.setText(f'Output: {os.path.basename(self.output_file)}')
            self.start_btn.setEnabled(True)

    def select_output_file(self):
        fp, _ = QFileDialog.getSaveFileName(self, 'Select Output EPUB', self.output_file or '', 'EPUB Files (*.epub)')
        if fp:
            if not fp.lower().endswith('.epub'):
                fp += '.epub'
            self.output_file = fp
            self.output_label.setText(f'Output: {os.path.basename(fp)}')

    def start_processing(self):
        if not (self.input_file and self.output_file):
            QMessageBox.warning(self, 'Missing Files', 'Select both input and output EPUB.')
            return
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setValue(0)
        self.status_lbl.setText('Starting...')

        self.worker = WorkerThread(self.input_file, self.output_file, self.settings)
        self.worker.parsing_complete.connect(self._on_parsed)
        self.worker.estimation_complete.connect(self._on_estimation)
        self.worker.summarization_details.connect(self._on_summary_details)
        self.worker.progress_update.connect(self._on_progress)
        self.worker.abridgment_complete.connect(self._on_success)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

    def _on_parsed(self, info_list):
        self.chapter_list.clear()
        for info in info_list:
            self.chapter_list.addItem(QListWidgetItem(f"{info['title']} (Tokens: {info['tokens']})"))

    def _on_estimation(self, tokens, cost):
        msg = '\n'.join(f"{k}: {v}" for k, v in tokens.items()) + f"\nCost: ${cost:.4f}"
        resp = QMessageBox.question(self, 'Confirm Cost', msg,
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        proceed = (resp == QMessageBox.StandardButton.Yes)
        self.worker.resume_after_estimation(proceed)
        if not proceed:
            self.cancel_processing()

    def _on_summary_details(self, details):
        lines = []
        for d in details:
            flag = 'SKIPPED' if d['skipped'] else ('ERROR' if d['error'] else '')
            lines.append(f"{d['title']}: {d['sum_wc']} words (orig {d['orig_wc']}) {flag}")
        self.stats_text.setPlainText("\n".join(lines))

    def _on_progress(self, val, text):
        self.progress.setValue(val)
        self.status_lbl.setText(text)

    def _on_success(self, path):
        self.status_lbl.setText('Complete!')
        self.progress.setValue(100)
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        QMessageBox.information(self, 'Done', f'Abridged saved to:\n{path}')

    def _on_error(self, err):
        self.status_lbl.setText('Error')
        self.progress.setValue(0)
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        QMessageBox.critical(self, 'Error', err)

    def cancel_processing(self):
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.setValue(0)
        self.status_lbl.setText('Cancelled')

    def closeEvent(self, event):
        self.cancel_processing()
        super().closeEvent(event)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    win = AbridgerWindow()
    win.show()
    sys.exit(app.exec())
