import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from langchain_core.documents import Document
import logging
from utils import count_tokens # Import token counter

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_book_metadata(book):
    """Extracts metadata from the EPUB book."""
    metadata = {
        'title': 'Unknown Title',
        'author': 'Unknown Author',
        'language': 'en', # Default language
        'identifier': None
    }
    try:
        # Try standard Dublin Core metadata fields
        dc_metadata = book.get_metadata('DC', {})
        if dc_metadata:
            metadata['title'] = dc_metadata.get('title', [('Unknown Title', {})])[0][0]
            metadata['author'] = dc_metadata.get('creator', [('Unknown Author', {})])[0][0]
            metadata['language'] = dc_metadata.get('language', [('en', {})])[0][0]
            metadata['identifier'] = dc_metadata.get('identifier', [(None, {})])[0][0]

        # Fallback for title if not in DC
        if metadata['title'] == 'Unknown Title' and book.title:
             metadata['title'] = book.title
        # Fallback for language if not in DC
        if metadata['language'] == 'en' and book.language:
             metadata['language'] = book.language
        # Fallback for identifier if not in DC
        if metadata['identifier'] is None and book.identifier:
             metadata['identifier'] = book.identifier

    except Exception as e:
        logging.warning(f"Could not extract some metadata: {e}")

    return metadata


def parse_epub(file_path: str) -> tuple[list[Document], dict]:
    """
    Parses an EPUB file, extracts chapters as text, and returns them as LangChain Documents
    along with book metadata. Skips frontmatter like table of contents or preface.

    Args:
        file_path: The path to the EPUB file.

    Returns:
        A tuple containing:
        - A list of LangChain Document objects, each representing a chapter.
        - A dictionary containing the book's metadata.
    """
    chapters: list[Document] = []
    metadata: dict = {}
    try:
        book = epub.read_epub(file_path)
        metadata = get_book_metadata(book)
        logging.info(f"Parsing EPUB: '{metadata.get('title', 'Unknown Title')}'")

        # Process items in the order defined by the spine
        spine_ids = [item_id for item_id, _ in book.spine]
        items_dict = {item.id: item for item in book.get_items()}

        logical_count = 0
        skip_keywords = ['table of contents', 'contents', 'preface', 'foreword', 'introduction']

        for item_id in spine_ids:
            item = items_dict.get(item_id)
            if not item or item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue

            try:
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                # Extract raw text
                body = soup.find('body')
                text_content = body.get_text(separator='', strip=True) if body else soup.get_text(separator='', strip=True)
                if not text_content:
                    logging.debug(f"Skipping empty document: {item.get_name()}")
                    continue

                # Extract title: prefer <title> tag, else first heading
                title_text = None
                if soup.title and soup.title.string:
                    title_text = soup.title.string.strip()
                else:
                    heading = soup.find(['h1', 'h2', 'h3'])
                    if heading and heading.get_text(strip=True):
                        title_text = heading.get_text(strip=True)
                title_text = title_text or ''
                lower_title = title_text.lower()

                # Skip frontmatter
                if any(kw in lower_title for kw in skip_keywords):
                    logging.info(f"Skipping auxiliary section: '{title_text or item.get_name()}'")
                    continue

                # This is a logical chapter
                logical_count += 1
                chapter_number = logical_count
                chapter_title = title_text or f"Chapter {chapter_number}"

                # Count tokens (placeholder model)
                token_count = count_tokens(text_content, model_name="gpt-4")

                # Create LangChain Document
                doc = Document(
                    page_content=text_content,
                    metadata={
                        'source': file_path,
                        'chapter_title': chapter_title,
                        'chapter_number': chapter_number,
                        'token_count': token_count,
                        'epub_item_id': item.id,
                        'epub_item_name': item.get_name(),
                        'book_title': metadata.get('title'),
                        'book_author': metadata.get('author')
                    }
                )
                chapters.append(doc)
                logging.debug(f"Added chapter {chapter_number}: '{chapter_title}' ({token_count} tokens)")

            except Exception as e:
                logging.error(f"Error processing chapter item {item.get_name()}: {e}", exc_info=True)

        if not chapters:
            logging.warning(f"No valid chapters found in {file_path}")
        else:
            logging.info(f"Successfully parsed {len(chapters)} chapters from '{metadata.get('title', file_path)}'.")

    except FileNotFoundError:
        logging.error(f"EPUB file not found: {file_path}")
        raise
    except Exception as e:
        logging.error(f"Failed to parse EPUB {file_path}: {e}", exc_info=True)
        return [], metadata

    return chapters, metadata
