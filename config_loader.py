import os
import json
import yaml
from dotenv import load_dotenv

# Load .env for sensitive API keys
load_dotenv()

def load_env():
    return {
        "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY"),
        "OPENROUTER_API_KEY": os.getenv("OPENROUTER_API_KEY"),
        "OPENAI_API_BASE": os.getenv("OPENAI_API_BASE"),
        "OLLAMA_BASE_URL": os.getenv("OLLAMA_BASE_URL")
    }

def load_config(file_path: str = "config.yaml"):
    with open(file_path, 'r') as file:
        if file_path.endswith(".yaml") or file_path.endswith(".yml"):
            return yaml.safe_load(file)
        elif file_path.endswith(".json"):
            return json.load(file)
        else:
            raise ValueError("Unsupported config file type. Use .yaml or .json")
