"""
Tests for the versioned Sketch prompt template (DEV-SPEC §11.2–11.3, §12; SP-601).

Covers:
- template loading, versioning, and content hash;
- §12 placeholder whitelist and completeness (no missing placeholder can reach the provider);
- option code -> human-readable input mapping (q03/q05/q06/q07) incl. drift guard;
- rendered prompt metadata that must be stored with the generated asset;
- PROMPT-01 (Q7 -> features) and QUIZ-01 (Q3 -> gender) are not silently changed.
"""

import re

import pytest

from app.core.config import settings
from app.quiz.loader import get_cached_quiz_config
from app.quiz.schema import QuizConfig
from app.soulmate.domain.profile import build_soulmate_profile
from app.soulmate.domain.sketch_prompt import (
    ALLOWED_SKETCH_PROMPT_VARIABLES,
    SKETCH_PROMPT_NAME,
    RenderedSketchPrompt,
    SketchPromptInputs,
    SketchPromptInputError,
    SketchPromptTemplate,
    SketchPromptTemplateError,
    build_rendered_sketch_prompt,
    build_sketch_prompt_inputs,
    load_sketch_prompt_template,
    map_sketch_option_to_readable,
    render_sketch_prompt,
    validate_sketch_input_mapping_coverage,
)


def _get_valid_answers_dict():
    """Complete valid answers (same fixture style as test_profile.py)."""
    return {
        "q02": {"value": "female"},
        "q03": {"value": "male"},
        "q04": {"value": "single"},
        "q05": {"value": "age_20_30"},
        "q06": {"value": "asian"},
        "q07": {"value": "loyalty"},
        "q08": {"value": "1994-08-25"},
        "q09": {"value": "fire"},
        "q10": {"value": "heart"},
        "q11": {"value": "building_trust"},
        "q12": {"value": "lack_of_trust"},
        "q13": {"value": "similar_to_me"},
        "q14": {"value": "deep_connection"},
        "q15": {"value": "words_of_affirmation"},
        "q16": {"value": "deep_and_intimate"},
        "q17": {"value": "losing_trust"},
        "q18": {"values": ["building_a_family", "traveling_the_world"]},
    }


@pytest.fixture
def profile():
    return build_soulmate_profile(_get_valid_answers_dict())


# ---------------------------------------------------------------------------
# Template loading & versioning (DEV-SPEC §11.3, §12)
# ---------------------------------------------------------------------------


def test_template_loads_with_canonical_identity():
    tpl = load_sketch_prompt_template()
    assert tpl.name == SKETCH_PROMPT_NAME == "soulmate_pencil_portrait"
    assert tpl.version == "v1"
    assert tpl.version == settings.soulmate_sketch_prompt_version
    assert len(tpl.text) > 0


def test_template_is_cached_across_calls():
    assert load_sketch_prompt_template() is load_sketch_prompt_template()


def test_template_sha256_is_stable_and_hex():
    first = load_sketch_prompt_template()
    second = load_sketch_prompt_template("v1")
    assert first.sha256 == second.sha256
    assert re.fullmatch(r"[0-9a-f]{64}", first.sha256)


def test_missing_template_version_raises():
    with pytest.raises(SketchPromptTemplateError):
        load_sketch_prompt_template("v999")


def test_invalid_template_version_raises():
    with pytest.raises(SketchPromptTemplateError):
        load_sketch_prompt_template("../escape")


def test_template_path_is_versioned_txt_file():
    from app.soulmate.domain.sketch_prompt import sketch_prompt_template_path

    path = sketch_prompt_template_path("v1")
    assert path.name == "v1.txt"
    assert path.parent.name == "soulmate-sketch"
    assert path.exists()


# ---------------------------------------------------------------------------
# §12 placeholder contract
# ---------------------------------------------------------------------------


def test_template_placeholders_exactly_whitelist():
    tpl = load_sketch_prompt_template()
    assert tpl.placeholders == ALLOWED_SKETCH_PROMPT_VARIABLES


def test_template_contains_each_variable_and_priority_order_usage():
    text = load_sketch_prompt_template().text
    assert "- Gender: {gender}" in text
    assert "- Age range: {age_range}" in text
    assert "- Ethnicity / racial appearance: {ethnicity}" in text
    assert "- Distinctive features: {features}" in text
    # PRD Priority Order reuses the variables; gender must appear at least twice.
    assert text.count("{gender}") >= 2
    assert "1. Accurately match {gender}" in text
    assert "2. Clearly remain within {age_range}" in text
    assert "3. Clearly represent {ethnicity}" in text
    assert "4. Faithfully incorporate {features}" in text


def test_template_prompt_content_matches_prd_source_of_truth():
    """The migrated PRD prompt keeps its signature content verbatim."""
    text = load_sketch_prompt_template().text
    assert "## Soulmate Pencil Portrait Prompt" in text
    assert "Treat the provided gender, age range, ethnicity, and distinctive features as **hard visual constraints**, not optional inspiration." in text
    assert "Create a single-person portrait, approximately chest-up or shoulders-up." in text
    assert "sophisticated, hand-drawn graphite pencil sketch on clean, lightly textured off-white drawing paper" in text
    assert "No scenery, no objects, no decorative frame, no text, no names, no zodiac symbols, and no typography." in text
    assert "Never sacrifice attributes 1–4 simply to make the person more conventionally attractive." in text


def test_template_validation_rejects_disallowed_placeholder():
    with pytest.raises(SketchPromptTemplateError) as exc:
        SketchPromptTemplate(
            name=SKETCH_PROMPT_NAME,
            version="test",
            text="A portrait of {gender} with {user_name} and {age_range} and {ethnicity} and {features}.",
        )
    assert "user_name" in str(exc.value)


def test_template_validation_rejects_missing_required_placeholder():
    with pytest.raises(SketchPromptTemplateError) as exc:
        SketchPromptTemplate(
            name=SKETCH_PROMPT_NAME,
            version="test",
            text="A portrait of {gender} with {age_range} and {ethnicity}.",
        )
    assert "features" in str(exc.value)


def test_template_validation_rejects_prd_style_double_braces():
    with pytest.raises(SketchPromptTemplateError):
        SketchPromptTemplate(
            name=SKETCH_PROMPT_NAME,
            version="test",
            text="A portrait of {{gender}} with {age_range} and {ethnicity} and {features}.",
        )


def test_template_validation_rejects_stray_braces():
    with pytest.raises(SketchPromptTemplateError):
        SketchPromptTemplate(
            name=SKETCH_PROMPT_NAME,
            version="test",
            text="A portrait of {gender} with {age_range} and {ethnicity} and {features} and a stray { brace.",
        )


# ---------------------------------------------------------------------------
# Option code -> human-readable mapping (DEV-SPEC §11.2, §12)
# ---------------------------------------------------------------------------


def test_input_mapping_matches_spec_example(profile):
    inputs = build_sketch_prompt_inputs(profile)
    assert isinstance(inputs, SketchPromptInputs)
    assert inputs.gender == "male"  # Q03 preferred_partner_gender (QUIZ-01)
    assert inputs.age_range == "20-30"  # Q05
    assert inputs.ethnicity == "Asian"  # Q06
    assert inputs.features == "Loyalty"  # Q07 (PROMPT-01: Q7 -> features unchanged)


@pytest.mark.parametrize(
    "question_code,code,expected",
    [
        ("q03", "male", "male"),
        ("q03", "female", "female"),
        ("q05", "age_20_30", "20-30"),
        ("q05", "age_30_40", "30-40"),
        ("q05", "age_40_50", "40-50"),
        ("q05", "age_50_plus", "50+"),
        ("q06", "caucasian_white", "Caucasian/White"),
        ("q06", "hispanic_latino", "Hispanic/Latino"),
        ("q06", "african_african_american", "African/African-American"),
        ("q06", "asian", "Asian"),
        ("q06", "no_preference", "No preference"),
        ("q07", "kindness", "Kindness"),
        ("q07", "loyalty", "Loyalty"),
        ("q07", "intelligence", "Intelligence"),
        ("q07", "creativity", "Creativity"),
        ("q07", "passion", "Passion"),
        ("q07", "empathy", "Empathy"),
    ],
)
def test_every_option_code_maps_to_readable_value(question_code, code, expected):
    assert map_sketch_option_to_readable(question_code, code) == expected


def test_mapping_table_covers_exactly_canonical_config_options():
    """Drift guard: table must cover exactly the options defined for q03/q05/q06/q07."""
    validate_sketch_input_mapping_coverage()  # must not raise for the canonical config


def test_mapping_coverage_detects_missing_config_option():
    config: QuizConfig = get_cached_quiz_config().model_copy(deep=True)
    for question in config.questions:
        if question.code == "q06":
            question.options = [o for o in question.options if o.code != "asian"]
    with pytest.raises(SketchPromptInputError) as exc:
        validate_sketch_input_mapping_coverage(config)
    assert "asian" in str(exc.value)


def test_mapping_coverage_detects_stale_table_entry():
    config: QuizConfig = get_cached_quiz_config().model_copy(deep=True)
    for question in config.questions:
        if question.code == "q07":
            question.options = question.options[:-1]  # drop one option the table still maps
    with pytest.raises(SketchPromptInputError):
        validate_sketch_input_mapping_coverage(config)


def test_unknown_option_code_never_reaches_provider():
    with pytest.raises(SketchPromptInputError):
        map_sketch_option_to_readable("q06", "martian")
    with pytest.raises(SketchPromptInputError):
        map_sketch_option_to_readable("q06", "")
    with pytest.raises(SketchPromptInputError):
        map_sketch_option_to_readable("q99", "male")


# ---------------------------------------------------------------------------
# Explicit inputs & rendering guards (no missing placeholder reaches the provider)
# ---------------------------------------------------------------------------


def test_inputs_reject_empty_values():
    with pytest.raises(SketchPromptInputError):
        SketchPromptInputs(gender="male", age_range="30-40", ethnicity="Asian", features="   ")
    with pytest.raises(SketchPromptInputError):
        SketchPromptInputs(gender="", age_range="30-40", ethnicity="Asian", features="Kindness")


def test_inputs_reject_extra_variables():
    with pytest.raises(Exception):
        SketchPromptInputs(
            gender="male",
            age_range="30-40",
            ethnicity="Asian",
            features="Kindness",
            style="photorealistic",  # client-injected prompt material must be impossible
        )


def test_inputs_values_are_stripped():
    inputs = SketchPromptInputs(
        gender=" male ", age_range=" 30-40 ", ethnicity=" Asian ", features=" Kindness "
    )
    assert inputs.model_dump() == {
        "gender": "male",
        "age_range": "30-40",
        "ethnicity": "Asian",
        "features": "Kindness",
    }


def test_render_produces_provider_ready_prompt_with_metadata(profile):
    rendered = render_sketch_prompt(build_sketch_prompt_inputs(profile))
    assert isinstance(rendered, RenderedSketchPrompt)
    assert rendered.prompt_name == SKETCH_PROMPT_NAME
    assert rendered.prompt_version == "v1"
    assert rendered.model == settings.soulmate_image_model == "gpt-image-2"
    assert rendered.template_sha256 == load_sketch_prompt_template().sha256

    text = rendered.rendered_text
    assert "- Gender: male" in text
    assert "- Age range: 20-30" in text
    assert "- Ethnicity / racial appearance: Asian" in text
    assert "- Distinctive features: Loyalty" in text
    # No placeholder or stray brace may survive into the provider request.
    assert "{" not in text and "}" not in text


def test_render_refuses_unresolved_placeholder_guard():
    """Belt-and-braces: even an unvalidated template cannot leak unresolved variables."""
    # PRD-style double braces survive str.format as literal single braces — the
    # post-render scan must reject the result.
    tpl = SketchPromptTemplate.model_construct(
        name=SKETCH_PROMPT_NAME,
        version="v1",
        text="Portrait of {{gender}} with {features}.",
    )
    with pytest.raises(SketchPromptTemplateError):
        render_sketch_prompt(
            SketchPromptInputs(gender="male", age_range="30-40", ethnicity="Asian", features="Kindness"),
            template=tpl,
        )


def test_render_wraps_unresolvable_template_as_prompt_error():
    """A template bypassing validation with an unknown variable surfaces as a prompt error."""
    tpl = SketchPromptTemplate.model_construct(
        name=SKETCH_PROMPT_NAME,
        version="v1",
        text="Portrait of {nickname} with {features}.",
    )
    with pytest.raises(SketchPromptTemplateError):
        render_sketch_prompt(
            SketchPromptInputs(gender="male", age_range="30-40", ethnicity="Asian", features="Kindness"),
            template=tpl,
        )


# ---------------------------------------------------------------------------
# PROMPT-01 / QUIZ-01 invariants
# ---------------------------------------------------------------------------


def test_prompt01_q7_flows_into_features_unchanged():
    answers = _get_valid_answers_dict()
    answers["q07"] = {"value": "empathy"}
    rendered = build_rendered_sketch_prompt(build_soulmate_profile(answers))
    assert rendered.inputs.features == "Empathy"
    assert "- Distinctive features: Empathy" in rendered.rendered_text


def test_quiz01_prompt_gender_is_preferred_partner_not_user_gender():
    answers = _get_valid_answers_dict()  # q02=female user, q03=male partner
    rendered = build_rendered_sketch_prompt(build_soulmate_profile(answers))
    assert rendered.inputs.gender == "male"
    assert "- Gender: male" in rendered.rendered_text
    assert "- Gender: female" not in rendered.rendered_text


# ---------------------------------------------------------------------------
# §11.3 metadata to be stored with the generated asset
# ---------------------------------------------------------------------------


def test_artifact_column_values_carry_prompt_version_and_inputs(profile):
    rendered = build_rendered_sketch_prompt(profile)
    values = rendered.artifact_column_values()
    assert values["prompt_version"] == "v1"
    assert values["model"] == "gpt-image-2"
    assert values["input_json"] == {
        "gender": "male",
        "age_range": "20-30",
        "ethnicity": "Asian",
        "features": "Loyalty",
    }
    # Exact column names on SoulmateArtifact (SP-501 schema).
    assert set(values) == {"prompt_version", "model", "input_json"}


def test_end_to_end_profile_to_rendered_prompt(profile):
    rendered = build_rendered_sketch_prompt(profile)
    assert isinstance(rendered, RenderedSketchPrompt)
    assert rendered.inputs.model_dump() == rendered.artifact_column_values()["input_json"]
    assert "{" not in rendered.rendered_text and "}" not in rendered.rendered_text
