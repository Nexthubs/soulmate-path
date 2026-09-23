import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional
from app.quiz.constants import CANONICAL_QUIZ_VERSION, DEFAULT_CONFIG_PATH
from app.quiz.schema import QuizConfig
from app.quiz.validator import QuizValidationError, validate_quiz_config


def load_quiz_config(path: Optional[Path] = None) -> QuizConfig:
    """
    Load, parse, and validate canonical quiz configuration from disk.
    Raises FileNotFoundError, ValidationError, or QuizValidationError on failure.
    """
    target_path = path or DEFAULT_CONFIG_PATH
    if not target_path.exists():
        raise FileNotFoundError(f"Quiz configuration file not found at: {target_path}")

    with open(target_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    config = QuizConfig.model_validate(data)
    if config.version != CANONICAL_QUIZ_VERSION:
        raise QuizValidationError(
            f"Expected version '{CANONICAL_QUIZ_VERSION}', got '{config.version}'"
        )

    validate_quiz_config(config)
    return config


@lru_cache(maxsize=4)
def get_cached_quiz_config() -> QuizConfig:
    """Return in-memory cached copy of validated canonical quiz config."""
    return load_quiz_config()
