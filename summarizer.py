import logging
from typing import List, Dict, Optional
from langchain_core.documents import Document
from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.messages import HumanMessage # For invoking chat models

from llm_config import get_llm_instance # Use absolute import
from prompts import MAP_PROMPT, COMBINE_PROMPT, OVERALL_SUMMARY_PROMPT # Use absolute import

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SummarizationEngine:
    """
    Handles the ebook abridgment process using LangChain summarization chains.
    """
    def __init__(
        self,
        llm_provider: str,
        llm_model_name: Optional[str] = None,
        temperature: float = 0.3,
        chain_type: str = "map_reduce",
        map_prompt=MAP_PROMPT,
        combine_prompt=COMBINE_PROMPT
    ):
        """
        Initializes the SummarizationEngine.

        Args:
            llm_provider: The LLM provider ("google", "ollama").
            llm_model_name: The specific model name. Uses provider default if None.
            temperature: The sampling temperature for the LLM.
            chain_type: The type of summarization chain to use (e.g., "map_reduce", "refine").
            map_prompt: The prompt template for the map step.
            combine_prompt: The prompt template for the combine/refine step.
        """
        self.llm_provider = llm_provider
        self.llm_model_name = llm_model_name
        self.temperature = temperature
        self.chain_type = chain_type
        self.map_prompt = map_prompt
        self.combine_prompt = combine_prompt # Keep for potential future use? Or remove? Let's keep for now.
        self.llm: Optional[BaseLanguageModel] = None
        # self.chain = None # Removed chain

        self._initialize_llm()
        # if self.llm: # Removed chain initialization
        #     self._initialize_chain()

    def _initialize_llm(self):
        """Initializes the LLM instance."""
        logging.info(f"Initializing LLM: Provider={self.llm_provider}, Model={self.llm_model_name or 'default'}")
        try:
            self.llm = get_llm_instance(
                provider=self.llm_provider,
                model_name=self.llm_model_name,
                temperature=self.temperature
            )
            if self.llm is None:
                 raise ValueError(f"Failed to initialize LLM for provider '{self.llm_provider}'. Check config/API keys.")
        except Exception as e:
            logging.error(f"Error initializing LLM: {e}", exc_info=True)
            self.llm = None # Ensure llm is None if init fails

    # Removed _initialize_chain method

    def summarize_single_chapter(self, chapter_doc: Document) -> Optional[str]:
        """Summarizes a single chapter document using the configured LLM and map_prompt."""
        if not self.llm:
            logging.error("LLM not initialized. Cannot summarize chapter.")
            return None

        try:
            # Format the map prompt for the current chapter
            prompt_text = self.map_prompt.format(text=chapter_doc.page_content)
            # Invoke the LLM
            response = self.llm.invoke([HumanMessage(content=prompt_text)])

            if hasattr(response, 'content'):
                chapter_summary = response.content.strip()
            else:
                chapter_summary = str(response).strip()

            if not chapter_summary:
                 logging.warning(f"Chapter {chapter_doc.metadata.get('chapter_number', '?')} summary was empty.")
                 return "" # Return empty string for empty summary
            else:
                 # Log summary generation here as well
                 logging.info(f"  Summary generated for Chapter {chapter_doc.metadata.get('chapter_number', '?')} (first 100 chars): {chapter_summary[:100]}...")
                 return chapter_summary

        except Exception as e:
            chapter_num = chapter_doc.metadata.get('chapter_number', '?')
            chapter_title = chapter_doc.metadata.get('chapter_title', 'Unknown')
            logging.error(f"Error processing Chapter {chapter_num} ('{chapter_title}'): {e}", exc_info=True)
            return f"[Error summarizing chapter {chapter_num}]" # Return error placeholder


    def abridge_documents(self, chapter_docs: List[Document]) -> Optional[List[str]]:
        """
        Summarizes each chapter document individually.

        Args:
            chapter_docs: A list of LangChain Document objects representing the chapters.

        Returns:
            A list of strings, where each string is the summary of the corresponding chapter,
            or None if the LLM initialization failed. Returns an empty list if input is empty.
            Individual list items might contain error messages if a specific chapter failed.
        """
        if not self.llm:
            logging.error("LLM not initialized. Cannot abridge.")
            return None
        if not chapter_docs:
            logging.warning("No documents provided to abridge.")
            return [] # Return empty list for empty input

        logging.info(f"Starting chapter-by-chapter abridgment for {len(chapter_docs)} documents...")
        all_chapter_summaries = []
        total_chapters = len(chapter_docs)

        for i, doc in enumerate(chapter_docs):
            chapter_num = doc.metadata.get('chapter_number', i + 1)
            chapter_title = doc.metadata.get('chapter_title', f'Chapter {chapter_num}')
            logging.info(f"Processing Chapter {chapter_num}/{total_chapters}: '{chapter_title}'...")

            # Call the new method to summarize the chapter
            chapter_summary = self.summarize_single_chapter(doc)
            all_chapter_summaries.append(chapter_summary if chapter_summary is not None else f"[Error summarizing chapter {chapter_num}]")

            # --- TODO: Add progress signal emission here for GUI ---
            # Example: self.progress_signal.emit(int((i + 1) / total_chapters * 100))

        logging.info("Chapter-by-chapter abridgment process completed.")
        return all_chapter_summaries # Return the list of summaries

    def summarize_book_overall(self, chapter_summaries: List[str]) -> Optional[str]:
        """
        Generates an overall summary of the book based on chapter summaries.

        Args:
            chapter_summaries: A list of strings containing the summaries of each chapter.

        Returns:
            A string containing the overall book summary, or None if an error occurs.
        """
        if not self.llm:
            logging.error("LLM not initialized. Cannot generate overall summary.")
            return None
        if not chapter_summaries:
            logging.warning("No chapter summaries provided for overall summary.")
            return ""

        logging.info("Generating overall book summary...")
        # Combine chapter summaries into a single text block for the prompt
        combined_summaries_text = "\n\n---\n\n".join(
            f"Chapter {i+1} Summary:\n{summary}"
            for i, summary in enumerate(chapter_summaries)
            if not summary.startswith("[Error summarizing chapter") # Exclude error placeholders
        )

        if not combined_summaries_text:
             logging.error("No valid chapter summaries available to generate an overall summary.")
             return "[Could not generate overall summary - no valid chapter summaries]"


        try:
            prompt_text = OVERALL_SUMMARY_PROMPT.format(text=combined_summaries_text)
            response = self.llm.invoke([HumanMessage(content=prompt_text)])

            if hasattr(response, 'content'):
                overall_summary = response.content.strip()
            else:
                overall_summary = str(response).strip()

            if not overall_summary:
                 logging.warning("Overall book summary generation resulted in empty text.")
                 return ""
            else:
                 logging.info(f"Overall book summary generated (first 500 chars): {overall_summary[:500]}...")
                 return overall_summary

        except Exception as e:
            logging.error(f"Error generating overall book summary: {e}", exc_info=True)
            return "[Error generating overall book summary]"


# Example usage (for testing purposes)
if __name__ == '__main__':
    print("\n--- Summarization Engine Test ---")

    # Create dummy documents for testing
    dummy_docs = [
        Document(page_content="Chapter 1: The journey begins with our hero leaving home.", metadata={'chapter': 1}),
        Document(page_content="Chapter 2: The hero faces the first challenge in the dark forest and meets a wise old mentor.", metadata={'chapter': 2}),
        Document(page_content="Chapter 3: Guided by the mentor, the hero learns a crucial skill and prepares for the next stage.", metadata={'chapter': 3}),
    ]

    # --- Test with Ollama (Ensure Ollama is running with llama3 model) ---
    print("\nTesting with Ollama (llama3)...")
    try:
        # Assuming Ollama runs locally and has 'llama3' model available
        ollama_engine = SummarizationEngine(llm_provider="ollama", llm_model_name="llama3")
        if ollama_engine.llm: # Check if LLM initialized
            chapter_summaries_ollama = ollama_engine.abridge_documents(dummy_docs)
            if chapter_summaries_ollama is not None:
                print("\n--- Ollama Chapter Summaries ---")
                for i, summary in enumerate(chapter_summaries_ollama):
                     print(f"Chapter {i+1}: {summary[:100]}...")
                print("-----------------------------")

                # Test overall summary
                overall_summary_ollama = ollama_engine.summarize_book_overall(chapter_summaries_ollama)
                if overall_summary_ollama:
                     print("\n--- Ollama Overall Summary ---")
                     print(overall_summary_ollama)
                     print("-----------------------------")
                else:
                     print("  Ollama overall summary generation failed.")

            else:
                print("  Ollama chapter abridgment failed.")
        else:
            print("  Could not initialize Ollama LLM. Is Ollama running?")
    except Exception as e:
        print(f"  Error during Ollama test: {e}")


    # --- Test with Google Gemini (Requires API Key in .env) ---
    # print("\nTesting with Google Gemini (gemini-1.5-flash)...")
    # try:
    #     gemini_engine = SummarizationEngine(llm_provider="google", llm_model_name="gemini-1.5-flash")
    #     if gemini_engine.chain:
    #         abridged_text_gemini = gemini_engine.abridge_documents(dummy_docs)
    #         if abridged_text_gemini:
    #             print("\n--- Gemini Abridged Output ---")
    #             print(abridged_text_gemini)
    #             print("----------------------------")
    #         else:
    #             print("  Gemini abridgment failed.")
    #     else:
    #          print("  Could not initialize Gemini engine/chain. Is GOOGLE_API_KEY set correctly in .env?")
    # except Exception as e:
    #      print(f"  Error during Gemini test: {e}")

    print("\n--- Test Complete ---")
    print("Note: Uncomment the Gemini test section if you have a valid API key in .env")