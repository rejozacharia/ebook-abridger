# AI Ebook Abridger

A Python application designed to create abridged versions of EPUB ebooks using Large Language Models (LLMs). It aims to summarize ebooks while preserving the original chapter structure, narrative flow, and key elements like anecdotes and dialogue, targeting approximately 10-15% of the original length.

This tool provides both a command-line interface (CLI) and a graphical user interface (GUI) for ease of use.

## Features

*   **EPUB Input/Output:** Reads standard EPUB files and generates a new, abridged EPUB file.
*   **AI-Powered Abridgment:** Leverages LLMs via LangChain to summarize content chapter by chapter.
*   **Context-Aware Summarization:** Uses LangChain's `map_reduce` chain to process chapters individually and then combine them coherently.
*   **Configurable LLMs:** Supports different LLM providers and models:
    *   Google Gemini (e.g., `gemini-1.5-pro`, `gemini-1.5-flash`) via API key.
    *   Ollama (e.g., `llama3`, `mistral`) for running local models.
    *   OpenRouter (e.g., `mistralai/mistral-7b-instruct`, `anthropic/claude-3-haiku`) via API key, providing access to various models.
*   **Cost Estimation:** Provides an estimated token count and cost (for API-based models like Google Gemini) before starting the potentially expensive abridgment process. (Note: OpenRouter cost estimation is currently simplified to $0; actual costs depend on the chosen model via OpenRouter).
*   **User Confirmation:** Prompts the user to confirm before proceeding with abridgment after seeing the cost estimate (can be skipped via CLI flag).
*   **Dual Interface:**
    *   **CLI:** `main.py` for command-line operation.
    *   **GUI:** `gui.py` (using PyQt6) for a graphical experience.
*   **Metadata Preservation:** Attempts to preserve original metadata (title, author, language) in the abridged EPUB, adding an "Abridged: " prefix to the title.

## Installation

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/rejozacharia/ebook-abridger.git
    cd ebook-abridger
    ```

2.  **Create and Activate Virtual Environment:**
    *   **Windows (PowerShell):**
        ```powershell
        python -m venv .venv
        .\.venv\Scripts\Activate.ps1
        ```
    *   **macOS/Linux (Bash):**
        ```bash
        python3 -m venv .venv
        source .venv/bin/activate
        ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Install Ollama (Optional):** If you plan to use local models via Ollama, download and install it from [ollama.com](https://ollama.com/) and ensure it's running. You might also need to pull the specific models you intend to use (e.g., `ollama pull llama3`).

## Configuration

1.  **Create `.env` file:** Copy the structure from the existing files or create a new file named `.env` in the project root (`ebook-abridger/`).

2.  **Add API Key (if using Google Gemini):**
    Open the `.env` file and add your Google API key:
    ```dotenv
    GOOGLE_API_KEY=YOUR_GOOGLE_API_KEY_HERE
    ```
    Replace `YOUR_GOOGLE_API_KEY_HERE` with your actual key obtained from Google AI Studio or Google Cloud.

3.  **Configure Ollama URL (Optional):**
    If Ollama is running on a different address than the default `http://localhost:11434`, specify it in `.env`:
    ```dotenv
    OLLAMA_BASE_URL=http://your_ollama_address:port
    ```

4.  **Add API Key (if using OpenRouter):**
    Open the `.env` file and add your OpenRouter API key:
    ```dotenv
    OPENROUTER_API_KEY=YOUR_OPENROUTER_API_KEY_HERE
    OPENAI_API_BASE=https://openrouter.ai/api/v1     # endpoint for OpenRouter
    ```
    Replace `YOUR_OPENROUTER_API_KEY_HERE` with your actual key obtained from [OpenRouter.ai](https://openrouter.ai/).

5.  **Configure Available Models (Optional):**
    You can customize the list of models available in the GUI dropdown and set the default model for each provider in the `.env` file. Use comma-separated values, and mark the default model with an asterisk (`*`). If not set, reasonable defaults will be used.
    ```dotenv
    # Example Google Models (replace/add as needed)
    GOOGLE_MODELS=gemini-1.5-flash*,gemini-1.5-pro,gemini-1.0-pro

    # Example Ollama Models (replace/add as needed)
    OLLAMA_MODELS=llama3*,mistral,phi3

    # Example OpenRouter Models (Check OpenRouter website for available models)
    # Use the format 'provider/model-name'
    OPENROUTER_MODELS=mistralai/mistral-7b-instruct*,google/gemini-flash-1.5,anthropic/claude-3-haiku
    ```

## Usage

Ensure your virtual environment is activated before running the application.

### Command-Line Interface (CLI)

Use the `main.py` script.

**Syntax:**

```bash
python main.py <input_epub_path> <output_epub_path> -p <provider> [-m <model_name>] [-t <temperature>] [-y]
```

**Arguments:**

*   `input_epub_path`: Path to the input EPUB file.
*   `output_epub_path`: Path where the abridged EPUB file will be saved.
*   `-p`, `--provider`: (Required) The LLM provider. Choices: `google`, `ollama`, `openrouter`.
*   `-m`, `--model`: (Optional) The specific LLM model name (e.g., `gemini-1.5-pro`, `llama3`, `mistralai/mistral-7b-instruct`). If omitted, uses the default model configured for the selected provider in the `.env` file (or a hardcoded fallback if not configured).
*   `-t`, `--temperature`: (Optional) Sampling temperature for the LLM (default: 0.3). Lower values are more deterministic.
*   `-y`, `--yes`: (Optional) Skip the cost estimation confirmation prompt and proceed directly to abridgment.

**Examples:**

*   **Using Ollama (Llama 3):**
    ```bash
    python main.py "MyBook.epub" "MyBook_abridged.epub" -p ollama -m llama3
    ```
*   **Using Google Gemini (Default Flash model):**
    ```bash
    python main.py "AnotherBook.epub" "output/AnotherBook_abridged.epub" -p google
    ```
*   **Using Google Gemini (Pro model, skip confirmation):**
    ```bash
    python main.py "input/LongNovel.epub" "output/LongNovel_abridged.epub" -p google -m gemini-1.5-pro -y
    ```
*   **Using OpenRouter (Default model configured in .env):**
    ```bash
    python main.py "MyBook.epub" "MyBook_abridged_or.epub" -p openrouter
    ```

### Graphical User Interface (GUI)

Run the `gui.py` script.

```bash
python gui.py
```

**Steps:**

1.  Click **"Select Input EPUB"** to choose the ebook you want to abridge.
2.  Click **"Select Output EPUB Location"** to specify where the abridged file should be saved.
3.  Select the **Provider** (`google`, `ollama`, or `openrouter`) from the dropdown.
4.  Select or enter a specific **Model** name. The dropdown is populated based on the models listed in your `.env` file for the selected provider (e.g., `gemini-1.5-flash`, `llama3`, `mistralai/mistral-7b-instruct`). If left blank or if you select from the dropdown, the default model (marked with `*` in `.env` or the first in the list) will be suggested/used. You can also type a different model name directly.
5.  Click **"Estimate & Abridge"**.
6.  The application will parse the EPUB and estimate the token usage and cost. The results will be displayed in the "Estimation Results" box.
7.  A confirmation dialog will appear asking if you want to proceed. Click **"Yes"** to start the abridgment or **"No"** to cancel.
8.  The progress bar and status label will update during the process. Abridgment can take a significant amount of time depending on the book length and LLM speed.
9.  A message box will appear upon success or error.

## Dependencies

See `requirements.txt` for a full list of Python dependencies. Key libraries include:

*   `ebooklib`: For parsing and building EPUB files.
*   `beautifulsoup4`: For parsing HTML content within EPUBs.
*   `langchain`, `langchain-community`, `langchain-google-genai`: For LLM interaction and summarization chains (includes OpenRouter support via `langchain-community`).
*   `ollama`: For interacting with a local Ollama instance.
*   `python-dotenv`: For managing environment variables (API keys).
*   `tiktoken`: For estimating token counts.
*   `PyQt6`: For the graphical user interface.

## Future Improvements (Phase 6 from Plan)

*   Implement LangChain caching to avoid re-processing identical chapters.
*   Explore parallel execution for the map step in the summarization chain.
*   Refine prompts for better quality and adherence to length constraints.
*   Improve cost estimation accuracy, especially for different chain types.
