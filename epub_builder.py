import ebooklib
from ebooklib import epub
import logging
from typing import Dict, Optional
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def build_epub(
    abridged_content: str,
    original_metadata: Dict,
    output_path: str,
    abridged_title_prefix: str = "Abridged: "
):
    """
    Builds a new EPUB file from the abridged text content and original metadata.
    Currently places all abridged content into a single chapter.

    Args:
        abridged_content: The full abridged text as a single string.
        original_metadata: A dictionary containing metadata from the original book
                           (e.g., 'title', 'author', 'language', 'identifier').
        output_path: The full path where the new EPUB file should be saved.
        abridged_title_prefix: Prefix to add to the original title for the abridged version.
    """
    if not abridged_content:
        logging.error("Cannot build EPUB: Abridged content is empty.")
        return False
    if not output_path:
        logging.error("Cannot build EPUB: Output path is not specified.")
        return False

    book = epub.EpubBook()

    # --- Set Metadata ---
    try:
        original_title = original_metadata.get('title', 'Untitled')
        book.set_title(f"{abridged_title_prefix}{original_title}")

        author = original_metadata.get('author', 'Unknown Author')
        book.add_author(author)

        language = original_metadata.get('language', 'en')
        book.set_language(language)

        identifier = original_metadata.get('identifier')
        if identifier:
            book.set_identifier(f"urn:uuid:{identifier}-abridged") # Modify original ID slightly
        else:
             # Generate a simple identifier if none exists
             import uuid
             book.set_identifier(f"urn:uuid:{uuid.uuid4()}")
             
        logging.info(f"Set metadata for abridged EPUB: Title='{book.title}', Author='{author}', Lang='{language}'")

    except Exception as e:
        logging.warning(f"Could not set some metadata for the abridged EPUB: {e}")


    # --- Create Content Chapter ---
    # Simple approach: Put all content into one chapter.
    # More advanced: Could try splitting content by paragraphs or heuristics if needed.
    
    # Basic HTML structure for the chapter content
    # Replace newlines with <br> tags for basic paragraph breaks in HTML
    html_content = abridged_content.replace('\n', '<br/>\n')
    chapter_content_full = f'<html><head><title>Abridged Content</title></head><body>{html_content}</body></html>'

    main_chapter = epub.EpubHtml(
        title='Abridged Content',
        file_name='chap_abridged.xhtml',
        lang=language # Use the book's language for the chapter
    )
    main_chapter.content = chapter_content_full
    book.add_item(main_chapter)

    # --- Define Book Structure ---
    # Basic spine: Navigation (NCX) and the single content chapter
    book.spine = ['nav', main_chapter]

    # Add default NCX (Table of Contents generator) and Nav file
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Define TOC programmatically (linking to the single chapter)
    # The toc is a tuple of Links or Sections
    book.toc = (epub.Link(main_chapter.file_name, main_chapter.title, 'abridged-chapter'),)

    # --- Write EPUB File ---
    try:
        # Ensure the output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        epub.write_epub(output_path, book, {})
        logging.info(f"Abridged EPUB successfully written to: {output_path}")
        return True
    except Exception as e:
        logging.error(f"Failed to write EPUB file to {output_path}: {e}", exc_info=True)
        return False

# Example usage (for testing purposes)
if __name__ == '__main__':
    print("\n--- EPUB Builder Test ---")

    # Dummy data
    test_content = "This is the first paragraph of the abridged book.\n\nThis is the second paragraph, following the first one after a break."
    test_metadata = {
        'title': 'The Original Adventure',
        'author': 'Test Author',
        'language': 'en',
        'identifier': 'orig-isbn-12345'
    }
    test_output_dir = "test_output"
    test_output_path = os.path.join(test_output_dir, "abridged_book.epub")

    # Create output directory if it doesn't exist
    if not os.path.exists(test_output_dir):
        os.makedirs(test_output_dir)
        print(f"Created test output directory: {test_output_dir}")

    print(f"Attempting to build EPUB at: {test_output_path}")
    success = build_epub(test_content, test_metadata, test_output_path)

    if success:
        print(f"EPUB build successful. Check '{test_output_path}'.")
        # Optional: Clean up test file
        # os.remove(test_output_path)
        # os.rmdir(test_output_dir) # Only if empty
    else:
        print("EPUB build failed.")