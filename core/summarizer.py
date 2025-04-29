# summarizer.py

import logging
import time
import uuid
from typing import List, Optional

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage

from core.llm_config import get_llm_instance
from core.prompts import (
    get_map_prompt,
    OVERALL_SUMMARY_PROMPT,
    FALLBACK_PROMPT,
    LENGTH_MAP,
    DEFAULT_LENGTH
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SummarizationEngine:
    """
    Handles chapter-by-chapter summaries and an overall book summary using a user-specified LLM.
    Implements:
      1. Retry-on-empty with prompt salting & temperature jitter,
      2. Simple‐prompt fallback on persistent empties via FALLBACK_PROMPT.
    """
    def __init__(
        self,
        llm_provider: str,
        llm_model_name: Optional[str] = None,
        temperature: float = 0.3,
        short_chapter_word_limit: int = 150,
        summary_length_key: Optional[str] = "short"
    ):
        self.llm_provider = llm_provider
        self.llm_model_name = llm_model_name
        self.temperature = temperature
        self.short_chapter_word_limit = short_chapter_word_limit
        self.summary_length_key = summary_length_key

        self.skipped_chapters: List[tuple[int, str, int]] = []
        self.error_chapters: List[tuple[int, str, Exception]] = []

        self.llm = None
        self._initialize_llm()

    def _initialize_llm(self):
        logging.info(
            f"Initializing LLM: Provider={self.llm_provider}, Model={self.llm_model_name or 'default'}"
        )
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
        Summarize one chapter, retrying once if the output is empty:
          - Adds a random salt to bust any prompt cache
          - Increases temperature slightly on retry
          - Falls back to a simpler prompt if still empty
        """
        if not self.llm:
            logging.error("LLM not initialized. Cannot summarize chapter.")
            return ""

        num    = chapter_doc.metadata.get('chapter_number', '?')
        title  = chapter_doc.metadata.get('chapter_title', 'Unknown')
        genre  = chapter_doc.metadata.get('genre', 'Fiction')
        text   = chapter_doc.page_content

        # 1) Skip very short chapters
        word_count = len(text.split())
        if word_count < self.short_chapter_word_limit:
            logging.info(f"Chapter {num} is short ({word_count} words); skipping summarization.")
            self.skipped_chapters.append((num, title, word_count))
            return text.strip()


        # 2) Compute length params (strip trailing '%' if present)
        length_key = self.summary_length_key or DEFAULT_LENGTH
        raw_pct = LENGTH_MAP.get(length_key, LENGTH_MAP[DEFAULT_LENGTH])
        # raw_pct might be "50%" or "50" or even an int 50
        if isinstance(raw_pct, str) and raw_pct.endswith('%'):
            length_pct = int(raw_pct.rstrip('%'))
        else:
            length_pct = int(raw_pct)
        # target word count
        #length_words = max(50, word_count * length_pct // 100)
        upper_word_limit = max(50, word_count * length_pct // 100)
        lower_pct   = max(length_pct - 10, 10)
        lower_word_limit = max(25, word_count * lower_pct // 100)


        # Log dynamic parameters
        logging.info(
            f"Chapter {num} params | genre={genre}, length_key={length_key}, "
            f"length_pct={length_pct}%, range={lower_word_limit}–{upper_word_limit} words"
        )

        # 3) Build the prompt once
        tmpl   = get_map_prompt(length_key)
        prompt = tmpl.format(
            text=text,
            genre=genre,
            length=length_key,
            length_percent=length_pct,
            length_words=upper_word_limit,
            min_length_words=lower_word_limit
        )
        logging.debug(f"[summarizer][debug] Chapter {num} prompt:\n{prompt}\n---")

        def call_llm(salt: str = "", temp_override: Optional[float] = None) -> str:
            # Append salt if retrying
            payload = prompt + (f"\n\n<!-- retry-id:{salt} -->" if salt else "")

            # Optionally bump temperature
            if temp_override is not None:
                orig = self.llm.temperature
                self.llm.temperature = temp_override

            try:
                resp = self.llm.invoke([HumanMessage(content=payload)])
                if hasattr(resp, 'generations'):
                    out = resp.generations[0][0].text.strip()
                elif hasattr(resp, 'content'):
                    out = resp.content.strip()
                else:
                    out = str(resp).strip()
            except Exception as e:
                logging.warning(f"[summarizer] API error: {e}")
                out = ""

            # Restore temperature
            if temp_override is not None:
                self.llm.temperature = orig

            return out

        # 4) First call
        summary = call_llm()

        # 5) Retry if empty
        if not summary:
            logging.warning(f"[summarizer] Chapter {num} summary was empty. Retrying in 5s...")
            time.sleep(5)

            retry_salt    = uuid.uuid4().hex
            jittered_temp = min(1.0, self.temperature + 0.2)

            # Log retry parameters
            logging.info(
                f"Chapter {num} retry | salt={retry_salt}, jittered_temp={jittered_temp}"
            )

            summary       = call_llm(salt=retry_salt, temp_override=jittered_temp)

            if not summary:
                logging.error(f"[summarizer] Chapter {num} still empty after retry (salt={retry_salt}).")
                # Fallback to simple one-paragraph prompt
                logging.info(f"[summarizer] Chapter {num} falling back to simple prompt.")
                try:
                    fb_prompt = FALLBACK_PROMPT.format(text=text)
                    resp2     = self.llm.invoke([HumanMessage(content=fb_prompt)])
                    summary   = getattr(resp2, 'content', '').strip() or ""
                    if not summary:
                        raise ValueError("Fallback returned empty")
                    logging.info(f"[summarizer] Chapter {num} fallback summary generated.")
                except Exception as e:
                    logging.error(f"[summarizer] Chapter {num} fallback also failed: {e}")
                    self.error_chapters.append((num, title, e))
                    return ""

        logging.info(f"[summarizer] Chapter {num} summary generated (first100 chars): {summary[:100]}...")
        return summary

    def abridge_documents(self, chapter_docs: List[Document]) -> List[str]:
        if not self.llm:
            logging.error("LLM not initialized. Cannot abridge.")
            return []
        if not chapter_docs:
            logging.warning("No documents provided to abridge.")
            return []

        logging.info(f"Starting abridgment for {len(chapter_docs)} chapters...")
        summaries = []
        for idx, doc in enumerate(chapter_docs, start=1):
            num   = doc.metadata.get('chapter_number', idx)
            title = doc.metadata.get('chapter_title', f'Chapter {num}')
            logging.info(f"[summarizer] Summarizing Chapter {num}/{len(chapter_docs)}: '{title}'")
            summaries.append(self.summarize_single_chapter(doc))

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
        if not self.llm:
            logging.error("LLM not initialized. Cannot generate overall summary.")
            return ""
        valid = [s for s in chapter_summaries if s and not s.startswith("[Error summarizing chapter")]
        if not valid:
            logging.error("No valid chapter summaries to generate overall summary.")
            return ""
        logging.info("Generating overall book summary...")
        combined = "\n\n---\n\n".join(f"{i+1}. {s}" for i, s in enumerate(valid))
        try:
            resp = self.llm.invoke([HumanMessage(content=OVERALL_SUMMARY_PROMPT.format(text=combined))])
            if hasattr(resp, 'generations'):
                overall = resp.generations[0][0].text.strip()
            elif hasattr(resp, 'content'):
                overall = resp.content.strip()
            else:
                overall = str(resp).strip()
            logging.info(f"Overall summary generated (first100 chars): {overall[:100]}...")
            return overall
        except Exception as e:
            logging.error(f"Error generating overall summary: {e}", exc_info=True)
            return ""
