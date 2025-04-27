import os, json, yaml
from dotenv import load_dotenv

load_dotenv()  # still pick up .env

# Calculate project root once
_PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
_DEFAULT_CFG  = os.path.join(_PROJECT_ROOT, "config.yaml")

def load_env():
    return {
        "GOOGLE_API_KEY":    os.getenv("GOOGLE_API_KEY"),
        "OPENROUTER_API_KEY":os.getenv("OPENROUTER_API_KEY"),
        "OPENAI_API_BASE":   os.getenv("OPENAI_API_BASE"),
        "OLLAMA_BASE_URL":   os.getenv("OLLAMA_BASE_URL"),
    }

def load_config(file_path: str | None = None):
    """
    Load YAML or JSON config. If no path is given, default to
    project_root/config.yaml.
    """
    path = file_path or _DEFAULT_CFG
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found at {path}")
    with open(path, "r") as f:
        if path.endswith((".yaml", ".yml")):
            return yaml.safe_load(f)
        elif path.endswith(".json"):
            return json.load(f)
        else:
            raise ValueError("Unsupported config type (must be .yaml/.json)")
