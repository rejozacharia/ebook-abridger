import tiktoken
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Global cache for tokenizer encodings to avoid re-initialization
_tokenizer_cache = {}

def count_tokens(text: str, model_name: str = "gpt-4") -> int:
    """
    Counts the number of tokens in a given text string using tiktoken.

    Args:
        text: The text string to count tokens for.
        model_name: The name of the model to use for tokenization (e.g., "gpt-4", "gpt-3.5-turbo").
                    This helps select the appropriate encoding. Defaults to "gpt-4".

    Returns:
        The estimated number of tokens in the text. Returns 0 if text is empty or an error occurs.
    """
    if not text:
        return 0

    global _tokenizer_cache
    try:
        # Get encoding from cache or initialize it
        if model_name not in _tokenizer_cache:
            _tokenizer_cache[model_name] = tiktoken.encoding_for_model(model_name)
        
        encoding = _tokenizer_cache[model_name]
        tokens = encoding.encode(text)
        return len(tokens)
    except KeyError:
        # Fallback if the specific model encoding is not found by tiktoken
        logging.warning(f"Tiktoken encoding for model '{model_name}' not found. Falling back to 'cl100k_base'.")
        try:
            # Use a common base encoding as a fallback
            if "cl100k_base" not in _tokenizer_cache:
                 _tokenizer_cache["cl100k_base"] = tiktoken.get_encoding("cl100k_base")
            encoding = _tokenizer_cache["cl100k_base"]
            tokens = encoding.encode(text)
            return len(tokens)
        except Exception as e:
            logging.error(f"Could not count tokens using fallback encoding: {e}", exc_info=True)
            return 0 # Indicate failure
    except Exception as e:
        logging.error(f"An error occurred during token counting: {e}", exc_info=True)
        return 0 # Indicate failure

# Example usage (for testing purposes)
if __name__ == '__main__':
    sample_text = "This is a sample text to test the token counting function."
    token_count_gpt4 = count_tokens(sample_text, model_name="gpt-4")
    token_count_gpt35 = count_tokens(sample_text, model_name="gpt-3.5-turbo")
    token_count_unknown = count_tokens(sample_text, model_name="unknown-model-xyz") # Test fallback

    print(f"Sample text: '{sample_text}'")
    print(f"Token count (using gpt-4 encoding): {token_count_gpt4}")
    print(f"Token count (using gpt-3.5-turbo encoding): {token_count_gpt35}")
    print(f"Token count (using fallback encoding for unknown model): {token_count_unknown}")

    empty_text_count = count_tokens("")
    print(f"Token count for empty text: {empty_text_count}")