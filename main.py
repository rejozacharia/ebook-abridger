import argparse
import logging
import os
import sys
from typing import Optional

# Import necessary components from our modules
from epub_parser import parse_epub
from cost_estimator import estimate_abridgment_cost
from summarizer import SummarizationEngine
from epub_builder import build_epub
from llm_config import get_default_model # Import new function

# Configure logging
# Set level to INFO, could be made configurable via args later
import os
print("Working directory:", os.getcwd())
logging.basicConfig(filename='abridger_engine.log',level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(module)s] %(message)s', force=True)

# Pass args explicitly to confirm_proceed to access model info
def confirm_proceed(args, estimated_tokens: dict, estimated_cost: float) -> bool:
    """Asks the user for confirmation after showing estimates."""
    # Determine which model name was actually used for estimation
    model_used = args.model or get_default_model(args.provider) or "Unknown"
    print("\n--- Cost & Token Estimates ---")
    print(f"  Provider: {args.provider}")
    print(f"  Model: {model_used}{' (Default)' if not args.model else ''}")
    print(f"  Total Estimated Tokens: {estimated_tokens.get('total_tokens', 0):,}")
    print(f"    Input Tokens:       {estimated_tokens.get('total_input_tokens', 0):,}")
    print(f"    Output Tokens:      {estimated_tokens.get('total_output_tokens', 0):,}")
    print(f"  Estimated Cost:       ${estimated_cost:.4f}")
    print("-----------------------------")

    if estimated_cost == 0 and estimated_tokens.get('total_tokens', 0) > 0:
        print("Note: Estimated cost is $0.00 (likely using a local model like Ollama).")
    elif estimated_cost == 0 and estimated_tokens.get('total_tokens', 0) == 0:
         print("Warning: Token estimation resulted in zero tokens. Cannot proceed.")
         return False

    while True:
        try:
            response = input("Do you want to proceed with abridgment? (yes/no): ").lower().strip()
            if response in ['yes', 'y']:
                return True
            elif response in ['no', 'n']:
                return False
            else:
                print("Invalid input. Please enter 'yes' or 'no'.")
        except EOFError: # Handle cases where input stream is closed unexpectedly
             logging.warning("EOF received while waiting for confirmation. Aborting.")
             return False


def main(args):
    """Main function to orchestrate the ebook abridgment process."""
    logging.info(f"Starting ebook abridgment process for: {args.input_epub}")
    # Determine the actual model being used (specified or default) for logging
    actual_model_name = args.model or get_default_model(args.provider)
    logging.info(f"LLM Provider: {args.provider}, Model: {actual_model_name}{' (Default)' if not args.model else ''}")

    # 1. Parse EPUB
    logging.info("Parsing EPUB file...")
    try:
        chapter_docs, metadata = parse_epub(args.input_epub)
        if not chapter_docs:
            logging.error("Failed to parse any chapters from the EPUB. Exiting.")
            sys.exit(1)
        logging.info(f"Parsed {len(chapter_docs)} chapters from '{metadata.get('title', 'Unknown Title')}'.")
    except FileNotFoundError:
        logging.error(f"Input EPUB file not found: {args.input_epub}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"An unexpected error occurred during EPUB parsing: {e}", exc_info=True)
        sys.exit(1)

    # 2. Estimate Cost & Tokens
    logging.info("Estimating token usage and cost...")
    # Determine the model name to use for estimation (use default if not specified)
    # Determine the model name to use for estimation (use default from config if not specified)
    estimation_model_name = args.model or get_default_model(args.provider)
    if not estimation_model_name:
         # This handles cases where the provider is valid but no default is configured in .env
         logging.error(f"Model not specified and no default model found for provider '{args.provider}' in .env configuration.")
         sys.exit(1)
              
    try:
        token_estimates, cost_estimate = estimate_abridgment_cost(chapter_docs, estimation_model_name)
    except Exception as e:
        logging.error(f"An unexpected error occurred during cost estimation: {e}", exc_info=True)
        sys.exit(1) # Exit if estimation fails

    # 3. Confirm with User
    if not args.yes: # Skip confirmation if -y flag is used
        # Pass args to confirm_proceed so it can display the correct model name
        if not confirm_proceed(args, token_estimates, cost_estimate):
            logging.info("Abridgment cancelled by user.")
            sys.exit(0)
        logging.info("User confirmed. Proceeding with abridgment...")
    else:
         logging.info("Skipping confirmation due to -y flag.")
         if token_estimates.get('total_tokens', 0) == 0:
              logging.error("Cannot proceed with -y flag: Estimated tokens are zero.")
              sys.exit(1)


    # 4. Initialize Summarization Engine
    logging.info("Initializing summarization engine...")
    try:
        engine = SummarizationEngine(
            llm_provider=args.provider,
            llm_model_name=args.model, # Pass None if user didn't specify, engine uses default
            temperature=args.temperature
            # chain_type can be added as arg later if needed
        )
        if not engine.llm or not engine.chain:
             # Errors should have been logged by the engine constructor
             logging.error("Failed to initialize summarization engine. Exiting.")
             sys.exit(1)
    except Exception as e:
        logging.error(f"An unexpected error occurred during summarization engine initialization: {e}", exc_info=True)
        sys.exit(1)


    # 5. Summarize / Abridge
    logging.info("Starting abridgment...")
    abridged_text: Optional[str] = None
    try:
        abridged_text = engine.abridge_documents(chapter_docs)
        if abridged_text is None:
            logging.error("Abridgment process failed. Check logs for details.")
            sys.exit(1)
        elif not abridged_text:
             logging.error("Abridgment resulted in empty text. Cannot build EPUB.")
             sys.exit(1) # Exit if the summary is empty
        else:
             logging.info(f"Abridgment successful. Final text length: {len(abridged_text)} characters.")
    except Exception as e:
        logging.error(f"An unexpected error occurred during abridgment: {e}", exc_info=True)
        sys.exit(1)


    # 6. Build Output EPUB
    logging.info(f"Building output EPUB file at: {args.output_epub}")
    try:
        success = build_epub(
            abridged_content=abridged_text or "", # Ensure it's not None
            original_metadata=metadata,
            output_path=args.output_epub
        )
        if not success:
            logging.error("Failed to build the output EPUB file.")
            sys.exit(1)
        logging.info("Output EPUB built successfully.")
    except Exception as e:
        logging.error(f"An unexpected error occurred during EPUB building: {e}", exc_info=True)
        sys.exit(1)

    logging.info("Ebook abridgment process completed successfully!")
    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Abridge an EPUB file using an LLM.")

    parser.add_argument("input_epub", help="Path to the input EPUB file.")
    parser.add_argument("output_epub", help="Path to save the abridged EPUB file.")

    parser.add_argument(
        "-p", "--provider",
        choices=["google", "ollama", "openrouter"], # Add openrouter
        required=True,
        help="The LLM provider to use."
    )
    parser.add_argument(
        "-m", "--model",
        type=str,
        default=None, # Use provider's default if not specified
        help="The specific LLM model name (e.g., 'gemini-1.5-pro', 'llama3'). Uses provider default if omitted."
    )
    parser.add_argument(
        "-t", "--temperature",
        type=float,
        default=0.3,
        help="Sampling temperature for the LLM (default: 0.3)."
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Automatically confirm and proceed without asking after cost estimation."
    )

    # Example command:
    # python main.py "path/to/book.epub" "path/to/abridged_book.epub" -p ollama -m llama3
    # python main.py "path/to/book.epub" "path/to/abridged_book.epub" -p google -m gemini-1.5-pro -y

    args = parser.parse_args()
    main(args)