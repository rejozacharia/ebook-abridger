import ebooklib
from ebooklib import epub
import logging
from typing import Dict, Optional, List
import os
import sys # For sys.exit() in test block
import uuid # For generating new IDs if needed
from bs4 import BeautifulSoup # To potentially preserve basic structure
from langchain_core.documents import Document # Import Document type

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def build_epub(
    chapter_summaries: List[str],
    overall_summary: str,
    parsed_docs: List[Document], # Add list of parsed docs
    original_book: epub.EpubBook,
    output_path: str,
    abridged_title_prefix: str = "Abridged: "
):
    """
    Builds a new EPUB file by replacing original chapter content with summaries,
    preserving structure, and adding an overall summary chapter.

    Args:
        chapter_summaries: A list of strings, each being the summary for a chapter
                           corresponding to the parsed_docs list.
                           Length must match len(parsed_docs).
        overall_summary: The overall summary text for the book.
        parsed_docs: The list of Document objects returned by epub_parser.
        original_book: The original ebooklib.epub.EpubBook object.
        output_path: The full path where the new EPUB file should be saved.
        abridged_title_prefix: Prefix to add to the original title for the abridged version.
    """
    if not output_path:
        logging.error("Cannot build EPUB: Output path is not specified.")
        return False
    if not original_book:
        logging.error("Cannot build EPUB: Original book object is missing.")
        return False

    new_book = epub.EpubBook()

    # --- Copy Metadata ---
    try:
        # Use get_metadata for identifier, title, language
        orig_identifier = original_book.get_metadata('DC', 'identifier')
        new_id = (orig_identifier[0][0] + "-abridged") if orig_identifier else f"urn:uuid:{uuid.uuid4()}"
        new_book.set_identifier(new_id)

        orig_title = original_book.get_metadata('DC', 'title')
        new_title = f"{abridged_title_prefix}{orig_title[0][0]}" if orig_title else f"{abridged_title_prefix}Untitled"
        new_book.set_title(new_title)

        orig_language = original_book.get_metadata('DC', 'language')
        new_lang = orig_language[0][0] if orig_language else 'en'
        new_book.set_language(new_lang)

        # Author copying seems okay, but ensure language is consistent
        new_book.language = new_lang # Explicitly set language attribute too

        for author_meta in original_book.get_metadata('DC', 'creator'):
            author_name = author_meta[0]
            author_attrs = author_meta[1]
            # Prepare keyword arguments, only including non-None values
            kwargs = {}
            file_as = author_attrs.get('file-as')
            if file_as is not None:
                kwargs['file_as'] = file_as
            role = author_attrs.get('role')
            if role is not None:
                kwargs['role'] = role
            uid = author_attrs.get('id')
            if uid is not None:
                kwargs['uid'] = uid
            # Add the author with only the valid keyword arguments
            new_book.add_author(author_name, **kwargs)
        # Copy other relevant metadata if needed (publisher, rights, etc.)
        logging.info(f"Set metadata for abridged EPUB: Title='{new_book.title}'")
    except Exception as e:
        logging.warning(f"Could not set some metadata for the abridged EPUB: {e}")

    # --- Process Items and Replace Content ---
    original_items = {item.id: item for item in original_book.get_items()}

    # Create the summary map based on the parsed documents and their summaries
    if len(chapter_summaries) != len(parsed_docs):
         logging.error(f"Mismatch between number of summaries ({len(chapter_summaries)}) and number of parsed documents ({len(parsed_docs)}). Cannot map summaries correctly.")
         return False

    summary_map = {}
    for doc, summary in zip(parsed_docs, chapter_summaries):
        item_id = doc.metadata.get('epub_item_id')
        if item_id:
            summary_map[item_id] = summary
        else:
            logging.warning(f"Parsed document for chapter '{doc.metadata.get('chapter_title')}' is missing 'epub_item_id' in metadata. Cannot replace content.")

    if not summary_map:
         logging.error("Summary map is empty. No chapter content can be replaced.")
         return False
    new_items = {} # Store newly created/copied items

    for item_id, item in original_items.items():
        if item.id in summary_map: # This is a chapter document to be replaced
            summary_text = summary_map[item.id]
            # Basic HTML formatting for the summary
            html_content = summary_text.replace('\n', '<br/>\n')
            # Try to keep original title if possible, otherwise use item name
            title = item.title or item.get_name().replace('.xhtml', '').replace('.html', '').replace('_', ' ').title()

            new_chapter = epub.EpubHtml(
                title=title,
                file_name=item.file_name, # Keep original filename
                lang=new_book.language,
                uid=item.id # Keep original ID
            )
            # Wrap summary in basic HTML structure
            new_chapter.content = f'<html><head><title>{title}</title></head><body><h1>{title}</h1>{html_content}</body></html>'
            new_book.add_item(new_chapter)
            new_items[item.id] = new_chapter
            logging.debug(f"Replaced content for chapter item: {item.file_name}")
        else:
            # Copy other items (CSS, images, Nav, NCX, etc.) directly
            new_book.add_item(item)
            new_items[item.id] = item
            logging.debug(f"Copied item: {item.file_name} (Type: {item.get_type()})")


    # --- Add Overall Summary Chapter ---
    if overall_summary:
        summary_title = "Book Summary"
        summary_file_name = "chap_overall_summary.xhtml"
        summary_id = "overall_summary"
        html_summary_content = overall_summary.replace('\n', '<br/>\n')
        summary_chapter_content = f'<html><head><title>{summary_title}</title></head><body><h1>{summary_title}</h1>{html_summary_content}</body></html>'

        summary_chapter = epub.EpubHtml(
            title=summary_title,
            file_name=summary_file_name,
            lang=new_book.language,
            uid=summary_id
        )
        summary_chapter.content = summary_chapter_content
        new_book.add_item(summary_chapter)
        new_items[summary_id] = summary_chapter
        logging.info("Added overall summary chapter.")
    else:
        summary_chapter = None
        logging.warning("No overall summary provided, skipping summary chapter.")


    # --- Reconstruct Spine ---
    # Use original spine order, replacing items with their new versions
    new_spine = []
    for item_id, linear in original_book.spine:
         if item_id in new_items: # Ensure item was processed/copied
              new_spine.append(new_items[item_id])
         elif item_id == 'nav': # Handle default nav item if not explicitly copied
              nav_item = new_book.get_item_with_href('nav.xhtml') # Default nav file name
              if nav_item:
                   new_spine.append(nav_item)
              else: # Add default if missing
                   nav_item_default = epub.EpubNav()
                   new_book.add_item(nav_item_default)
                   new_spine.append(nav_item_default)
         elif item_id == 'ncx': # Handle default ncx item if not explicitly copied
              ncx_item = new_book.get_item_with_id('ncx') # Default ncx id
              if ncx_item:
                   new_spine.append(ncx_item)
              else: # Add default if missing
                   ncx_item_default = epub.EpubNcx()
                   new_book.add_item(ncx_item_default)
                   new_spine.append(ncx_item_default)
         else:
              logging.warning(f"Item '{item_id}' from original spine not found in new items. Skipping.")

    # Add the overall summary chapter to the end of the spine if it exists
    if summary_chapter:
        new_spine.append(summary_chapter)
    new_book.spine = new_spine


    # --- Reconstruct TOC ---
    # Create TOC based on the new spine items that are EpubHtml
    new_toc = []
    for item in new_book.spine:
        # Check if it's an EpubHtml item and not the nav file itself
        if isinstance(item, epub.EpubHtml) and item.is_chapter():
             # Use item's title and file_name for the link (remove uid)
             new_toc.append(epub.Link(item.file_name, item.title))

    new_book.toc = tuple(new_toc)

    # Ensure Nav and NCX items are present (add defaults if somehow missed)
    if not new_book.get_item_with_href('nav.xhtml'):
         logging.warning("Nav item missing, adding default.")
         new_book.add_item(epub.EpubNav())
    if not new_book.get_item_with_id('ncx'):
         logging.warning("NCX item missing, adding default.")
         new_book.add_item(epub.EpubNcx())

    # --- Write EPUB File ---
    try:
        # Ensure the output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        epub.write_epub(output_path, new_book, {})
        logging.info(f"Abridged EPUB successfully written to: {output_path}")
        return True
    except Exception as e:
        logging.error(f"Failed to write EPUB file to {output_path}: {e}", exc_info=True)
        return False

# Example usage (for testing purposes)
if __name__ == '__main__':
    print("\n--- EPUB Builder Test ---")

    # Dummy data
    # --- Test requires a real EPUB file now ---
    test_epub_path = 'path/to/your/test_book.epub' # <--- CHANGE THIS
    test_output_dir = "test_output"
    test_output_path = os.path.join(test_output_dir, "abridged_test_book.epub")

    if not os.path.exists(test_epub_path):
         print(f"Test EPUB file not found: {test_epub_path}. Skipping build test.")
         sys.exit()

    print(f"Reading original EPUB: {test_epub_path}")
    original_book = epub.read_epub(test_epub_path)
    spine_docs = [item for item in original_book.get_items() if item.id in dict(original_book.spine) and item.get_type() == ebooklib.ITEM_DOCUMENT]

    # Create dummy summaries matching the number of chapters
    num_chapters = len(spine_docs)
    dummy_chapter_summaries = [f"This is the summary for chapter {i+1}." for i in range(num_chapters)]
    dummy_overall_summary = "This is the overall summary of the entire test book."

    # Create output directory if it doesn't exist
    if not os.path.exists(test_output_dir):
        os.makedirs(test_output_dir)
        print(f"Created test output directory: {test_output_dir}")

    print(f"Attempting to build EPUB at: {test_output_path}")
    success = build_epub(
        chapter_summaries=dummy_chapter_summaries,
        overall_summary=dummy_overall_summary,
        original_book=original_book,
        output_path=test_output_path
    )

    if success:
        print(f"EPUB build successful. Check '{test_output_path}'.")
    else:
        print("EPUB build failed.")