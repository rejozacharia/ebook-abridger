import logging
from typing import Optional

from pydantic import Field, SecretStr
from langchain_core.utils.utils import secret_from_env

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.llms import Ollama
from langchain_openai import ChatOpenAI

from core.config_loader import load_env, load_config

# ─── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ─── Load environment variables & config file ─────────────────────────────────
_env    = load_env()         # dict with GOOGLE_API_KEY, OPENROUTER_API_KEY, etc.
_config = load_config()      # dict from project_root/config.yaml

# ─── Pull defaults & models from config.yaml ─────────────────────────────────
_DEFAULTS = _config.get("defaults", {})
_MODELS   = _config.get("models", {})

DEFAULT_TEMPERATURE      = _DEFAULTS.get("temperature", 0.3)
SHORT_CHAPTER_WORD_LIMIT = _DEFAULTS.get("short_chapter_word_limit", 150)
DEFAULT_CHAIN_TYPE       = _DEFAULTS.get("chain_type", "map_reduce")

# ─── Helpers to read model lists & defaults ───────────────────────────────────
def get_available_models(provider: str) -> list[str]:
    return _MODELS.get(provider.lower(), {}).get("available", [])

def get_default_model(provider: str) -> Optional[str]:
    return _MODELS.get(provider.lower(), {}).get("default")

# ─── OpenRouter subclass of ChatOpenAI ────────────────────────────────────────
class ChatOpenRouter(ChatOpenAI):
    openai_api_key: SecretStr = Field(
        alias="api_key",
        default_factory=secret_from_env("OPENROUTER_API_KEY", default=None),
    )

    @property
    def lc_secrets(self) -> dict[str, str]:
        return {"openai_api_key": "OPENROUTER_API_KEY"}

# ─── LLM factory functions ────────────────────────────────────────────────────
def get_google_genai_llm(model_name: str, temperature: float = DEFAULT_TEMPERATURE):
    api_key = _env.get("GOOGLE_API_KEY")
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
    base   = _env.get("OLLAMA_BASE_URL")
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
    api_base = _env.get("OPENAI_API_BASE_URL")
    if not _env.get("OPENROUTER_API_KEY"):
        logging.error("OPENROUTER_API_KEY missing; cannot init OpenRouter LLM.")
        return None
    try:
        llm = ChatOpenRouter(
            model_name,
            temperature=temperature,
            openai_api_base=api_base
        )
        logging.info(f"Initialized OpenRouter LLM: {model_name}")
        return llm
    except Exception as e:
        logging.error(f"OpenRouter init error ({model_name}): {e}", exc_info=True)
        return None

def get_llm_instance(
    provider: str,
    model_name: Optional[str] = None,
    temperature: float = DEFAULT_TEMPERATURE
):
    """
    Return an initialized LLM for 'google', 'ollama', or 'openrouter'.
    Uses config.yaml to supply defaults if model_name is None.
    """
    prov  = provider.lower()
    model = model_name or get_default_model(prov)
    if not model:
        logging.error(f"No model specified or default for provider '{prov}'.")
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
