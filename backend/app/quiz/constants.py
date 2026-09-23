"""
Constants for Soulmate Quiz Engine (Spec §4.5–4.6, Decisions: QUIZ-01).
"""
from pathlib import Path

CANONICAL_QUIZ_VERSION = "soulmate-quiz-v1"

# Root relative path to canonical JSON
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "quiz" / f"{CANONICAL_QUIZ_VERSION}.json"
