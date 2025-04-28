import os
import uuid
import logging
from typing import Dict, List, Any

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup  # kept in case you need to preserve extra structure
from langchain_core.documents import Document  # your parsed-doc type

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def build_epub(
    chapter_summaries: List[str],
    overall_summary: str,
    parsed_docs: List[Document],        # must include metadata 'epub_item_id', 'chapter_title', 'chapter_number'
    original_book: epub.EpubBook,       # used only for items/spine
    epub_metadata: Dict[str, Any],      # new: includes 'identifier','title','language','authors'
    output_path: str,
    abridged_title_prefix: str = "Abridged: "
) -> bool:
    """
    Builds a new EPUB by replacing original chapter content with summaries,
    preserving structure, and appending an overall summary chapter, using
    metadata that was pre-extracted by your EPUB parser.

    Args:
        chapter_summaries: List of HTML/text summaries for each chapter.
        overall_summary: Text of the overall book summary.
        parsed_docs:      List of Document with metadata:
                          - 'epub_item_id' (matches original_book item.id)
                          - 'chapter_title'
                          - 'chapter_number'
        original_book:    ebooklib.epub.EpubBook to read items, spine, etc.
        epub_metadata:    Dict with at least:
                          - 'identifier': str
                          - 'title':      str
                          - 'language':   str
                          - 'authors':    List[str] or List[Dict[str,Any]]
        output_path:      Where to write the new .epub file.
        abridged_title_prefix: Prefix to prepend to the book title.

    Returns:
        True on success, False on failure.
    """
    # 1) Validate basic inputs
    if not output_path:
        logging.error("Cannot build EPUB: output_path is missing.")
        return False
    if not original_book:
        logging.error("Cannot build EPUB: original_book is missing.")
        return False

    # 2) New book container
    new_book = epub.EpubBook()

    # 3) Copy top-level metadata from parser output
    # ------------------------------------------------
    # Identifier
    base_id = epub_metadata.get("identifier") or f"urn:uuid:{uuid.uuid4()}"
    new_book.set_identifier(f"{base_id}-abridged")

    # Title
    orig_title = epub_metadata.get("title", "Untitled")
    new_book.set_title(f"{abridged_title_prefix}{orig_title}")

    # Language
    lang = epub_metadata.get("language", "en")
    new_book.set_language(lang)

    # Authors (could be plain strings or dicts with file-as, role, id, etc.)
    for author in epub_metadata.get("authors", []):
        if isinstance(author, dict):
            name = author.get("name")
            kwargs = {k: v for k, v in author.items() if k != "name"}
            new_book.add_author(name, **kwargs)
        else:
            new_book.add_author(author)

    logging.info(
        f"Metadata set from parser: title='{new_book.title}', "
        f"language='{lang}', authors={epub_metadata.get('authors')}"
    )

    # 4) Build mapping of item-IDs → summaries/titles/numbers
    # --------------------------------------------------------
    if len(chapter_summaries) != len(parsed_docs):
        logging.error(
            f"Mismatch: {len(chapter_summaries)} summaries vs {len(parsed_docs)} parsed_docs."
        )
        return False

    summary_map: Dict[str, str] = {}
    title_map:   Dict[str, str] = {}
    number_map:  Dict[str, int] = {}

    for doc, summary in zip(parsed_docs, chapter_summaries):
        item_id = doc.metadata.get("epub_item_id")
        if not item_id:
            logging.warning(f"Skipping doc without epub_item_id: {doc.metadata.get('chapter_title')}")
            continue
        summary_map[item_id] = summary
        title_map[item_id]   = doc.metadata.get("chapter_title", "").strip()
        number_map[item_id]  = doc.metadata.get("chapter_number", 0)

    if not summary_map:
        logging.error("No chapter summaries mapped; aborting.")
        return False

    # 5) Copy or replace each item from original_book
    # ------------------------------------------------
    original_items = {item.id: item for item in original_book.get_items()}
    new_items: Dict[str, epub.EpubItem] = {}

    for item_id, item in original_items.items():
        # Only replace XHTML/html chapters
        if item_id in summary_map and isinstance(item, epub.EpubHtml):
            summary = summary_map[item_id]
            html_body = summary.replace("\n", "<br/>\n")

            # Build chapter title
            chap_num = number_map.get(item_id)
            orig_title = title_map.get(item_id)
            if orig_title:
                title = f"{orig_title}"
            elif chap_num is not None:
                if chap_num < 5:
                    title = f"Preface {chap_num}"
                else:
                    title = f"Appendix {chap_num}"
            else:
                title = item.title or item.get_name().rsplit('.', 1)[0].replace('_', ' ').title()

            new_chap = epub.EpubHtml(
                title=title,
                file_name=item.file_name,
                lang=lang,
                uid=item.id
            )
            new_chap.content = (
                f"<html><head><title>{title}</title></head>"
                f"<body><h1>{title}</h1>{html_body}</body></html>"
            )
            new_book.add_item(new_chap)
            new_items[item_id] = new_chap
            logging.debug(f"Replaced chapter item '{item_id}' => '{title}'")
        else:
            # copy unmodified items (images, CSS, nav, etc.)
            new_book.add_item(item)
            new_items[item_id] = item
            logging.debug(f"Copied item: {getattr(item,'file_name',item_id)}")

    # 6) Append overall summary as a final chapter
    # ----------------------------------------------
    summary_chap = None
    if overall_summary:
        summary_id    = "overall_summary"
        summary_title = "Book Summary"
        html_sum      = overall_summary.replace("\n", "<br/>\n")
        summary_chap  = epub.EpubHtml(
            title=summary_title,
            file_name="chap_overall_summary.xhtml",
            lang=lang,
            uid=summary_id
        )
        summary_chap.content = (
            f"<html><head><title>{summary_title}</title></head>"
            f"<body><h1>{summary_title}</h1>{html_sum}</body></html>"
        )
        new_book.add_item(summary_chap)
        new_items[summary_id] = summary_chap
        logging.info("Added overall summary chapter.")
    else:
        logging.warning("No overall_summary provided; skipping summary chapter.")

    # 7) Rebuild the spine (reading order)
    # -------------------------------------
    new_spine = []
    for spine_entry in original_book.spine:
        item_ref = spine_entry[0] if isinstance(spine_entry, tuple) else spine_entry
        itm      = new_items.get(item_ref)
        if itm:
            new_spine.append(itm)
        elif item_ref == "nav":
            nav = epub.EpubNav()
            new_book.add_item(nav)
            new_spine.append(nav)
        elif item_ref == "ncx":
            ncx = epub.EpubNcx()
            new_book.add_item(ncx)
            new_spine.append(ncx)
        else:
            logging.warning(f"Spine entry '{item_ref}' not found; skipping.")
    if summary_chap:
        new_spine.append(summary_chap)
    new_book.spine = new_spine

    # 8) Rebuild the TOC from the new spine
    # --------------------------------------
    toc_links = []
    for itm in new_book.spine:
        if isinstance(itm, epub.EpubHtml):
            link_id = getattr(itm, "uid", itm.file_name)
            toc_links.append(epub.Link(itm.file_name, itm.title, link_id))
    new_book.toc = tuple(toc_links)

    # Ensure mandatory nav & ncx are present
    if not new_book.get_item_with_href("nav.xhtml"):
        new_book.add_item(epub.EpubNav())
    if not new_book.get_item_with_id("ncx"):
        new_book.add_item(epub.EpubNcx())

    # 9) Write out the new EPUB file
    # -------------------------------
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        epub.write_epub(output_path, new_book, {})
        logging.info(f"Abridged EPUB successfully written to: {output_path}")
        return True
    except Exception as e:
        logging.error(f"Failed to write EPUB to {output_path}: {e}", exc_info=True)
        return False
