# Project Plan: AI Ebook Abridger

**Project Goal:** Create a desktop application that takes an EPUB file as input, uses a Large Language Model (LLM) via LangChain to generate an abridged version preserving narrative flow and character (~10% of original length), estimates token usage/cost beforehand, and outputs a new EPUB file.

**Core Requirements:**

1.  **Input/Output:** EPUB format for both input and output.
2.  **Abridgment Style:** Retain chapter structure, key anecdotes, dialogue, and narrative voice. Maintain inter-chapter coherence.
3.  **Target Length:** Approximately 10% of the original page/content length.
4.  **Model Flexibility:** Allow selection between models like Llama 4 or Gemini 2.5 Pro.
5.  **Cost Estimation:** Estimate token usage and potential cost before processing and require user confirmation.
6.  **User Interface:** Simple GUI for file selection, model choice, estimation display, confirmation, and initiating the process.

**Proposed Architecture (Conceptual):**

```mermaid
graph TD
    A[Input EPUB File] --> B(EPUB Parser);
    B -- Extracted Chapters & Metadata --> C(LangChain Summarization Chain);
    D[LLM (Llama 4 / Gemini 2.5)] <--> C;
    C -- Abridged Chapters --> E(EPUB Rebuilder);
    B -- Metadata --> E;
    E --> F[Output Abridged EPUB];

    G[User Interface (GUI)] --> H{User Actions};
    H -- Select File --> B;
    H -- Select Model --> C;
    H -- Estimate Cost --> I(Cost/Token Estimator);
    B -- Chapter Docs --> I;
    I -- Estimates --> G;
    H -- Confirm & Start Processing --> C;
    C -- Progress Updates --> G;
    E -- Save File --> H;

    subgraph Core Logic
        direction LR
        B[EPUB Parser (ebooklib, BeautifulSoup)];
        I[Cost/Token Estimator (tiktoken)];
        C[Summarization Chain (LangChain)];
        E[EPUB Rebuilder (ebooklib)];
    end

    subgraph External Services/Models
        D[LLM API/Local Inference];
    end

    subgraph User Interaction
        A; F; G[GUI (PyQt6)]; H;
    end
```

**Development Plan:**

1.  **Phase 1: Foundation, Parsing & Estimation**
    *   **Task 1.1:** Set up Python project environment (virtual environment, Git repository).
    *   **Task 1.2:** Install core libraries: `ebooklib`, `beautifulsoup4`, `langchain`, `langchain-community`, `langchain-google-genai`, `ollama`, `python-dotenv`, `tiktoken`.
    *   **Task 1.3:** Implement `parse_epub` function to extract chapters into LangChain `Document` objects.
    *   **Task 1.4:** Implement Token Counting utility function using `tiktoken` or similar.
    *   **Task 1.5:** Implement Cost Estimation Logic (sum input tokens, estimate output tokens, estimate combine tokens, calculate cost based on selected LLM pricing).
    *   **Task 1.6:** Implement User Confirmation Step logic (to be triggered by GUI later).

2.  **Phase 2: LangChain Summarization Pipeline**
    *   **Task 2.1:** Configure LangChain LLM wrappers (`ChatGoogleGenerativeAI`, `Ollama`, etc.). Load API keys securely.
    *   **Task 2.2:** Define LangChain `PromptTemplate`s (`map_prompt`, `combine_prompt`/`refine_prompt`).
    *   **Task 2.3:** Implement the core summarization chain using `load_summarize_chain` (`map_reduce` preferred).
    *   **Task 2.4:** Create `SummarizationEngine` class/function to run the chain *after* user confirmation.

3.  **Phase 3: EPUB Rebuilding**
    *   **Task 3.1:** Implement `build_epub` function using `ebooklib`.

4.  **Phase 4: Integration & Workflow**
    *   **Task 4.1:** Create the main script/function (`process_book`) orchestrating: Parse -> Estimate & Confirm -> Summarize -> Rebuild.

5.  **Phase 5: User Interface (GUI)**
    *   **Task 5.1:** Install `PyQt6`.
    *   **Task 5.2:** Design and implement the main window: File selection, LLM choice, Display area for estimation results, "Estimate & Abridge" button, Progress indicator, Save dialog.
    *   **Task 5.3:** Connect UI elements to backend logic, running processing in a background thread (`QThread`).

6.  **Phase 6: Optimization & Refinement**
    *   **Task 6.1:** Implement LangChain caching.
    *   **Task 6.2:** Explore parallel execution for the map step.
    *   **Task 6.3:** Refine prompts and estimation logic based on testing.

7.  **Phase 7: Testing**
    *   **Task 7.1:** Test with diverse EPUBs.
    *   **Task 7.2:** Evaluate output quality and accuracy of cost/token estimates.

**Technology Stack:**

*   **Language:** Python 3.x
*   **Core Libraries:** `ebooklib`, `BeautifulSoup4`, `langchain`, `langchain-community`, `langchain-google-genai`, `ollama`, `python-dotenv`, `tiktoken`
*   **GUI:** `PyQt6`