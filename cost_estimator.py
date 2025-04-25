import logging
from typing import List, Dict, Tuple
from langchain_core.documents import Document
from utils import count_tokens # Use absolute import

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Placeholder Pricing ---
# Prices are typically per 1 million tokens (input/output)
# These are illustrative and may not be accurate. Replace with actual pricing.
# Example: Gemini 2.5 Pro might have different pricing tiers.
# Example: Llama 4 (if run locally via Ollama) might have $0 API cost, but compute cost.
LLM_PRICING = {
    "gemini-2.5-pro-exp-03-25": { # Specific experimental model
        "input_cost_per_million_tokens": 0.00, # USD (Free tier)
        "output_cost_per_million_tokens": 0.00  # USD (Free tier)
    },
    "gemini-2.5-pro": { # Hypothetical pricing for standard Gemini 2.5 Pro
        "input_cost_per_million_tokens": 2.00, # USD
        "output_cost_per_million_tokens": 6.00  # USD
    },
    "gpt-4": { # Example pricing
        "input_cost_per_million_tokens": 10.00, # USD
        "output_cost_per_million_tokens": 30.00  # USD
    },
    "llama4-scout": { # Assuming local execution via Ollama
         "input_cost_per_million_tokens": 0.00,
         "output_cost_per_million_tokens": 0.00
    },
    # Add other models as needed
}

# --- Heuristics ---
# Factor to estimate output tokens based on input for the map phase (abridgment target)
MAP_OUTPUT_FACTOR = 0.15 # Estimate 15% length for safety margin over 10% target
# Factor to estimate combine phase tokens based on the *output* of the map phase
COMBINE_FACTOR = 0.5 # Estimate combine phase uses tokens ~50% of the map output size

def get_model_pricing(model_name: str) -> Dict[str, float]:
    """Retrieves pricing information for a given model name."""
    # Try to find the exact model name
    pricing = LLM_PRICING.get(model_name)
    if pricing:
        return pricing
    
    # Basic fallback logic (e.g., if model name includes 'gemini', use gemini pricing)
    logging.warning(f"Exact pricing for model '{model_name}' not found. Attempting fallback.")
    if "gemini" in model_name.lower():
        return LLM_PRICING.get("gemini-2.5-pro", {"input_cost_per_million_tokens": 0, "output_cost_per_million_tokens": 0})
    if "gpt-4" in model_name.lower():
        return LLM_PRICING.get("gpt-4", {"input_cost_per_million_tokens": 0, "output_cost_per_million_tokens": 0})
    if "llama" in model_name.lower(): # Assuming local Ollama Llama models are free
         return LLM_PRICING.get("llama4-scout", {"input_cost_per_million_tokens": 0, "output_cost_per_million_tokens": 0})
    # Check for OpenRouter format (e.g., 'mistralai/mistral-7b-instruct')
    if "/" in model_name:
         logging.info(f"Assuming $0 estimated cost for OpenRouter model '{model_name}'. Actual costs vary.")
         return {"input_cost_per_million_tokens": 0, "output_cost_per_million_tokens": 0}

    logging.warning(f"Could not determine fallback pricing for '{model_name}'. Assuming $0 cost.")
    return {"input_cost_per_million_tokens": 0, "output_cost_per_million_tokens": 0}


def estimate_abridgment_cost(
    chapter_docs: List[Document],
    model_name: str,
    chain_type: str = "map_reduce" # Currently assumes map_reduce logic
) -> Tuple[Dict[str, int], float]:
    """
    Estimates the token usage and cost for abridging a list of chapter documents
    using a specified LLM and chain type (currently assumes map_reduce).

    Args:
        chapter_docs: A list of LangChain Document objects representing the chapters.
        model_name: The name of the LLM to be used (e.g., "gpt-4", "gemini-2.5-pro").
        chain_type: The LangChain summarization chain type (default: "map_reduce").

    Returns:
        A tuple containing:
        - A dictionary with estimated token counts:
            {
                "map_input_tokens": int,
                "map_output_tokens": int,
                "combine_input_tokens": int, # Estimated based on map output
                "combine_output_tokens": int, # Estimated based on combine input
                "total_input_tokens": int,
                "total_output_tokens": int,
                "total_tokens": int
            }
        - The estimated total cost in USD.
    """
    if not chapter_docs:
        return {
            "map_input_tokens": 0, "map_output_tokens": 0,
            "combine_input_tokens": 0, "combine_output_tokens": 0,
            "total_input_tokens": 0, "total_output_tokens": 0, "total_tokens": 0
        }, 0.0

    # --- Token Estimation ---
    map_input_tokens = sum(count_tokens(doc.page_content, model_name) for doc in chapter_docs)
    map_output_tokens = int(map_input_tokens * MAP_OUTPUT_FACTOR)

    # Estimate combine phase tokens (specific to map_reduce)
    if chain_type == "map_reduce":
        # Combine input is roughly the sum of map outputs
        combine_input_tokens = map_output_tokens
        # Combine output is a further reduction, maybe similar ratio to map phase?
        # Let's estimate it as a fraction of the combine input for simplicity.
        combine_output_tokens = int(combine_input_tokens * MAP_OUTPUT_FACTOR)
    elif chain_type == "refine":
        # Refine is harder to estimate - it processes sequentially.
        # Rough guess: Input is original + accumulating summary, output is refined summary.
        # This needs a more complex heuristic, maybe based on chapter count.
        # For now, let's use a simpler placeholder estimate similar to map_reduce.
        logging.warning("Cost estimation for 'refine' chain is less accurate. Using map_reduce heuristic.")
        combine_input_tokens = map_output_tokens # Placeholder
        combine_output_tokens = int(combine_input_tokens * MAP_OUTPUT_FACTOR) # Placeholder
    else: # Stuff, etc.
        logging.warning(f"Cost estimation for chain type '{chain_type}' not fully implemented. Using map_reduce heuristic.")
        combine_input_tokens = map_output_tokens # Placeholder
        combine_output_tokens = int(combine_input_tokens * MAP_OUTPUT_FACTOR) # Placeholder


    total_input_tokens = map_input_tokens + combine_input_tokens
    total_output_tokens = map_output_tokens + combine_output_tokens
    total_tokens = total_input_tokens + total_output_tokens

    token_estimates = {
        "map_input_tokens": map_input_tokens,
        "map_output_tokens": map_output_tokens,
        "combine_input_tokens": combine_input_tokens,
        "combine_output_tokens": combine_output_tokens,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_tokens": total_tokens
    }

    # --- Cost Calculation ---
    pricing = get_model_pricing(model_name)
    input_cost = (total_input_tokens / 1_000_000) * pricing["input_cost_per_million_tokens"]
    output_cost = (total_output_tokens / 1_000_000) * pricing["output_cost_per_million_tokens"]
    total_cost = input_cost + output_cost

    logging.info(f"Estimated Tokens: {total_tokens} (Input: {total_input_tokens}, Output: {total_output_tokens})")
    logging.info(f"Estimated Cost for model '{model_name}': ${total_cost:.4f}")

    return token_estimates, total_cost

# Example usage (for testing purposes)
if __name__ == '__main__':
    # Create dummy documents for testing
    dummy_docs = [
        Document(page_content="This is the first chapter. It's quite short.", metadata={'chapter_number': 1}),
        Document(page_content="This is the second chapter, which is significantly longer and contains more details about the main plot and introduces several key characters.", metadata={'chapter_number': 2}),
        Document(page_content="The third chapter concludes the first arc.", metadata={'chapter_number': 3}),
    ]

    print("\n--- Cost Estimation Test ---")

    models_to_test = ["gemini-2.5-pro", "gpt-4", "llama4-scout", "unknown-model"]

    for model in models_to_test:
        print(f"\nEstimating for model: {model}")
        try:
            token_est, cost_est = estimate_abridgment_cost(dummy_docs, model)
            print(f"  Estimated Tokens:")
            for key, value in token_est.items():
                print(f"    {key}: {value}")
            print(f"  Estimated Cost: ${cost_est:.4f}")
        except Exception as e:
            print(f"  Error estimating cost for {model}: {e}")

    print("\nTesting with empty document list:")
    token_est_empty, cost_est_empty = estimate_abridgment_cost([], "gpt-4")
    print(f"  Estimated Tokens: {token_est_empty}")
    print(f"  Estimated Cost: ${cost_est_empty:.4f}")