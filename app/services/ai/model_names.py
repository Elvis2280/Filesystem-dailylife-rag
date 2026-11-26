"""Helpers for comparing Ollama model names and optional tags."""


def normalize_model_name(name: str) -> str:
    """Add Ollama's implicit ``latest`` tag while preserving explicit tags."""
    namespace, separator, model = name.rpartition("/")
    prefix = f"{namespace}/" if separator else ""
    if ":" not in model:
        model = f"{model}:latest"
    return f"{prefix}{model}"


def model_is_available(model_name: str, available_models: set[str]) -> bool:
    """Check model availability, treating an omitted tag as ``latest``."""
    normalized = normalize_model_name(model_name)
    return any(normalize_model_name(name) == normalized for name in available_models)
