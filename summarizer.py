import logging
from typing import List, Optional
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage

from llm_config import get_llm_instance
from prompts import get_map_prompt, OVERALL_SUMMARY_PROMPT

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SummarizationEngine:
    """
    Handles chapter-by-chapter summaries and an overall book summary using a user-specified LLM.
    """
    def __init__(
        self,
        llm_provider: str,
        llm_model_name: Optional[str] = None,
        temperature: float = 0.3,
        chapter_word_limit:  int = 150  # chapters below this limit are not summarized but passed through
    ):
        self.llm_provider = llm_provider
        self.llm_model_name = llm_model_name
        self.temperature = temperature
        self.chapter_word_limit = chapter_word_limit
        self.llm = None
        self.skipped_chapters = []  # <--- Track skipped chapters
        self._initialize_llm()

    def _initialize_llm(self):
        logging.info(f"Initializing LLM: Provider={self.llm_provider}, Model={self.llm_model_name or 'default'}")
        try:
            self.llm = get_llm_instance(
                provider=self.llm_provider,
                model_name=self.llm_model_name,
                temperature=self.temperature
            )
            if not self.llm:
                raise ValueError("LLM initialization returned None.")
        except Exception as e:
            logging.error(f"Error initializing LLM: {e}", exc_info=True)
            self.llm = None
    
    def summarize_single_chapter(self, chapter_doc: Document) -> str:
        """
        Summarize one chapter, or pass through short chapters unchanged.
        """
        if not self.llm:
            logging.error("LLM not initialized. Cannot summarize chapter.")
            return ""
        num = chapter_doc.metadata.get('chapter_number', '?')
        title = chapter_doc.metadata.get('chapter_title', 'Unknown')
        try:
            word_count = len(chapter_doc.page_content.split())
            if word_count < self.chapter_word_limit:
                logging.info(f"Chapter {num} is short ({word_count} words); skipping summarization.")
                self.skipped_chapters.append((num, title, word_count))  # <--- Add to skipped list
                return chapter_doc.page_content.strip()
            prompt_text = get_map_prompt().format(text=chapter_doc.page_content)
            response = self.llm.invoke([HumanMessage(content=prompt_text)])
            if hasattr(response, 'generations'):
                chapter_summary = response.generations[0][0].text.strip()
            elif hasattr(response, 'content'):
                chapter_summary = response.content.strip()
            else:
                chapter_summary = str(response).strip()
            if not chapter_summary:
                logging.warning(f"Chapter {num} summary was empty.")
            else:
                logging.info(f"Chapter {num} summary generated (first100 chars): {chapter_summary[:100]}...")
            return chapter_summary
        except Exception as e:
            logging.error(f"Error summarizing Chapter {num} ('{title}'): {e}", exc_info=True)
            return f"[Error summarizing chapter {num}]"



    def abridge_documents(self, chapter_docs: List[Document]) -> List[str]:
        """
        Produces a list of chapter summaries.
        """
        if not self.llm:
            logging.error("LLM not initialized. Cannot abridge.")
            return []
        if not chapter_docs:
            logging.warning("No documents provided to abridge.")
            return []

        logging.info(f"Starting abridgment for {len(chapter_docs)} chapters...")
        summaries = []
        total = len(chapter_docs)
        for idx, doc in enumerate(chapter_docs, start=1):
            num = doc.metadata.get('chapter_number', idx)
            title = doc.metadata.get('chapter_title', f'Chapter {num}')
            logging.info(f"Summarizing Chapter {num}/{total}: '{title}'")
            summary = self.summarize_single_chapter(doc)
            summaries.append(summary)
        logging.info("Chapter-by-chapter abridgment completed.")
        # Log skipped chapters
        if self.skipped_chapters:
            logging.info(f"Skipped summarizing {len(self.skipped_chapters)} chapters because they were short:")
            for num, title, words in self.skipped_chapters:
                logging.info(f"  - Chapter {num}: '{title}' ({words} words)")

        return summaries

    def summarize_book_overall(self, chapter_summaries: List[str]) -> str:
        """
        Combine chapter summaries into a final book-level summary.
        """
        if not self.llm:
            logging.error("LLM not initialized. Cannot generate overall summary.")
            return ""
        valid = [s for s in chapter_summaries if s and not s.startswith("[Error summarizing chapter")]
        if not valid:
            logging.error("No valid chapter summaries to generate overall summary.")
            return ""

        logging.info("Generating overall book summary...")
        combined = "\n\n---\n\n".join(
            f"{idx+1}. {summary}" for idx, summary in enumerate(valid)
        )
        try:
            prompt = OVERALL_SUMMARY_PROMPT.format(text=combined)
            response = self.llm.invoke([HumanMessage(content=prompt)])
            if hasattr(response, 'generations'):
                overall = response.generations[0][0].text.strip()
            elif hasattr(response, 'content'):
                overall = response.content.strip()
            else:
                overall = str(response).strip()
            if overall:
                logging.info(f"Overall summary generated (first100 chars): {overall[:100]}...")
            return overall
        except Exception as e:
            logging.error(f"Error generating overall summary: {e}", exc_info=True)
            return ""

