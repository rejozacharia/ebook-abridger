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
    along with book metadata.

    Args:
        file_path: The path to the EPUB file.

    Returns:
        A tuple containing:
        - A list of LangChain Document objects, each representing a chapter.
        - A dictionary containing the book's metadata.
    """
    chapters = []
    metadata = {}
    try:
        book = epub.read_epub(file_path)
        metadata = get_book_metadata(book)
        logging.info(f"Parsing EPUB: '{metadata.get('title', 'Unknown Title')}'")

        # Process items in the order defined by the spine
        spine_ids = [item_id for item_id, _ in book.spine]
        items_dict = {item.id: item for item in book.get_items()}
        
        chapter_count = 0
        for item_id in spine_ids:
            item = items_dict.get(item_id)
            if item is None:
                logging.warning(f"Item with ID '{item_id}' from spine not found in items.")
                continue

            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                chapter_count += 1
                logging.debug(f"Processing chapter item: {item.get_name()} (ID: {item.id})")
                
                try:
                    soup = BeautifulSoup(item.get_content(), 'html.parser')
                    
                    # Extract text content
                    body = soup.find('body')
                    if body:
                        # Get text, try to preserve some structure with separators
                        text_content = body.get_text(separator='\n', strip=True)
                    else:
                        # Fallback if no body tag found
                        text_content = soup.get_text(separator='\n', strip=True)

                    if not text_content:
                        logging.warning(f"Chapter item {item.get_name()} has no text content. Skipping.")
                        continue

                    # Try to find a title within the chapter content
                    title = f"Chapter {chapter_count}" # Default title
                    title_tag = soup.find(['h1', 'h2', 'h3'])
                    if title_tag and title_tag.get_text(strip=True):
                        title = title_tag.get_text(strip=True)
                    
                    # Count tokens (using a placeholder model name for now, as actual model isn't known here)
                    # A more accurate approach might pass the selected model later or use a generic tokenizer
                    token_count = count_tokens(text_content, model_name="gpt-4") # Using gpt-4 as proxy

                    # Create LangChain Document
                    doc = Document(
                        page_content=text_content,
                        metadata={
                            'source': file_path,
                            'chapter_title': title,
                            'chapter_number': chapter_count,
                            'token_count': token_count, # Add token count
                            'epub_item_id': item.id,
                            'epub_item_name': item.get_name(),
                            'book_title': metadata.get('title'),
                            'book_author': metadata.get('author')
                        }
                    )
                    chapters.append(doc)
                    logging.debug(f"Added chapter: '{title}' (Tokens: {token_count}, Length: {len(text_content)} chars)")

                except Exception as e:
                    logging.error(f"Error processing chapter item {item.get_name()}: {e}", exc_info=True)

            elif item.get_type() == ebooklib.ITEM_NAVIGATION:
                 logging.debug(f"Skipping navigation item: {item.get_name()}")
            elif item.get_type() == ebooklib.ITEM_COVER:
                 logging.debug(f"Skipping cover item: {item.get_name()}")
            # Add other item types to skip if necessary (e.g., stylesheets, images)

        if not chapters:
             logging.warning(f"No valid chapter content found in {file_path}")
        else:
             logging.info(f"Successfully parsed {len(chapters)} chapters from '{metadata.get('title', file_path)}'.")

    except FileNotFoundError:
        logging.error(f"EPUB file not found: {file_path}")
        raise
    except Exception as e:
        logging.error(f"Failed to parse EPUB file {file_path}: {e}", exc_info=True)
        # Return empty list and potentially partial metadata if parsing failed mid-way
        return [], metadata

    return chapters, metadata

# Example usage (for testing purposes)
if __name__ == '__main__':
    # Replace with a path to an actual EPUB file for testing
    test_epub_path = 'path/to/your/ebook.epub' 
    try:
        docs, meta = parse_epub(test_epub_path)
        if docs:
            print(f"\n--- Metadata ---")
            for key, value in meta.items():
                print(f"{key.capitalize()}: {value}")
            
            print(f"\n--- Parsed Chapters ({len(docs)}) ---")
            # Print info about the first chapter, including token count
            print(f"\nChapter 1 Metadata: {docs[0].metadata}")
            print(f"Chapter 1 Token Count: {docs[0].metadata.get('token_count', 'N/A')}")
            print(f"\nChapter 1 Content (first 500 chars):\n{docs[0].page_content[:500]}...")
        else:
            print(f"Could not parse chapters from {test_epub_path}")
            
    except FileNotFoundError:
         print(f"Test file not found: {test_epub_path}. Please update the path in epub_parser.py for testing.")
    except Exception as e:
         print(f"An error occurred during testing: {e}")