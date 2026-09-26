"""
Versioned Sketch prompt template registry (DEV-SPEC §11.2–11.3, §12; Decisions: PROMPT-01).

Owns everything between the normalized profile and the image provider:
- loads the versioned prompt template from config/prompts/soulmate-sketch/<version>.txt;
- enforces the §12 placeholder whitelist ({gender}, {age_range}, {ethnicity}, {features});
- maps quiz option codes to provider-ready human-readable values (§11.2);
- renders the final prompt and guarantees no unresolved placeholder survives;
- exposes prompt_name / prompt_version / template sha256 / model / inputs metadata
  that the generation service must persist with the generated asset (§11.3).

The prompt text is migrated verbatim from the PRD "Soulmate Pencil Portrait Prompt".
Decision PROMPT-01 stays OPEN: Q7 (`key_soulmate_quality`) is passed into `features`
unchanged; no reinterpretation happens here.
"""

import hashlib
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.core.config import settings
from app.core.errors import ValidationError
from app.quiz.loader import get_cached_quiz_config
from app.quiz.schema import QuizConfig
from app.soulmate.domain.profile import SoulmateProfileV1

# DEV-SPEC §11.3
SKETCH_PROMPT_NAME = "soulmate_pencil_portrait"

# DEV-SPEC §12: the only template variables allowed in a sketch prompt template.
ALLOWED_SKETCH_PROMPT_VARIABLES = frozenset({"gender", "age_range", "ethnicity", "features"})

# Prompt variable -> quiz question it is fed from (DEV-SPEC §11.2, Decisions: PROMPT-01, QUIZ-01).
# gender comes from Q03 (preferred_partner_gender), never Q02 (user_gender).
PROMPT_VARIABLE_TO_QUESTION: Dict[str, str] = {
    "gender": "q03",
    "age_range": "q05",
    "ethnicity": "q06",
    "features": "q07",
}

# Option code -> provider-ready human-readable value (DEV-SPEC §11.2 "option code →
# 人类可读值映射"). Values are the canonical quiz labels without UI emoji decoration,
# matching the §11.2 example ("male", "30-40", "Asian", "Kindness").
SKETCH_INPUT_OPTION_LABELS: Dict[str, Dict[str, str]] = {
    "q03": {
        "male": "male",
        "female": "female",
    },
    "q05": {
        "age_20_30": "20-30",
        "age_30_40": "30-40",
        "age_40_50": "40-50",
        "age_50_plus": "50+",
    },
    "q06": {
        "caucasian_white": "Caucasian/White",
        "hispanic_latino": "Hispanic/Latino",
        "african_african_american": "African/African-American",
        "asian": "Asian",
        "no_preference": "No preference",
    },
    "q07": {
        "kindness": "Kindness",
        "loyalty": "Loyalty",
        "intelligence": "Intelligence",
        "creativity": "Creativity",
        "passion": "Passion",
        "empathy": "Empathy",
    },
}

_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")
_VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

# Repository layout: backend/app/soulmate/domain/sketch_prompt.py -> repo root is parents[4].
SKETCH_PROMPTS_DIR = Path(__file__).resolve().parents[4] / "config" / "prompts"


class SketchPromptError(ValidationError):
    """Raised when sketch prompt template loading, input mapping, or rendering fails."""


class SketchPromptTemplateError(SketchPromptError):
    """Raised when a prompt template is missing or violates the §12 variable contract."""


class SketchPromptInputError(SketchPromptError):
    """Raised when profile answers cannot be mapped to provider-ready prompt inputs."""


def sketch_prompt_template_path(version: str) -> Path:
    """Resolves the template file path for a prompt version (DEV-SPEC §12)."""
    if not _VERSION_RE.match(version or ""):
        raise SketchPromptTemplateError(
            f"Invalid sketch prompt version '{version}'.",
            details={"version": version},
        )
    return SKETCH_PROMPTS_DIR / "soulmate-sketch" / f"{version}.txt"


class SketchPromptTemplate(BaseModel):
    """A loaded, validated prompt template snapshot with content hash (DEV-SPEC §11.3, §12)."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    text: str

    @property
    def placeholders(self) -> frozenset:
        return frozenset(_PLACEHOLDER_RE.findall(self.text))

    @property
    def sha256(self) -> str:
        """Prompt version hash of the template content (DEV-SPEC §12)."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def _validate_placeholder_contract(self) -> "SketchPromptTemplate":
        if "{{" in self.text or "}}" in self.text:
            raise SketchPromptTemplateError(
                "Sketch prompt template contains PRD-style '{{...}}' delimiters; "
                "only single-brace §12 variables are allowed.",
                details={"version": self.version},
            )
        found = set(self.placeholders)
        unknown = found - ALLOWED_SKETCH_PROMPT_VARIABLES
        if unknown:
            raise SketchPromptTemplateError(
                f"Sketch prompt template uses disallowed placeholders: {sorted(unknown)}.",
                details={
                    "version": self.version,
                    "disallowed": sorted(unknown),
                    "allowed": sorted(ALLOWED_SKETCH_PROMPT_VARIABLES),
                },
            )
        missing = ALLOWED_SKETCH_PROMPT_VARIABLES - found
        if missing:
            raise SketchPromptTemplateError(
                f"Sketch prompt template is missing required placeholders: {sorted(missing)}.",
                details={
                    "version": self.version,
                    "missing": sorted(missing),
                },
            )
        residual = self.text
        for var in found:
            residual = residual.replace("{" + var + "}", "")
        if "{" in residual or "}" in residual:
            raise SketchPromptTemplateError(
                "Sketch prompt template contains braces outside the allowed §12 variables.",
                details={"version": self.version},
            )
        return self


class SketchPromptInputs(BaseModel):
    """
    Explicit, provider-ready sketch prompt inputs (DEV-SPEC §11.2, §12).

    extra="forbid" makes the input set exactly the four §12 variables — no client- or
    caller-supplied extra prompt material can enter the provider request.
    """

    model_config = ConfigDict(extra="forbid")

    gender: str
    age_range: str
    ethnicity: str
    features: str

    @field_validator("gender", "age_range", "ethnicity", "features", mode="after")
    @classmethod
    def _clean_value(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise SketchPromptInputError(
                "Sketch prompt inputs must be non-empty; an empty value would leave "
                "a placeholder unresolved at the provider.",
                details={"invalid_value": v},
            )
        if "{" in cleaned or "}" in cleaned:
            raise SketchPromptInputError(
                "Sketch prompt inputs must not contain brace characters.",
                details={"invalid_value": v},
            )
        return cleaned


class RenderedSketchPrompt(BaseModel):
    """A fully rendered prompt plus the §11.3 metadata that must be stored with the asset."""

    model_config = ConfigDict(frozen=True)

    prompt_name: str
    prompt_version: str
    template_sha256: str
    model: str
    rendered_text: str
    inputs: SketchPromptInputs

    def artifact_column_values(self) -> Dict[str, Any]:
        """
        Values for the matching SoulmateArtifact columns (DEV-SPEC §11.3).

        The generation service (SP-603) must persist these onto the artifact row
        when generation runs so the prompt version is stored with the generated asset.
        """
        return {
            "prompt_version": self.prompt_version,
            "model": self.model,
            "input_json": self.inputs.model_dump(),
        }


def map_sketch_option_to_readable(question_code: str, code: str) -> str:
    """
    Maps a single quiz option code to its provider-ready human-readable value.

    Raises SketchPromptInputError on any code without an explicit mapping — raw option
    codes or unknown values must never reach the provider (DEV-SPEC §12).
    """
    table = SKETCH_INPUT_OPTION_LABELS.get(question_code)
    if table is None:
        raise SketchPromptInputError(
            f"No sketch input mapping registered for question '{question_code}'.",
            details={"question_code": question_code},
        )
    if not isinstance(code, str) or not code.strip():
        raise SketchPromptInputError(
            f"Sketch input for question '{question_code}' is empty or not a string.",
            details={"question_code": question_code, "invalid_value": code},
        )
    cleaned = code.strip()
    if cleaned not in table:
        raise SketchPromptInputError(
            f"Option '{cleaned}' has no human-readable sketch mapping for question '{question_code}'.",
            details={
                "question_code": question_code,
                "invalid_value": cleaned,
                "allowed_options": sorted(table),
            },
        )
    return table[cleaned]


def validate_sketch_input_mapping_coverage(quiz_config: Optional[QuizConfig] = None) -> None:
    """
    Guards the mapping table against drift from the canonical quiz config: the table
    must cover exactly the options defined for q03/q05/q06/q07, so a config change can
    never silently drop or invent a sketch input value.
    """
    config = quiz_config or get_cached_quiz_config()
    questions = {q.code: q for q in config.questions}
    for question_code, table in SKETCH_INPUT_OPTION_LABELS.items():
        question = questions.get(question_code)
        if question is None or not question.options:
            raise SketchPromptInputError(
                f"Quiz config '{config.version}' defines no options for mapped question '{question_code}'.",
                details={"question_code": question_code, "quiz_version": config.version},
            )
        config_codes = {opt.code for opt in question.options}
        table_codes = set(table)
        if table_codes != config_codes:
            raise SketchPromptInputError(
                f"Sketch input mapping for '{question_code}' is out of sync with quiz config "
                f"'{config.version}': missing_in_mapping={sorted(config_codes - table_codes)}, "
                f"unknown_in_mapping={sorted(table_codes - config_codes)}.",
                details={
                    "question_code": question_code,
                    "missing_in_mapping": sorted(config_codes - table_codes),
                    "unknown_in_mapping": sorted(table_codes - config_codes),
                },
            )


def build_sketch_prompt_inputs(
    profile: SoulmateProfileV1,
    quiz_config: Optional[QuizConfig] = None,
) -> SketchPromptInputs:
    """
    Maps a normalized profile into explicit sketch prompt inputs (DEV-SPEC §11.2).

    gender strictly comes from preferred_partner_gender (Q03) via profile.to_sketch_input()
    (Decisions: QUIZ-01); features is key_soulmate_quality (Q07) unchanged (Decision
    PROMPT-01 — OPEN, must not be silently reinterpreted).
    """
    config = quiz_config or get_cached_quiz_config()
    validate_sketch_input_mapping_coverage(config)

    codes = profile.to_sketch_input()
    mapped: Dict[str, str] = {}
    for variable, question_code in PROMPT_VARIABLE_TO_QUESTION.items():
        code = codes.get(variable)
        if code is None:
            raise SketchPromptInputError(
                f"Normalized sketch input '{variable}' (from '{question_code}') is missing.",
                details={"variable": variable, "question_code": question_code},
            )
        mapped[variable] = map_sketch_option_to_readable(question_code, code)
    return SketchPromptInputs(**mapped)


@lru_cache(maxsize=8)
def _load_template_cached(version: str) -> SketchPromptTemplate:
    path = sketch_prompt_template_path(version)
    if not path.exists():
        raise SketchPromptTemplateError(
            f"Sketch prompt template for version '{version}' not found at '{path}'.",
            details={"version": version, "path": str(path)},
        )
    text = path.read_text(encoding="utf-8")
    return SketchPromptTemplate(name=SKETCH_PROMPT_NAME, version=version, text=text)


def load_sketch_prompt_template(version: Optional[str] = None) -> SketchPromptTemplate:
    """Loads (and caches) the versioned prompt template; version defaults to config."""
    resolved = version or settings.soulmate_sketch_prompt_version
    return _load_template_cached(resolved)


def invalidate_sketch_prompt_template_cache() -> None:
    """Clears the in-memory template cache (used by tests after config changes)."""
    _load_template_cached.cache_clear()


def render_sketch_prompt(
    inputs: SketchPromptInputs,
    template: Optional[SketchPromptTemplate] = None,
    version: Optional[str] = None,
) -> RenderedSketchPrompt:
    """
    Renders the final provider-ready prompt (DEV-SPEC §12).

    Guarantees before returning:
    - all four §12 variables were substituted (inputs are non-empty by model contract);
    - no unresolved placeholder or stray brace survives in the rendered text.
    Client-submitted prompt text is structurally impossible: this API only accepts
    profile-derived inputs against a server-owned template.
    """
    tpl = template or load_sketch_prompt_template(version)
    try:
        rendered = tpl.text.format(**inputs.model_dump())
    except (KeyError, IndexError, ValueError) as exc:
        # Only reachable with a template that bypassed validation (e.g. model_construct);
        # any failure to fully resolve must surface as a prompt-contract error, never a
        # raw format exception or a partially resolved prompt.
        raise SketchPromptTemplateError(
            f"Failed to resolve sketch prompt template '{tpl.version}' against the four "
            f"§12 variables: {exc}.",
            details={"version": tpl.version},
        ) from exc
    if "{" in rendered or "}" in rendered:
        raise SketchPromptTemplateError(
            "Rendered sketch prompt still contains unresolved placeholders; "
            "refusing to return a provider-ready prompt.",
            details={"version": tpl.version},
        )
    return RenderedSketchPrompt(
        prompt_name=tpl.name,
        prompt_version=tpl.version,
        template_sha256=tpl.sha256,
        model=settings.soulmate_image_model,
        rendered_text=rendered,
        inputs=inputs,
    )


def build_rendered_sketch_prompt(
    profile: SoulmateProfileV1,
    quiz_config: Optional[QuizConfig] = None,
    version: Optional[str] = None,
) -> RenderedSketchPrompt:
    """One-call entry: normalized profile -> mapped inputs -> rendered prompt metadata."""
    inputs = build_sketch_prompt_inputs(profile, quiz_config)
    return render_sketch_prompt(inputs, version=version)
