import ebooklib
from ebooklib import epub
import logging
from typing import Dict, List
import os
import uuid  # For generating new IDs if needed
from bs4 import BeautifulSoup  # To potentially preserve basic structure
from langchain_core.documents import Document  # Import Document type

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def build_epub(
    chapter_summaries: List[str],
    overall_summary: str,
    parsed_docs: List[Document],  # List of parsed docs with metadata including 'epub_item_id'
    original_book: epub.EpubBook,
    output_path: str,
    abridged_title_prefix: str = "Abridged: "
) -> bool:
    """
    Builds a new EPUB file by replacing original chapter content with summaries,
    preserving structure, and appending an overall summary chapter.

    Args:
        chapter_summaries: Summaries matching each parsed_doc, in order.
        overall_summary: Combined book summary text.
        parsed_docs: List of Document objs from epub_parser with metadata['epub_item_id'] and 'chapter_title'.
        original_book: The original ebooklib.epub.EpubBook instance.
        output_path: Path to save the new EPUB.
        abridged_title_prefix: Prefix for the new book's title.

    Returns:
        True on success, False on failure.
    """
    # Validate inputs
    if not output_path:
        logging.error("Cannot build EPUB: Output path is not specified.")
        return False
    if not original_book:
        logging.error("Cannot build EPUB: Original book object is missing.")
        return False

    new_book = epub.EpubBook()

    # --- Copy Metadata ---
    try:
        # Identifier
        orig_id = original_book.get_metadata('DC', 'identifier')
        new_id = (orig_id[0][0] + "-abridged") if orig_id else f"urn:uuid:{uuid.uuid4()}"
        new_book.set_identifier(new_id)
        # Title
        orig_title = original_book.get_metadata('DC', 'title')
        title_val = orig_title[0][0] if orig_title else 'Untitled'
        new_book.set_title(f"{abridged_title_prefix}{title_val}")
        # Language
        orig_lang = original_book.get_metadata('DC', 'language')
        lang = orig_lang[0][0] if orig_lang else 'en'
        new_book.set_language(lang)
        # Authors
        for author_meta in original_book.get_metadata('DC', 'creator'):
            name, attrs = author_meta
            kwargs = {}
            if attrs.get('file-as'): kwargs['file_as'] = attrs['file-as']
            if attrs.get('role'):    kwargs['role'] = attrs['role']
            if attrs.get('id'):      kwargs['uid'] = attrs['id']
            new_book.add_author(name, **kwargs)
        logging.info(f"Set metadata: Title='{new_book.title}', Language='{lang}'")
    except Exception as e:
        logging.warning(f"Metadata copy warning: {e}")

    # --- Build summary and title maps ---
    if len(chapter_summaries) != len(parsed_docs):
        logging.error(
            f"Mismatch: {len(chapter_summaries)} summaries vs {len(parsed_docs)} docs."
        )
        return False

    summary_map: Dict[str, str] = {}
    title_map: Dict[str, str] = {}
    for doc, summary in zip(parsed_docs, chapter_summaries):
        item_id = doc.metadata.get('epub_item_id')
        if item_id:
            summary_map[item_id] = summary
            # Extract original chapter title from metadata
            title_map[item_id] = doc.metadata.get('chapter_title', '').strip() or None
        else:
            logging.warning(
                f"Doc missing epub_item_id: {doc.metadata.get('chapter_title')}"
            )
    if not summary_map:
        logging.error("Summary map is empty; no chapters to replace.")
        return False

    # --- Copy or replace items ---
    original_items = {item.id: item for item in original_book.get_items()}
    new_items: Dict[str, epub.EpubItem] = {}

    for item_id, item in original_items.items():
        if item_id in summary_map and isinstance(item, epub.EpubHtml):
            # Replace chapter content
            summary = summary_map[item_id]
            html = summary.replace('\n', '<br/>\n')
            # Use original parsed title if available
            title = title_map.get(item_id) or item.title or \
                item.get_name().rsplit('.', 1)[0].replace('_', ' ').title()
            new_chap = epub.EpubHtml(
                title=title,
                file_name=item.file_name,
                lang=lang,
                uid=item.id
            )
            new_chap.content = (
                f"<html><head><title>{title}</title></head>"
                f"<body><h1>{title}</h1>{html}</body></html>"
            )
            new_book.add_item(new_chap)
            new_items[item_id] = new_chap
            logging.debug(f"Replaced chapter: {item.file_name} with title '{title}'")
        else:
            # Copy other resources (CSS, images, nav, etc.)
            new_book.add_item(item)
            new_items[item_id] = item
            logging.debug(f"Copied item: {getattr(item, 'file_name', item.id)}")

    # --- Add overall summary chapter ---
    summary_chap = None
    if overall_summary:
        summary_id = 'overall_summary'
        summary_title = 'Book Summary'
        html_sum = overall_summary.replace('\n', '<br/>\n')
        summary_chap = epub.EpubHtml(
            title=summary_title,
            file_name='chap_overall_summary.xhtml',
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
        logging.warning("No overall summary provided.")

    # --- Reconstruct spine ---
    new_spine = []
    for spine_entry in original_book.spine:
        item_id = spine_entry[0] if isinstance(spine_entry, tuple) else spine_entry
        itm = new_items.get(item_id)
        if itm:
            new_spine.append(itm)
        elif item_id == 'nav':
            nav = epub.EpubNav()
            new_book.add_item(nav)
            new_spine.append(nav)
        elif item_id == 'ncx':
            ncx = epub.EpubNcx()
            new_book.add_item(ncx)
            new_spine.append(ncx)
        else:
            logging.warning(f"Spine missing item '{item_id}'. Skipping.")
    if summary_chap:
        new_spine.append(summary_chap)
    new_book.spine = new_spine

    # --- Reconstruct TOC with explicit IDs ---
    toc_links = []
    for itm in new_book.spine:
        if isinstance(itm, epub.EpubHtml):
            link_id = getattr(itm, 'uid', itm.file_name) or itm.file_name
            toc_links.append(epub.Link(itm.file_name, itm.title, link_id))
    new_book.toc = tuple(toc_links)

    # Ensure nav/ncx are present
    if not new_book.get_item_with_href('nav.xhtml'):
        new_book.add_item(epub.EpubNav())
    if not new_book.get_item_with_id('ncx'):
        new_book.add_item(epub.EpubNcx())

    # --- Write EPUB ---
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        epub.write_epub(output_path, new_book, {})
        logging.info(f"Abridged EPUB written to: {output_path}")
        return True
    except Exception as e:
        logging.error(f"Failed to write EPUB to {output_path}: {e}", exc_info=True)
        return False
