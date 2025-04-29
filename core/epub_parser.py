import re
import ebooklib
from ebooklib import epub
from ebooklib.epub import Section, Link
from bs4 import BeautifulSoup
from langchain_core.documents import Document
import logging
from core.token_counter import count_tokens  # Import token counter

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_book_metadata(book) -> dict:
    """Extracts metadata from the EPUB book."""
    metadata = {
        'title': 'Unknown Title',
        'author': 'Unknown Author',
        'language': 'en',
        'identifier': None
    }
    try:
        dc_title    = book.get_metadata('DC', 'title')
        dc_creator  = book.get_metadata('DC', 'creator')
        dc_language = book.get_metadata('DC', 'language')
        dc_id       = book.get_metadata('DC', 'identifier')

        if dc_title:
            metadata['title']      = dc_title[0][0]
        if dc_creator:
            metadata['author']     = dc_creator[0][0]
        if dc_language:
            metadata['language']   = dc_language[0][0]
        if dc_id:
            metadata['identifier'] = dc_id[0][0]

        # fallbacks
        if metadata['title']=='Unknown Title' and getattr(book, 'title', None):
            metadata['title'] = book.title
        if metadata['language']=='en' and getattr(book, 'language', None):
            metadata['language'] = book.language
        if metadata['identifier'] is None and getattr(book, 'identifier', None):
            metadata['identifier'] = book.identifier

    except Exception as e:
        logging.warning(f"Could not extract some metadata: {e}")
    return metadata

def detect_genre_from_metadata(book) -> str | None:
    """Try to infer fiction vs non-fiction from DC subjects."""
    subjects = book.get_metadata('DC', 'subject') or []
    for subj, _ in subjects:
        sub = subj.lower()
        if any(k in sub for k in ('fiction','novel','story','tale')):
            return 'Fiction'
        if any(k in sub for k in ('non-fiction','science','economics','essay','memoir','guide')):
            return 'Non-Fiction'
    return None

def detect_genre_by_text(text: str) -> str:
    """Heuristic: chapters with dialogue or 'Chapter' headings → Fiction, else Non-Fiction."""
    sample = text[:2000].lower()
    if re.search(r'chapter\s+[ivxlcdm0-9]', sample) or sample.count('“') > 2:
        return 'Fiction'
    if re.search(r'\d+\.\s+\w+', sample) or 'figure ' in sample or 'et al.' in sample:
        return 'Non-Fiction'
    return 'Fiction'

def extract_cover(file_path: str) -> bytes | None:
    book = epub.read_epub(file_path)
    meta_cover = book.get_metadata('OPF', 'meta') or []
    cover_id = next((v['content'] for _, v in meta_cover if v.get('name')=='cover'), None)
    if not cover_id:
        return None
    item = book.get_item_with_id(cover_id)
    return item.get_content() if item else None

def parse_epub(file_path: str) -> tuple[list[Document], dict]:
    """
    Parses an EPUB file, extracting:
      - A list of Documents for each chapter (with title, number, token_count, genre, etc.)
      - A metadata dict (including cover_image_bytes and detected genre)
    """
    chapters: list[Document] = []
    metadata: dict = {}
    try:
        book = epub.read_epub(file_path)
        metadata = get_book_metadata(book)
        logging.info(f"Parsing EPUB: '{metadata['title']}'")

        # Extract cover
        cover_bytes = extract_cover(file_path)
        metadata['cover_image_bytes'] = cover_bytes

        # Build ToC map
        toc_map: dict[str,str] = {}
        def extract_toc_entries(entries):
            for e in entries:
                if isinstance(e, Link):
                    href = e.href.split('#')[0]
                    toc_map[href] = e.title
                elif isinstance(e, Section):
                    href = e.href.split('#')[0] if e.href else ''
                    if href:
                        toc_map[href] = e.title
                    extract_toc_entries(e.subitems)
        extract_toc_entries(book.toc)

        # Prepare for genre detection
        # Try metadata first
        genre = detect_genre_from_metadata(book)
        # If none, sample first document item
        if not genre:
            docs = [i for i in book.get_items() if i.get_type()==ebooklib.ITEM_DOCUMENT]
            if docs:
                sample_text = BeautifulSoup(docs[0].get_content(), 'html.parser').get_text()
                genre = detect_genre_by_text(sample_text)
            else:
                genre = 'Fiction'
        metadata['genre'] = genre
        logging.info(f"Inferred genre: {genre}")

        # Process spine in order
        spine_ids  = [sid for sid,_ in book.spine]
        items_dict = {it.id: it for it in book.get_items()}
        logical_count = 0
        skip_keywords = ['table of contents','contents','preface','foreword','introduction']

        for item_id in spine_ids:
            item = items_dict.get(item_id)
            if not item or item.get_type()!=ebooklib.ITEM_DOCUMENT:
                continue
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            body = soup.find('body')
            text = body.get_text(separator='',strip=True) if body else soup.get_text(separator='',strip=True)
            if not text:
                continue

            # Title extraction
            fn = item.get_name()
            title = toc_map.get(fn)
            if not title:
                if soup.title and soup.title.string:
                    title = soup.title.string.strip()
                else:
                    h = soup.find(['h1','h2','h3'])
                    title = h.get_text(strip=True) if h else ''
            if any(k in title.lower() for k in skip_keywords):
                continue

            logical_count += 1
            chap_num   = logical_count
            chap_title = title or f"Chapter {chap_num}"
            tok_count  = count_tokens(text, model_name="gpt-4")

            doc = Document(
                page_content=text,
                metadata={
                    'source': file_path,
                    'chapter_title': chap_title,
                    'chapter_number': chap_num,
                    'token_count': tok_count,
                    'epub_item_id': item.id,
                    'epub_item_name': fn,
                    'book_title': metadata['title'],
                    'book_author': metadata['author'],
                    'genre': genre
                }
            )
            chapters.append(doc)
            logging.debug(f"Added chapter {chap_num}: '{chap_title}' ({tok_count} tokens)")

        if not chapters:
            logging.warning(f"No valid chapters found in {file_path}")
        else:
            logging.info(f"Parsed {len(chapters)} chapters from '{metadata['title']}'")

    except FileNotFoundError:
        logging.error(f"EPUB file not found: {file_path}")
        raise
    except Exception as e:
        logging.error(f"Failed to parse EPUB {file_path}: {e}", exc_info=True)
        return [], metadata

    return chapters, metadata
