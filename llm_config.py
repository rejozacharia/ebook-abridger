import os
import logging
from dotenv import load_dotenv
from pydantic import Field, SecretStr

# --- External LLM clients ---
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.llms import Ollama
from langchain_openai import ChatOpenAI
from langchain_core.utils.utils import secret_from_env

# --- Logging setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Load .env ---
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
    logging.info(f"Loaded environment variables from: {dotenv_path}")
else:
    logging.warning(f".env file not found at expected location: {dotenv_path}.")
    load_dotenv()

# --- Constants ---
DEFAULT_TEMPERATURE = 0.3

# --- OpenRouter subclass of ChatOpenAI ---
class ChatOpenRouter(ChatOpenAI):
    """
    Treat OpenRouter.ai as an OpenAI-compatible endpoint.
    Reads OPENROUTER_API_KEY and OPENAI_API_BASE from env.
    """
    openai_api_key: SecretStr = Field(
        alias="api_key",
        default_factory=secret_from_env("OPENROUTER_API_KEY", default=None),
    )

    @property
    def lc_secrets(self) -> dict[str, str]:
        # ensure the secret is mapped correctly for runtime
        return {"openai_api_key": "OPENROUTER_API_KEY"}


# --- Model config parsing ---
_MODEL_CONFIG: dict[str, dict[str, list[str] | str | None]] = {}

def _parse_models_from_env(env_var_name: str) -> tuple[list[str], str | None]:
    models_str = os.getenv(env_var_name, "")
    if not models_str:
        return [], None

    models = []
    default = None
    for token in models_str.split(','):
        m = token.strip()
        if m.endswith('*'):
            name = m[:-1]
            default = default or name
            models.append(name)
        else:
            models.append(m)
    if not default and models:
        default = models[0]
    return models, default

def _load_model_config() -> None:
    global _MODEL_CONFIG
    if _MODEL_CONFIG:
        return

    google_models, google_def = _parse_models_from_env("GOOGLE_MODELS")
    ollama_models, ollama_def = _parse_models_from_env("OLLAMA_MODELS")
    openr_models, openr_def = _parse_models_from_env("OPENROUTER_MODELS")

    _MODEL_CONFIG = {
        "google":  {"models": google_models,   "default": google_def},
        "ollama":  {"models": ollama_models,   "default": ollama_def},
        "openrouter": {"models": openr_models,  "default": openr_def},
    }

    # Fallback defaults
    if not _MODEL_CONFIG["google"]["default"]:
        _MODEL_CONFIG["google"]["default"] = "gemini-1.5-flash"
        logging.warning("No default Google model in .env; using 'gemini-1.5-flash'.")
    if not _MODEL_CONFIG["ollama"]["default"]:
        _MODEL_CONFIG["ollama"]["default"] = "llama3"
        logging.warning("No default Ollama model in .env; using 'llama3'.")
    if not _MODEL_CONFIG["openrouter"]["default"]:
        _MODEL_CONFIG["openrouter"]["default"] = "mistralai/mistral-7b-instruct"
        logging.warning("No default OpenRouter model in .env; using 'mistralai/mistral-7b-instruct'.")

# populate on import
_load_model_config()

def get_available_models(provider: str) -> list[str]:
    return _MODEL_CONFIG.get(provider.lower(), {}).get("models", [])

def get_default_model(provider: str) -> str | None:
    return _MODEL_CONFIG.get(provider.lower(), {}).get("default")


# --- LLM factories ---

def get_google_genai_llm(model_name: str, temperature: float = DEFAULT_TEMPERATURE):
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logging.error("GOOGLE_API_KEY missing; cannot init Gemini.")
        return None
    try:
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=temperature,
            convert_system_message_to_human=True
        )
        logging.info(f"Initialized Google GenAI LLM: {model_name}")
        return llm
    except Exception as e:
        logging.error(f"Google GenAI init error ({model_name}): {e}", exc_info=True)
        return None

def get_ollama_llm(model_name: str, temperature: float = DEFAULT_TEMPERATURE):
    params = {"model": model_name, "temperature": temperature}
    base = os.getenv("OLLAMA_BASE_URL")
    if base:
        params["base_url"] = base
        logging.info(f"Ollama base URL override: {base}")
    try:
        llm = Ollama(**params)
        logging.info(f"Initialized Ollama LLM: {model_name}")
        return llm
    except Exception as e:
        logging.error(f"Ollama init error ({model_name}): {e}", exc_info=True)
        return None

def get_openrouter_llm(model_name: str, temperature: float = DEFAULT_TEMPERATURE):
    """
    Uses our ChatOpenRouter subclass to target OpenRouter.ai.
    Requires in .env:
      OPENROUTER_API_KEY=<your key>
      OPENAI_API_BASE=https://openrouter.ai/api/v1
    """
    api_base = os.getenv("OPENAI_API_BASE")
    if not os.getenv("OPENROUTER_API_KEY"):
        logging.error("OPENROUTER_API_KEY missing; cannot init OpenRouter LLM.")
        return None
    try:
        llm = ChatOpenRouter(
            model_name,
            temperature=temperature,
            openai_api_base=api_base  # passed through ChatOpenAI base
        )
        logging.info(f"Initialized OpenRouter LLM: {model_name}")
        return llm
    except Exception as e:
        logging.error(f"OpenRouter init error ({model_name}): {e}", exc_info=True)
        return None

def get_llm_instance(provider: str, model_name: str = None, temperature: float = DEFAULT_TEMPERATURE):
    """
    Return an initialized LLM for 'google', 'ollama', or 'openrouter'.
    """
    prov = provider.lower()
    model = model_name or get_default_model(prov)
    if not model:
        logging.error(f"No model given or default for provider '{prov}'.")
        return None

    if prov == "google":
        return get_google_genai_llm(model, temperature)
    elif prov == "ollama":
        return get_ollama_llm(model, temperature)
    elif prov == "openrouter":
        return get_openrouter_llm(model, temperature)
    else:
        logging.error(f"Unsupported provider: {provider}")
        return None
