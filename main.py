import argparse
import logging
import os
import sys
import json
from typing import Optional, List, Dict, Tuple

import ebooklib  # Need to import ebooklib to read the original book
from config_loader import load_config
from epub_parser import parse_epub
from cost_estimator import estimate_abridgment_cost
from summarizer import SummarizationEngine
from epub_builder import build_epub
from llm_config import get_default_model

# Load application config for summary lengths
CONFIG = load_config(os.path.join(os.path.dirname(__file__), 'config.yaml'))
SUMMARY_LENGTH_KEYS = list(CONFIG.get('chapter_summary_lengths', {}).keys())
DEFAULT_SUMMARY_LENGTH = CONFIG.get('default_chapter_summary_length')

# Configure logging
logging.basicConfig(
    filename='abridger_engine.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(module)s] %(message)s',
    force=True
)


def confirm_proceed(args, estimated_tokens: Dict[str, int], estimated_cost: float) -> bool:
    """Asks the user for confirmation after showing estimates."""
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
        print("Note: Estimated cost is $0.00 (likely using a local model).")
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
        except EOFError:
            logging.warning("EOF received while waiting for confirmation. Aborting.")
            return False


def main(args):
    logging.info(f"Starting ebook abridgment process for: {args.input_epub}")
    model_name = args.model or get_default_model(args.provider)
    logging.info(f"LLM Provider: {args.provider}, Model: {model_name}{' (Default)' if not args.model else ''}")

    # 1. Parse EPUB
    logging.info("Parsing EPUB file...")
    try:
        chapters, metadata = parse_epub(args.input_epub)
        if not chapters:
            logging.error("Failed to parse any chapters from the EPUB. Exiting.")
            sys.exit(1)
        logging.info(f"Parsed {len(chapters)} chapters from '{metadata.get('title', 'Unknown Title')}'.")
    except FileNotFoundError:
        logging.error(f"Input EPUB file not found: {args.input_epub}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error during EPUB parsing: {e}", exc_info=True)
        sys.exit(1)

    # 2. Estimate Cost & Tokens
    logging.info("Estimating token usage and cost...")
    try:
        token_estimates, cost_estimate = estimate_abridgment_cost(chapters, model_name)
    except Exception as e:
        logging.error(f"Error during cost estimation: {e}", exc_info=True)
        sys.exit(1)

    # 3. Confirm with User
    if not args.yes:
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
            llm_model_name=args.model,
            temperature=args.temperature,
            short_chapter_word_limit=args.shortchapterwordlimit,
            summary_length_key=args.summary_length
        )
        if not engine.llm:
            logging.error("Failed to initialize LLM. Exiting.")
            sys.exit(1)
    except Exception as e:
        logging.error(f"Error initializing summarization engine: {e}", exc_info=True)
        sys.exit(1)

    # 5. Summarize Chapters
    logging.info("Starting chapter summarization...")
    try:
        chapter_summaries = engine.abridge_documents(chapters)
        if all(s.startswith("[Error summarizing chapter") or not s for s in chapter_summaries):
            logging.error("All chapter summaries failed or were empty. Exiting.")
            sys.exit(1)
        logging.info("Chapter summarization finished.")
    except Exception as e:
        logging.error(f"Error during chapter summarization: {e}", exc_info=True)
        sys.exit(1)

    # 5b. Show summarization stats
    skipped = len(engine.skipped_chapters)
    errors = len(engine.error_chapters)
    print(f"\nSummarization Stats: Skipped {skipped} short chapters, {errors} errors.")
    logging.info(f"Summarization Stats: skipped={skipped}, errors={errors}")

    # 6. Overall Book Summary
    logging.info("Generating overall book summary...")
    try:
        overall_summary = engine.summarize_book_overall(chapter_summaries)
        if not overall_summary:
            logging.warning("No overall summary generated; proceeding without it.")
    except Exception as e:
        logging.error(f"Error during overall summary: {e}", exc_info=True)
        overall_summary = ""

    # 7. Build Output EPUB
    logging.info("Building output EPUB...")
    try:
        success = build_epub(
            chapter_summaries=chapter_summaries,
            overall_summary=overall_summary,
            parsed_docs=chapters,
            original_book=ebooklib.epub.read_epub(args.input_epub),
            epub_metadata=metadata,
            output_path=args.output_epub
        )
        if not success:
            logging.error("Failed to build output EPUB.")
            sys.exit(1)
        logging.info("Output EPUB built successfully.")
    except Exception as e:
        logging.error(f"Error during EPUB building: {e}", exc_info=True)
        sys.exit(1)

    logging.info("Ebook abridgment completed successfully!")
    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Abridge an EPUB file using an LLM.")

    parser.add_argument("input_epub", help="Path to the input EPUB file.")
    parser.add_argument("output_epub", help="Path to save the abridged EPUB file.")
    parser.add_argument(
        "-p", "--provider",
        choices=["google", "ollama", "openrouter"],
        required=True,
        help="The LLM provider to use."
    )
    parser.add_argument(
        "-m", "--model",
        type=str,
        default=None,
        help="Specific LLM model name. Uses default if omitted."
    )
    parser.add_argument(
        "-t", "--temperature",
        type=float,
        default=0.3,
        help="Sampling temperature for the LLM (default: 0.3)."
    )
    parser.add_argument(
        "-w", "--shortchapterwordlimit",
        type=int,
        default=150,
        help="Word limit below which chapters are passed through."
    )
    parser.add_argument(
        "-l", "--summary-length",
        choices=SUMMARY_LENGTH_KEYS,
        default=DEFAULT_SUMMARY_LENGTH,
        help="Chapter summary length key (from config.yaml)."
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation after cost estimation."
    )

    args = parser.parse_args()
    main(args)
