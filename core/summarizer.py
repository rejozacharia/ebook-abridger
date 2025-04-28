# summarizer.py

import logging
import time
import uuid
from typing import List, Optional

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage

from core.llm_config import get_llm_instance
from core.prompts import get_map_prompt, OVERALL_SUMMARY_PROMPT

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SummarizationEngine:
    """
    Handles chapter-by-chapter summaries and an overall book summary using a user-specified LLM.
    Implements:
      1. SystemMessage framing for consistency,
      2. Retry-on-empty with prompt salting & temperature jitter,
      3. Simple‐prompt fallback on persistent empties.
    """
    def __init__(
        self,
        llm_provider: str,
        llm_model_name: Optional[str] = None,
        temperature: float = 0.3,
        short_chapter_word_limit: int = 150,  # below this, we pass text through
        summary_length_key: Optional[str] = "short"
    ):
        self.llm_provider = llm_provider
        self.llm_model_name = llm_model_name
        self.temperature = temperature
        self.short_chapter_word_limit = short_chapter_word_limit
        self.summary_length_key = summary_length_key

        # Track chapters
        self.skipped_chapters: List[tuple[int, str, int]] = []
        self.error_chapters: List[tuple[int, str, Exception]] = []

        self.llm = None
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
        Summarize one chapter, with:
          - initial call using SystemMessage framing,
          - retry once if empty (salt + temp jitter),
          - simple‐prompt fallback if still empty.
        """
        if not self.llm:
            logging.error("LLM not initialized. Cannot summarize chapter.")
            return ""

        num   = chapter_doc.metadata.get('chapter_number', '?')
        title = chapter_doc.metadata.get('chapter_title', 'Unknown')

        # 1) Skip very short chapters
        word_count = len(chapter_doc.page_content.split())
        if word_count < self.short_chapter_word_limit:
            logging.info(f"Chapter {num} is short ({word_count} words); skipping summarization.")
            self.skipped_chapters.append((num, title, word_count))
            return chapter_doc.page_content.strip()

        # 2) Prepare the prompt template
        prompt_template = get_map_prompt(self.summary_length_key)

        def call_llm(salt: str = "", temp_override: Optional[float] = None) -> str:
            # Build the chapter prompt
            prompt = prompt_template.format(text=chapter_doc.page_content)
            if salt:
                prompt += f"\n\n<!-- retry-id: {salt} -->"

            # Pack into messages with a system role
            messages = [
                SystemMessage(content="You are a concise literary summarization assistant.  "
                                      "Return only the abridged chapter text."),
                HumanMessage(content=prompt)
            ]

            # Bump temperature if requested
            if temp_override is not None:
                orig_temp = self.llm.temperature
                self.llm.temperature = temp_override

            try:
                resp = self.llm.invoke(messages)
                if hasattr(resp, 'generations'):
                    text = resp.generations[0][0].text.strip()
                elif hasattr(resp, 'content'):
                    text = resp.content.strip()
                else:
                    text = str(resp).strip()
            except Exception as e:
                logging.warning(f"[summarizer] API error: {e}")
                text = ""

            # Restore temperature
            if temp_override is not None:
                self.llm.temperature = orig_temp

            return text

        # 3) First LLM call
        summary = call_llm()

        # 4) Retry once if empty
        if not summary:
            logging.warning(f"[summarizer] Chapter {num} summary was empty. Retrying in 5s...")
            time.sleep(5)

            retry_salt   = uuid.uuid4().hex
            jittered_temp = min(1.0, self.temperature + 0.2)
            summary = call_llm(salt=retry_salt, temp_override=jittered_temp)

            if not summary:
                logging.error(f"[summarizer] Chapter {num} still empty after retry (salt={retry_salt}).")
                # 5) Fallback to a simpler prompt
                fallback_prompt = (
                    "Please summarize the following chapter text in one paragraph:\n\n"
                    + chapter_doc.page_content[:2000]
                )
                logging.info(f"[summarizer] Chapter {num} falling back to simple prompt.")
                fallback_messages = [
                    SystemMessage(content="You are a helpful summarization assistant."),
                    HumanMessage(content=fallback_prompt)
                ]
                try:
                    resp2 = self.llm.invoke(fallback_messages)
                    summary = getattr(resp2, 'content', '').strip() or ""
                    if summary:
                        logging.info(f"[summarizer] Chapter {num} fallback summary generated.")
                    else:
                        raise ValueError("Fallback returned empty")
                except Exception as e:
                    logging.error(f"[summarizer] Chapter {num} fallback also failed: {e}")
                    self.error_chapters.append((num, title, e))
                    return ""  # GUI will show 0 words

        # 6) Successful summary
        logging.info(f"[summarizer] Chapter {num} summary generated (first100 chars): {summary[:100]}...")
        return summary

    def abridge_documents(self, chapter_docs: List[Document]) -> List[str]:
        """
        Produce a list of chapter summaries.
        """
        if not self.llm:
            logging.error("LLM not initialized. Cannot abridge.")
            return []

        if not chapter_docs:
            logging.warning("No documents provided to abridge.")
            return []

        logging.info(f"Starting abridgment for {len(chapter_docs)} chapters...")
        summaries = []
        total     = len(chapter_docs)

        for idx, doc in enumerate(chapter_docs, start=1):
            num   = doc.metadata.get('chapter_number', idx)
            title = doc.metadata.get('chapter_title', f'Chapter {num}')
            logging.info(f"[summarizer] Summarizing Chapter {num}/{total}: '{title}'")
            summary = self.summarize_single_chapter(doc)
            summaries.append(summary)

        logging.info("Chapter-by-chapter abridgment completed.")
        if self.skipped_chapters:
            logging.info(f"Skipped {len(self.skipped_chapters)} short chapters:")
            for num, title, wc in self.skipped_chapters:
                logging.info(f"  • Chapter {num}: '{title}' ({wc} words)")
        if self.error_chapters:
            logging.warning(f"{len(self.error_chapters)} chapters failed to summarize:")
            for num, title, err in self.error_chapters:
                logging.warning(f"  • Chapter {num}: '{title}' – {err}")

        return summaries

    def summarize_book_overall(self, chapter_summaries: List[str]) -> str:
        """
        Combine chapter summaries into a final book-level summary.
        """
        if not self.llm:
            logging.error("LLM not initialized. Cannot generate overall summary.")
            return ""

        valid = [
            s for s in chapter_summaries
            if s and not s.startswith("[Error summarizing chapter")
        ]
        if not valid:
            logging.error("No valid chapter summaries to generate overall summary.")
            return ""

        logging.info("Generating overall book summary...")
        combined = "\n\n---\n\n".join(
            f"{idx+1}. {summary}"
            for idx, summary in enumerate(valid)
        )

        try:
            prompt   = OVERALL_SUMMARY_PROMPT.format(text=combined)
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
