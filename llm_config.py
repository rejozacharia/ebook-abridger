import os
import logging
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.llms import Ollama # Use LLM wrapper for Ollama

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables from .env file
# Explicitly load .env file from the same directory as this script
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
    logging.info(f"Loaded environment variables from: {dotenv_path}")
else:
    logging.warning(f".env file not found at expected location: {dotenv_path}. API keys might be missing.")
    # Attempt default load_dotenv() as a fallback, might find it elsewhere
    load_dotenv()

# --- Constants ---
DEFAULT_TEMPERATURE = 0.3 # Lower temperature for more deterministic summaries

# --- Model Configuration Parsing ---

# Store parsed models to avoid re-parsing every time
_MODEL_CONFIG = {}

def _parse_models_from_env(env_var_name: str):
    """Parses model list and default from an environment variable."""
    models_str = os.getenv(env_var_name, "")
    if not models_str:
        return [], None # Return empty list and no default if var is not set

    models = [m.strip() for m in models_str.split(',')]
    default_model = None
    cleaned_models = []

    for model in models:
        if model.endswith('*'):
            model_name = model[:-1]
            if not default_model: # Take the first one marked as default
                 default_model = model_name
            cleaned_models.append(model_name)
        else:
            cleaned_models.append(model)

    if not default_model and cleaned_models:
         default_model = cleaned_models[0] # Fallback: use the first model if none is marked

    return cleaned_models, default_model

def _load_model_config():
    """Loads model configurations for all providers from environment variables."""
    global _MODEL_CONFIG
    if not _MODEL_CONFIG: # Load only once
        google_models, google_default = _parse_models_from_env("GOOGLE_MODELS")
        ollama_models, ollama_default = _parse_models_from_env("OLLAMA_MODELS")

        _MODEL_CONFIG = {
            "google": {"models": google_models, "default": google_default},
            "ollama": {"models": ollama_models, "default": ollama_default},
        }
        # Add fallback defaults if parsing failed but provider is known
        if not _MODEL_CONFIG["google"]["default"]:
             _MODEL_CONFIG["google"]["default"] = "gemini-1.5-flash" # Hardcoded fallback
             logging.warning("No default Google model found in .env, using 'gemini-1.5-flash'.")
        if not _MODEL_CONFIG["ollama"]["default"]:
             _MODEL_CONFIG["ollama"]["default"] = "llama3" # Hardcoded fallback
             logging.warning("No default Ollama model found in .env, using 'llama3'.")


# Load config when module is imported
_load_model_config()

def get_available_models(provider: str) -> list[str]:
    """Returns the list of available models for a given provider."""
    provider = provider.lower()
    return _MODEL_CONFIG.get(provider, {}).get("models", [])

def get_default_model(provider: str) -> str | None:
    """Returns the default model name for a given provider."""
    provider = provider.lower()
    return _MODEL_CONFIG.get(provider, {}).get("default")


# --- LLM Initialization ---

def get_google_genai_llm(model_name: str, temperature: float = DEFAULT_TEMPERATURE):
    """
    Initializes and returns a LangChain ChatGoogleGenerativeAI LLM instance.

    Args:
        model_name: The specific Gemini model to use (e.g., "gemini-1.5-pro", "gemini-1.5-flash").
        temperature: The sampling temperature for the model.

    Returns:
        An initialized ChatGoogleGenerativeAI instance, or None if API key is missing.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key or api_key == "YOUR_GOOGLE_API_KEY_HERE":
        logging.error("GOOGLE_API_KEY not found or not set in .env file. Cannot initialize Gemini LLM.")
        return None
    
    try:
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=temperature,
            convert_system_message_to_human=True # Often needed for Gemini compatibility
        )
        logging.info(f"Initialized Google GenAI LLM with model: {model_name}")
        return llm
    except Exception as e:
        logging.error(f"Failed to initialize Google GenAI LLM ({model_name}): {e}", exc_info=True)
        return None

def get_ollama_llm(model_name: str, temperature: float = DEFAULT_TEMPERATURE):
    """
    Initializes and returns a LangChain Ollama LLM instance.

    Args:
        model_name: The specific Ollama model to use (e.g., "llama3", "llama4-scout").
        temperature: The sampling temperature for the model.

    Returns:
        An initialized Ollama instance, or None if Ollama service is unavailable.
    """
    base_url = os.getenv("OLLAMA_BASE_URL") # Optional override from .env
    
    try:
        llm_params = {
            "model": model_name,
            "temperature": temperature,
        }
        if base_url:
            llm_params["base_url"] = base_url
            logging.info(f"Using Ollama base URL: {base_url}")
            
        llm = Ollama(**llm_params)
        
        # Optional: Add a quick check to see if the Ollama service is reachable
        # Note: This might slow down initialization slightly.
        # try:
        #     llm.invoke("Hi") # Simple test prompt
        # except Exception as check_err:
        #     logging.error(f"Ollama service check failed for model '{model_name}': {check_err}")
        #     raise ConnectionError(f"Could not connect to Ollama service for model '{model_name}'. Is it running?") from check_err

        logging.info(f"Initialized Ollama LLM with model: {model_name}")
        return llm
    except Exception as e:
        logging.error(f"Failed to initialize Ollama LLM ({model_name}): {e}", exc_info=True)
        # Re-raise specific error if connection failed during check
        if isinstance(e, ConnectionError):
             raise
        return None

# --- Helper Function ---
def get_llm_instance(provider: str, model_name: str = None, temperature: float = DEFAULT_TEMPERATURE):
    """
    Gets an initialized LLM instance based on the provider name.

    Args:
        provider: The LLM provider ("google", "ollama").
        model_name: The specific model name. If None, uses the default for the provider.
        temperature: The sampling temperature.

    Returns:
        An initialized LangChain LLM instance, or None if initialization fails.
    """
    provider = provider.lower()
    # Use specified model or get the default from config
    target_model = model_name or get_default_model(provider)

    if not target_model:
         logging.error(f"No model specified and no default found for provider '{provider}'.")
         return None

    if provider == "google":
        return get_google_genai_llm(model_name=target_model, temperature=temperature)
    elif provider == "ollama":
        return get_ollama_llm(model_name=target_model, temperature=temperature)
    else:
        logging.error(f"Unsupported LLM provider: {provider}")
        return None

# Example usage (for testing purposes)
if __name__ == '__main__':
    print("\n--- LLM Configuration Test ---")

    print("\n--- Testing Model Configuration ---")
    print(f"Google Models: {get_available_models('google')}")
    print(f"Google Default: {get_default_model('google')}")
    print(f"Ollama Models: {get_available_models('ollama')}")
    print(f"Ollama Default: {get_default_model('ollama')}")

    print("\n--- Testing LLM Initialization (using defaults from .env) ---")
    print("\nTesting Google Gemini LLM (default):")
    default_google_model = get_default_model('google')
    if default_google_model:
        gemini_llm = get_llm_instance("google") # Uses default
        if gemini_llm:
            print(f"  Successfully initialized Default Google LLM ({default_google_model}): {type(gemini_llm)}")
        else:
            print(f"  Failed to initialize Default Google LLM ({default_google_model}). Check GOOGLE_API_KEY in .env")
    else:
         print("  No default Google model configured in .env")


    print("\nTesting Ollama LLM (default):")
    default_ollama_model = get_default_model('ollama')
    if default_ollama_model:
        ollama_llm = get_llm_instance("ollama") # Uses default
        if ollama_llm:
            print(f"  Successfully initialized Default Ollama LLM ({default_ollama_model}): {type(ollama_llm)}")
            print(f"  Model name reported by instance: {ollama_llm.model}")
        else:
            print(f"  Failed to initialize Default Ollama LLM ({default_ollama_model}). Is Ollama service running?")
    else:
         print("  No default Ollama model configured in .env")


    print("\n--- Testing with specific model names from .env (if available) ---")
    google_models_list = get_available_models('google')
    if len(google_models_list) > 1:
         specific_google = google_models_list[1] # Try second model in the list
         print(f"\nTesting specific Google model: {specific_google}")
         gemini_specific = get_llm_instance("google", model_name=specific_google)
         if gemini_specific:
              print(f"  Successfully initialized specific Google model: {specific_google}")
         else:
              print(f"  Failed to initialize specific Google model: {specific_google}")

    ollama_models_list = get_available_models('ollama')
    if len(ollama_models_list) > 1:
         specific_ollama = ollama_models_list[1] # Try second model in the list
         print(f"\nTesting specific Ollama model: {specific_ollama}")
         ollama_specific = get_llm_instance("ollama", model_name=specific_ollama)
         if ollama_specific:
              print(f"  Successfully initialized specific Ollama model: {ollama_specific.model}")
         else:
              print(f"  Failed to initialize specific Ollama model: {specific_ollama}")