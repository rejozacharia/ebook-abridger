import sys
import logging
import os
import ebooklib # Import ebooklib
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QComboBox, QTextEdit, QMessageBox,
    QProgressBar, QGroupBox, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QMutex, QWaitCondition

# Backend function imports
from epub_parser import parse_epub
from cost_estimator import estimate_abridgment_cost
from summarizer import SummarizationEngine
from epub_builder import build_epub
from llm_config import get_available_models, get_default_model # Import new functions

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(module)s] %(message)s')

# --- Worker Thread for Backend Processing ---
# To keep the GUI responsive during long tasks like parsing, estimation, and abridgment
class WorkerThread(QThread):
    # Signals to communicate back to the main GUI thread
    estimation_complete = pyqtSignal(dict, float) # Send token estimates (dict) and cost (float)
    parsing_complete = pyqtSignal(list) # Send list of chapter metadata dicts
    abridgment_complete = pyqtSignal(str) # Send output file path (str) on success
    progress_update = pyqtSignal(int, str) # Send percentage (int) and status message (str)
    error_occurred = pyqtSignal(str) # Send error message (str)

    def __init__(self, input_path, output_path, provider, model):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.provider = provider
        self.model = model
        self._is_running = True
        self.mutex = QMutex()
        self.wait_condition = QWaitCondition()
        self._proceed_after_estimation = False # Flag to control continuation

    def run(self):
        """The main logic executed in the background thread."""
        try:
            # --- Stage 1: Parsing ---
            self.progress_update.emit(10, "Parsing EPUB...")
            # Actual call to parse_epub
            chapters, metadata = parse_epub(self.input_path)
            if not chapters:
                 raise ValueError("Failed to parse chapters from EPUB.")
            # Ensure chapters is a list of Document objects for estimation
            if not isinstance(chapters, list): # Basic type check
                 raise TypeError("Parsing did not return a list of chapters.")
            # Extract metadata for UI display before estimation
            chapter_info_list = [
                {
                    "title": doc.metadata.get('chapter_title', f"Chapter {doc.metadata.get('chapter_number', i+1)}"),
                    "tokens": doc.metadata.get('token_count', 'N/A')
                }
                for i, doc in enumerate(chapters)
            ]
            self.parsing_complete.emit(chapter_info_list)
            self.progress_update.emit(20, f"Parsed {len(chapters)} chapters.")

            # --- Stage 2: Estimation ---
            self.progress_update.emit(30, "Estimating cost and tokens...")
            # Determine model for estimation (use default if needed)
            estimation_model = self.model or self._get_default_model_name()
            # Actual call to estimate_abridgment_cost
            tokens, cost = estimate_abridgment_cost(chapters, estimation_model)
            self.estimation_complete.emit(tokens, cost)

            # --- Wait for Confirmation from GUI ---
            self.mutex.lock()
            logging.debug("Worker thread waiting for confirmation...")
            self.wait_condition.wait(self.mutex) # Pause thread
            logging.debug(f"Worker thread woken up. Proceed flag: {self._proceed_after_estimation}")
            proceed = self._proceed_after_estimation
            self.mutex.unlock()

            if not proceed:
                 raise InterruptedError("Abridgment cancelled by user after estimation.")

            # --- Stage 3: Abridgment (Chapter by Chapter) ---
            self.progress_update.emit(50, "Initializing LLM for abridgment...")
            engine = SummarizationEngine(
                llm_provider=self.provider,
                llm_model_name=self.model, # Pass None if user didn't specify
                # We don't need the chain type here anymore as we loop manually
            )
            if not engine.llm:
                 raise ConnectionError("Failed to initialize LLM.")

            # --- Stage 3a: Summarize Chapters ---
            # Progress: 50% - 80%
            self.progress_update.emit(50, "Summarizing chapters...")
            # Note: engine.abridge_documents now returns List[str] or None
            chapter_summaries = engine.abridge_documents(chapters)
            if chapter_summaries is None:
                 raise ValueError("Chapter summarization process failed (returned None).")
            # Check if all summaries are error placeholders or empty
            if all(s is None or s.startswith("[Error summarizing chapter") or not s for s in chapter_summaries):
                 raise ValueError("All chapter summaries failed or were empty.")
            self.progress_update.emit(80, "Chapter summarization finished.")

            # --- Stage 3b: Summarize Overall Book ---
            # Progress: 80% - 90%
            self.progress_update.emit(80, "Generating overall book summary...")
            overall_summary = engine.summarize_book_overall(chapter_summaries)
            if overall_summary is None or overall_summary.startswith("[Error generating overall"):
                 logging.warning(f"Could not generate overall book summary: {overall_summary}")
                 overall_summary = "" # Continue without summary chapter
            self.progress_update.emit(90, "Overall summary finished.")

            # --- Stage 4: Read Original Book Structure ---
            # Progress: 90% - 95%
            self.progress_update.emit(90, "Reading original EPUB structure...")
            try:
                 original_book = ebooklib.epub.read_epub(self.input_path)
            except Exception as e:
                 # Use specific IOError for file reading issues
                 raise IOError(f"Failed to re-read original EPUB file {self.input_path}: {e}") from e
            self.progress_update.emit(95, "Original structure read.")

            # --- Stage 5: Building Output EPUB ---
            # Progress: 95% - 100%
            self.progress_update.emit(95, "Building output EPUB...")
            success = build_epub(
                chapter_summaries=chapter_summaries,
                overall_summary=overall_summary,
                parsed_docs=chapters, # Pass the parsed documents list
                original_book=original_book,
                output_path=self.output_path
            )
            if not success:
                 raise ValueError("Failed to build output EPUB.")

            self.progress_update.emit(100, "Process complete!")
            self.abridgment_complete.emit(self.output_path)

        except Exception as e:
            logging.error(f"Error in worker thread: {e}", exc_info=True)
            self.error_occurred.emit(str(e))
        finally:
             # Ensure mutex is unlocked if an exception occurs while locked (though unlikely here)
             if self.mutex.tryLock(): # Check if locked without blocking
                 self.mutex.unlock()


    def stop(self):
        """Signals the thread to stop and wakes any waiting condition."""
        logging.debug("Stop requested for worker thread.")
        self.mutex.lock()
        self._is_running = False
        self._proceed_after_estimation = False # Ensure it doesn't proceed if stopped while waiting
        self.wait_condition.wakeAll() # Wake up if waiting
        self.mutex.unlock()

    def resume_after_estimation(self, proceed: bool):
        """Sets the proceed flag and wakes the waiting thread."""
        logging.debug(f"Resuming worker thread with proceed={proceed}")
        self.mutex.lock()
        self._proceed_after_estimation = proceed
        self.wait_condition.wakeAll() # Wake up the thread
        self.mutex.unlock()

    def _get_default_model_name(self):
         def _get_default_model_name(self):
              """Gets the default model name based on the provider using llm_config."""
              # Use the refactored function from llm_config
              default_model = get_default_model(self.provider)
              if not default_model:
                   logging.warning(f"Could not retrieve default model for provider: {self.provider}")
              return default_model

# --- Main Application Window ---
class AbridgerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Ebook Abridger")
        self.setGeometry(100, 100, 600, 500) # x, y, width, height

        self.input_file_path = None
        self.output_file_path = None
        self.worker_thread = None

        self._init_ui()

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- File Selection ---
        file_group = QGroupBox("Input / Output")
        file_layout = QVBoxLayout()
        file_group.setLayout(file_layout)

        self.input_btn = QPushButton("Select Input EPUB")
        self.input_btn.clicked.connect(self.select_input_file)
        self.input_label = QLabel("No input file selected.")
        self.input_label.setWordWrap(True)

        self.output_btn = QPushButton("Select Output EPUB Location")
        self.output_btn.clicked.connect(self.select_output_file)
        self.output_label = QLabel("No output location selected.")
        self.output_label.setWordWrap(True)

        file_layout.addWidget(self.input_btn)
        file_layout.addWidget(self.input_label)
        file_layout.addWidget(self.output_btn)
        file_layout.addWidget(self.output_label)
        main_layout.addWidget(file_group)

        # --- Model Selection ---
        model_group = QGroupBox("LLM Configuration")
        model_layout = QHBoxLayout() # Horizontal layout for provider and model
        model_group.setLayout(model_layout)

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["google", "ollama", "openrouter"]) # Add openrouter
        self.provider_combo.currentTextChanged.connect(self.update_model_defaults) # Update model list/default

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True) # Allow entering custom model names
        self.update_model_defaults(self.provider_combo.currentText()) # Initial population

        model_layout.addWidget(QLabel("Provider:"))
        model_layout.addWidget(self.provider_combo)
        model_layout.addWidget(QLabel("Model (optional):"))
        model_layout.addWidget(self.model_combo)
        main_layout.addWidget(model_group)
        main_layout.addWidget(model_group)

        # --- Chapter Info Display ---
        chapter_group = QGroupBox("Chapter Information")
        chapter_layout = QVBoxLayout()
        chapter_group.setLayout(chapter_layout)
        self.chapter_list_widget = QListWidget()
        # Optional: Set max height or make it expandable
        # self.chapter_list_widget.setMaximumHeight(150)
        chapter_layout.addWidget(self.chapter_list_widget)
        main_layout.addWidget(chapter_group)


        # --- Estimation Display ---
        estimation_group = QGroupBox("Estimation Results")
        estimation_layout = QVBoxLayout()
        estimation_group.setLayout(estimation_layout)
        self.estimation_display = QTextEdit()
        self.estimation_display.setReadOnly(True)
        self.estimation_display.setFixedHeight(80) # Make estimation box smaller
        self.estimation_display.setText("Select files and click 'Estimate & Abridge'.")
        estimation_layout.addWidget(self.estimation_display)
        main_layout.addWidget(estimation_group)
        # --- Controls ---
        control_layout = QHBoxLayout()
        self.start_button = QPushButton("Estimate & Abridge")
        self.start_button.clicked.connect(self.start_processing)
        self.start_button.setEnabled(False) # Disabled until files are selected

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_processing)
        self.cancel_button.setEnabled(False) # Disabled initially

        control_layout.addWidget(self.start_button)
        control_layout.addWidget(self.cancel_button)
        main_layout.addLayout(control_layout)

        # --- Progress Bar & Status ---
        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.status_label = QLabel("Status: Idle")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.status_label)
        main_layout.addLayout(progress_layout)


    def select_input_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Input EPUB", "", "EPUB Files (*.epub)")
        if file_path:
            self.input_file_path = file_path
            self.input_label.setText(f"Input: {os.path.basename(file_path)}")
            self._check_start_conditions()

    def select_output_file(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Select Output EPUB Location", "", "EPUB Files (*.epub)")
        if file_path:
             # Ensure it has the .epub extension
            if not file_path.lower().endswith('.epub'):
                file_path += '.epub'
            self.output_file_path = file_path
            self.output_label.setText(f"Output: {os.path.basename(file_path)}")
            self._check_start_conditions()

    def update_model_defaults(self, provider):
        """Updates the model combo box based on the selected provider using llm_config."""
        self.model_combo.clear() # Clear existing items

        available_models = get_available_models(provider)
        default_model = get_default_model(provider)

        if available_models:
            self.model_combo.addItems(available_models)
            if default_model and default_model in available_models:
                self.model_combo.setCurrentText(default_model)
            elif available_models: # If default not found or not in list, select first available
                 self.model_combo.setCurrentIndex(0)
        else:
             logging.warning(f"No models found for provider '{provider}' in .env configuration.")
             # Optionally add a placeholder item
             # self.model_combo.addItem(f"No models configured for {provider}")

        # Ensure the editable text field is cleared if we set an item programmatically
        # Or keep it empty if no models were found
        if self.model_combo.currentIndex() != -1:
             self.model_combo.setEditText("")
        else:
             self.model_combo.setEditText(f"No models for {provider}")



    def _check_start_conditions(self):
        """Enable start button only if input and output files are selected."""
        if self.input_file_path and self.output_file_path:
            self.start_button.setEnabled(True)
        else:
            self.start_button.setEnabled(False)

    def start_processing(self):
        """Starts the background processing thread."""
        if not self.input_file_path or not self.output_file_path:
            QMessageBox.warning(self, "Missing Files", "Please select both input and output EPUB files.")
            return

        provider = self.provider_combo.currentText()
        model = self.model_combo.currentText().strip() or None # Use None if empty

        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("Status: Starting...")
        self.estimation_display.setText("Processing started...")

        # Create and start the worker thread
        self.worker_thread = WorkerThread(self.input_file_path, self.output_file_path, provider, model)
        
        # Connect signals from the worker thread to GUI slots
        self.worker_thread.parsing_complete.connect(self.handle_parsing_complete) # Connect new signal
        self.worker_thread.estimation_complete.connect(self.handle_estimation_results)
        self.worker_thread.abridgment_complete.connect(self.handle_abridgment_success)
        self.worker_thread.progress_update.connect(self.update_progress)
        self.worker_thread.error_occurred.connect(self.handle_error)
        
        self.worker_thread.start()

    def handle_parsing_complete(self, chapter_info_list):
        """Populates the chapter list widget."""
        self.chapter_list_widget.clear()
        if not chapter_info_list:
            self.chapter_list_widget.addItem("No chapters found or parsed.")
            return

        for info in chapter_info_list:
            title = info.get('title', 'Unknown Chapter')
            tokens = info.get('tokens', 'N/A')
            item_text = f"{title} (Tokens: {tokens})"
            self.chapter_list_widget.addItem(QListWidgetItem(item_text))
        logging.info(f"Displayed info for {len(chapter_info_list)} chapters.")

    def handle_estimation_results(self, tokens, cost):
        """Displays estimation results and asks for confirmation."""
        self.update_progress(40, "Estimation complete. Waiting for confirmation...") # Update progress
        
        token_text = "\n".join([f"  {k.replace('_', ' ').title()}: {v:,}" for k, v in tokens.items()])
        cost_text = f"${cost:.4f}"
        
        confirmation_message = f"--- Estimation Results ---\n" \
                               f"Model: {self.model_combo.currentText() or ('Default ' + self.provider_combo.currentText())}\n" \
                               f"{token_text}\n" \
                               f"Estimated Cost: {cost_text}\n\n" \
                               f"Do you want to proceed with the abridgment?"

        self.estimation_display.setText(confirmation_message.replace("--- Estimation Results ---\n", "")) # Display in text box too

        reply = QMessageBox.question(self, 'Confirm Abridgment', confirmation_message,
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No) # Default to No

        if reply == QMessageBox.StandardButton.Yes:
            self.status_label.setText("Status: User confirmed. Abridging...")
            # Signal the worker thread to proceed
            if self.worker_thread:
                 self.worker_thread.resume_after_estimation(proceed=True)
        else:
            self.status_label.setText("Status: User cancelled.")
            # Signal the worker thread NOT to proceed and then request stop
            if self.worker_thread:
                 self.worker_thread.resume_after_estimation(proceed=False)
            # self.cancel_processing() # Let the thread exit naturally after checking flag


    def handle_abridgment_success(self, output_path):
        """Handles successful completion of the process."""
        self.status_label.setText("Status: Complete!")
        self.progress_bar.setValue(100)
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        QMessageBox.information(self, "Success", f"Abridged EPUB saved successfully to:\n{output_path}")
        self.worker_thread = None # Clear thread reference

    def handle_error(self, error_message):
        """Handles errors reported by the worker thread."""
        self.status_label.setText("Status: Error!")
        self.progress_bar.setValue(0) # Or keep last value? Resetting indicates failure.
        self.start_button.setEnabled(True) # Allow trying again
        self.cancel_button.setEnabled(False)
        QMessageBox.critical(self, "Error", f"An error occurred:\n{error_message}")
        self.worker_thread = None # Clear thread reference

    def update_progress(self, value, message):
        """Updates the progress bar and status label."""
        self.progress_bar.setValue(value)
        self.status_label.setText(f"Status: {message}")

    def cancel_processing(self):
        """Stops the worker thread if it's running."""
        if self.worker_thread and self.worker_thread.isRunning():
            # Note: Stopping threads abruptly can be tricky.
            # This signals the thread's loop/wait condition check.
            logging.info("Attempting to cancel worker thread...")
            self.worker_thread.stop() # Sets flags and wakes condition
            # No need to force quit/terminate usually, let run() finish or exit wait
            # self.worker_thread.wait(500) # Optional short wait
            # if self.worker_thread.isRunning():
            #      logging.warning("Thread did not stop gracefully, terminating.")
            #      self.worker_thread.terminate() # Force terminate (use with caution)
            
            self.status_label.setText("Status: Cancelling...")
            # Reset UI elements after a short delay or when thread confirms stopped
            self.start_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self.progress_bar.setValue(0)
            self.worker_thread = None # Clear reference
            self.status_label.setText("Status: Cancelled.")


    def closeEvent(self, event):
        """Ensure worker thread is stopped when closing the window."""
        self.cancel_processing()
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = AbridgerWindow()
    window.show()
    sys.exit(app.exec())