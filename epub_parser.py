import ebooklib
from ebooklib import epub
from ebooklib.epub import Section, Link
from bs4 import BeautifulSoup
from langchain_core.documents import Document
import logging
from utils import count_tokens  # Import token counter

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_book_metadata(book) -> dict:
    """Extracts metadata from the EPUB book."""
    metadata = {
        'title': 'Unknown Title',
        'author': 'Unknown Author',
        'language': 'en',  # Default language
        'identifier': None
    }
    try:
        # Standard Dublin Core metadata fields
        dc_title     = book.get_metadata('DC', 'title')
        dc_creator   = book.get_metadata('DC', 'creator')
        dc_language  = book.get_metadata('DC', 'language')
        dc_id        = book.get_metadata('DC', 'identifier')

        if dc_title:
            metadata['title']       = dc_title[0][0]
        if dc_creator:
            metadata['author']      = dc_creator[0][0]
        if dc_language:
            metadata['language']    = dc_language[0][0]
        if dc_id:
            metadata['identifier']  = dc_id[0][0]

        # Fallbacks to book attributes if metadata missing
        if metadata['title'] == 'Unknown Title' and getattr(book, 'title', None):
            metadata['title'] = book.title
        if metadata['language'] == 'en' and getattr(book, 'language', None):
            metadata['language'] = book.language
        if metadata['identifier'] is None and getattr(book, 'identifier', None):
            metadata['identifier'] = book.identifier

    except Exception as e:
        logging.warning(f"Could not extract some metadata: {e}")

    return metadata

def extract_cover(file_path: str) -> bytes | None:
    book = epub.read_epub(file_path)
    # 1. Read OPF to find cover-id
    #    <meta name="cover" content="cover-id"/>
    meta_cover = book.get_metadata('OPF', 'meta') or []
    cover_id = next((v['content'] for _, v in meta_cover if v.get('name') == 'cover'), None)
    if not cover_id:
        return None

    # 2. Fetch the image item by ID
    cover_item = book.get_item_with_id(cover_id)
    if not cover_item:
        return None

    # 3. Return raw image bytes
    return cover_item.get_content()

def parse_epub(file_path: str) -> tuple[list[Document], dict]:
    """
    Parses an EPUB file, extracts chapters as text, and returns them as LangChain Documents
    along with book metadata.
    """
    chapters: list[Document] = []
    try:
        # Read the EPUB
        book = epub.read_epub(file_path)

        # Extract metadata
        metadata = get_book_metadata(book)
        logging.info(f"Parsing EPUB: '{metadata.get('title', 'Unknown Title')}'")

        # ─── Extract cover image bytes ────────────────────────────────
        cover_bytes = None
        meta_cover = book.get_metadata('OPF', 'meta') or []
        cover_id = next((v['content'] for _, v in meta_cover
                        if v.get('name') == 'cover'), None)
        if cover_id:
            cover_item = book.get_item_with_id(cover_id)
            if cover_item:
                cover_bytes = cover_item.get_content()
        metadata['cover_image_bytes'] = cover_bytes


        # ─── Build ToC map: href → title ────────────────────────────────────────────
        toc_map: dict[str, str] = {}
        def extract_toc_entries(entries):
            for entry in entries:
                if isinstance(entry, Link):
                    href = entry.href.split('#')[0]
                    toc_map[href] = entry.title
                elif isinstance(entry, Section):
                    href = entry.href.split('#')[0] if entry.href else ''
                    if href:
                        toc_map[href] = entry.title
                    extract_toc_entries(entry.subitems)

        extract_toc_entries(book.toc)

        # Process items in the order defined by the spine
        spine_ids   = [item_id for item_id, _ in book.spine]
        items_dict  = {item.id: item for item in book.get_items()}

        logical_count   = 0
        skip_keywords   = ['table of contents', 'contents', 'preface', 'foreword', 'introduction']

        for item_id in spine_ids:
            item = items_dict.get(item_id)
            if not item or item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue

            try:
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                body = soup.find('body')
                text_content = body.get_text(separator='', strip=True) if body else soup.get_text(separator='', strip=True)
                if not text_content:
                    logging.debug(f"Skipping empty document: {item.get_name()}")
                    continue

                # ─── Chapter title extraction ────────────────────────────────────────
                file_name = item.get_name()                   # e.g., 'chapter1.xhtml'
                title_text = toc_map.get(file_name)           # ToC title if available

                # Fallback to <title> tag or first heading
                if not title_text:
                    if soup.title and soup.title.string:
                        title_text = soup.title.string.strip()
                    else:
                        heading = soup.find(['h1', 'h2', 'h3'])
                        title_text = heading.get_text(strip=True) if heading else ''

                lower_title = (title_text or '').lower()
                # Skip frontmatter sections
                if any(kw in lower_title for kw in skip_keywords):
                    logging.info(f"Skipping auxiliary section: '{title_text or file_name}'")
                    continue

                logical_count += 1
                chapter_number = logical_count
                chapter_title  = title_text or f"Chapter {chapter_number}"

                # Token counting
                token_count = count_tokens(text_content, model_name="gpt-4")

                # Build LangChain Document
                doc = Document(
                    page_content=text_content,
                    metadata={
                        'source': file_path,
                        'chapter_title': chapter_title,
                        'chapter_number': chapter_number,
                        'token_count': token_count,
                        'epub_item_id': item.id,
                        'epub_item_name': file_name,
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
            logging.info(f"Successfully parsed {len(chapters)} chapters from '{metadata.get('title')}'.")

    except FileNotFoundError:
        logging.error(f"EPUB file not found: {file_path}")
        raise
    except Exception as e:
        logging.error(f"Failed to parse EPUB {file_path}: {e}", exc_info=True)
        return [], metadata

    return chapters, metadata
