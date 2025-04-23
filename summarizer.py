import logging
from typing import List, Dict, Optional
from langchain_core.documents import Document
from langchain.chains.summarize import load_summarize_chain
from langchain_core.language_models.base import BaseLanguageModel

from llm_config import get_llm_instance # Use absolute import
from prompts import MAP_PROMPT, COMBINE_PROMPT # Use absolute import

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
        self.combine_prompt = combine_prompt
        self.llm: Optional[BaseLanguageModel] = None
        self.chain = None

        self._initialize_llm()
        if self.llm:
            self._initialize_chain()

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

    def _initialize_chain(self):
        """Initializes the LangChain summarization chain."""
        if not self.llm:
            logging.error("Cannot initialize chain: LLM is not available.")
            return

        logging.info(f"Initializing summarization chain with type: {self.chain_type}")
        try:
            # Note: For 'refine', combine_prompt is used as the refine_prompt.
            # LangChain's load_summarize_chain handles this mapping internally.
            self.chain = load_summarize_chain(
                llm=self.llm,
                chain_type=self.chain_type,
                map_prompt=self.map_prompt,
                combine_prompt=self.combine_prompt,
                verbose=True # Set to True for more detailed logging from LangChain
            )
            logging.info("Summarization chain initialized successfully.")
        except Exception as e:
            logging.error(f"Error initializing {self.chain_type} chain: {e}", exc_info=True)
            self.chain = None

    def abridge_documents(self, chapter_docs: List[Document]) -> Optional[str]:
        """
        Runs the summarization chain on the provided chapter documents.

        Args:
            chapter_docs: A list of LangChain Document objects representing the chapters.

        Returns:
            The final abridged text as a string, or None if an error occurs or
            the engine wasn't initialized properly.
        """
        if not self.chain or not self.llm:
            logging.error("Summarization engine or LLM not initialized. Cannot abridge.")
            return None
        if not chapter_docs:
            logging.warning("No documents provided to abridge.")
            return "" # Return empty string for empty input

        logging.info(f"Starting abridgment process for {len(chapter_docs)} documents using '{self.chain_type}' chain...")
        try:
            # The chain expects a dictionary with 'input_documents' key
            result = self.chain.invoke({"input_documents": chapter_docs})
            
            # The output structure might vary slightly, but usually under 'output_text'
            output_text = result.get("output_text") 
            if output_text is None:
                 logging.error("Chain execution finished, but 'output_text' not found in the result.")
                 # Log the full result for debugging if output_text is missing
                 logging.debug(f"Full chain result: {result}")
                 return None
                 
            logging.info("Abridgment process completed successfully.")
            return output_text.strip()

        except Exception as e:
            logging.error(f"Error during chain execution: {e}", exc_info=True)
            return None

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
        if ollama_engine.chain:
            abridged_text_ollama = ollama_engine.abridge_documents(dummy_docs)
            if abridged_text_ollama:
                print("\n--- Ollama Abridged Output ---")
                print(abridged_text_ollama)
                print("-----------------------------")
            else:
                print("  Ollama abridgment failed.")
        else:
            print("  Could not initialize Ollama engine/chain. Is Ollama running?")
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