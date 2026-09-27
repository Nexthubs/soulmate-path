"""
Report generation provider interface tests (DEV-SPEC §13.2–13.4; SP-704;
Decisions: REPORT-01, REPORT-02).

Acceptance criteria under test:
- input uses normalized profile/versioned context (SoulmateProfileV1 + prompt_version);
- output validates against the ReportV1 contract (both providers, every path);
- provider implementations can be mock or OpenAI-compatible, and are pluggable
  through the factory;
- the production switch is OFF by default (REPORT-01/02) and the factory fails
  closed while disabled;
- no production reading content exists in this repository (missing template file
  fails closed; the mock is unmistakably test content).
"""

import json
import uuid
from pathlib import Path

import httpx
import pytest

from app.core.config import settings
from app.soulmate.domain.profile import build_soulmate_profile
from app.soulmate.domain.report import parse_soulmate_report_v1
from app.soulmate.domain.report_models import (
    ReportGenerationDisabledError,
    ReportGenerationInput,
    ReportProviderError,
    SoulmateReportGenerator,
)
from app.soulmate.services.report_providers import (
    ALLOWED_REPORT_PROMPT_VARIABLES,
    REPORT_PROVIDER_MOCK,
    REPORT_PROVIDER_OPENAI_COMPATIBLE,
    MockReportProvider,
    OpenAICompatibleReportProvider,
    ReportPromptTemplate,
    ReportPromptTemplateError,
    build_report_provider,
    chat_completions_url,
    load_report_prompt_template,
    render_report_prompt,
)


def _get_valid_answers_dict():
    """Complete valid answers (same fixture style as test_profile.py/test_sketch_prompt.py)."""
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


@pytest.fixture
def generation_input(profile):
    return ReportGenerationInput(profile=profile, prompt_version="v1")


# ---------------------------------------------------------------------------
# §13.3 input contract: normalized profile + versioned context
# ---------------------------------------------------------------------------


def test_generation_input_requires_normalized_profile_and_version():
    from pydantic import ValidationError as PydanticValidationError

    with pytest.raises(PydanticValidationError):
        ReportGenerationInput(profile={"userGender": "female"}, prompt_version="v1")
    with pytest.raises(PydanticValidationError):
        ReportGenerationInput(profile=None, prompt_version="v1")
    profile = build_soulmate_profile(_get_valid_answers_dict())
    with pytest.raises(PydanticValidationError):
        ReportGenerationInput(profile=profile, prompt_version="")
    inp = ReportGenerationInput(profile=profile, prompt_version="v1")
    assert inp.profile.preferred_partner_gender == "male"  # QUIZ-01: Q03, not Q02


def test_no_client_prompt_text_can_enter_generation_input():
    """The input contract has no field for prompt content — only the version id."""
    assert set(ReportGenerationInput.model_fields) == {"profile", "prompt_version"}


# ---------------------------------------------------------------------------
# Mock provider (clearly non-production)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_provider_satisfies_interface_and_validates_output(generation_input):
    provider: SoulmateReportGenerator = MockReportProvider()
    assert isinstance(provider, SoulmateReportGenerator)
    result = await provider.generate(generation_input)
    assert result.provider == REPORT_PROVIDER_MOCK
    assert result.model == "mock"
    assert result.prompt_version == generation_input.prompt_version
    assert result.duration_ms >= 0
    # Output validates against the ReportV1 contract (provider contract requirement).
    parse_soulmate_report_v1(result.report.model_dump(by_alias=True, exclude_none=True))


@pytest.mark.asyncio
async def test_mock_provider_consumes_normalized_profile(generation_input):
    result = await MockReportProvider().generate(generation_input)
    body = result.report.sections[0].body
    # The normalized profile carries canonical option codes (SP-205): preferred
    # partner gender from Q03, age range, and key quality must be consumed as-is.
    assert "'male'" in body  # preferred_partner_gender (Q03), not user_gender (Q02 = female)
    assert "age_20_30" in body
    assert "loyalty" in body


@pytest.mark.asyncio
async def test_mock_provider_is_deterministic_and_unmistakably_test_content(generation_input):
    a = await MockReportProvider().generate(generation_input)
    b = await MockReportProvider().generate(generation_input)
    assert a.report == b.report
    assert a.report.title.startswith("[MOCK]")
    assert "REPORT-01" in a.report.intro or "REPORT-02" in a.report.intro


# ---------------------------------------------------------------------------
# Versioned prompt template (REPORT-02 slot: infrastructure, no content shipped)
# ---------------------------------------------------------------------------


def test_allowed_template_variables_are_whitelisted():
    assert ALLOWED_REPORT_PROMPT_VARIABLES == frozenset({"profile_json", "report_schema_json"})


def test_missing_template_file_fails_closed(tmp_path, monkeypatch):
    from app.soulmate.services import report_providers as rp

    monkeypatch.setattr(rp, "REPORT_PROMPTS_DIR", tmp_path)
    with pytest.raises(ReportPromptTemplateError) as exc_info:
        load_report_prompt_template("v1")
    assert "REPORT-02" in exc_info.value.message


def test_template_rejects_disallowed_placeholders(tmp_path, monkeypatch):
    from app.soulmate.services import report_providers as rp

    prompts_dir = tmp_path / "soulmate-report"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "v1.txt").write_text(
        "Profile: {profile_json}\nSchema: {report_schema_json}\nStory: {soulmate_story}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rp, "REPORT_PROMPTS_DIR", tmp_path)
    rp.invalidate_report_prompt_template_cache()
    with pytest.raises(ReportPromptTemplateError) as exc_info:
        load_report_prompt_template("v1")
    assert "soulmate_story" in exc_info.value.message


def test_template_rejects_double_brace_escapes(tmp_path, monkeypatch):
    from app.soulmate.services import report_providers as rp

    prompts_dir = tmp_path / "soulmate-report"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "v1.txt").write_text("Profile: {{profile_json}}\n", encoding="utf-8")
    monkeypatch.setattr(rp, "REPORT_PROMPTS_DIR", tmp_path)
    rp.invalidate_report_prompt_template_cache()
    with pytest.raises(ReportPromptTemplateError):
        load_report_prompt_template("v1")


def test_rendered_prompt_embeds_profile_and_schema_without_unresolved_placeholders(
    tmp_path, monkeypatch, profile
):
    from app.soulmate.services import report_providers as rp

    prompts_dir = tmp_path / "soulmate-report"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "v9.txt").write_text(
        "Normalize into JSON:\nPROFILE: {profile_json}\nCONTRACT: {report_schema_json}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rp, "REPORT_PROMPTS_DIR", tmp_path)
    rp.invalidate_report_prompt_template_cache()

    tpl = load_report_prompt_template("v9")
    assert tpl.sha256
    rendered, used = render_report_prompt(
        ReportGenerationInput(profile=profile, prompt_version="v9"), template=tpl
    )
    assert used is tpl
    assert '"preferredPartnerGender": "male"' in rendered  # QUIZ-01: Q03 value, camelCase
    # The schema placeholder expands; no template placeholder survives rendering.
    assert "{profile_json}" not in rendered
    assert "{report_schema_json}" not in rendered
    assert '"SoulmateReportV1"' in rendered or "sections" in rendered


def test_invalid_prompt_version_is_rejected():
    with pytest.raises(ReportPromptTemplateError):
        load_report_prompt_template("../etc/passwd")
    with pytest.raises(ReportPromptTemplateError):
        load_report_prompt_template("")


# ---------------------------------------------------------------------------
# OpenAI-compatible provider
# ---------------------------------------------------------------------------


def _chat_response(content: str, request_id: str = "req-report-1") -> httpx.Response:
    return httpx.Response(
        200,
        headers={"x-request-id": request_id},
        json={
            "id": "chatcmpl-1",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
        },
        request=httpx.Request("POST", "https://relay.example.com/v1/chat/completions"),
    )


def _valid_report_json() -> str:
    return json.dumps(
        {
            "schemaVersion": "v1",
            "title": "Your Soulmate Report",
            "intro": "Structured output conforming to the ReportV1 contract.",
            "sections": [
                {
                    "index": "01.",
                    "title": "Section One",
                    "body": "Body text without markup.",
                    "points": [{"title": "Point", "body": "Point body."}],
                }
            ],
            "closing": "End mark text.",
        },
        ensure_ascii=False,
    )


def _openai_provider_with(handler, **kwargs) -> OpenAICompatibleReportProvider:
    transport = httpx.MockTransport(handler)
    return OpenAICompatibleReportProvider(
        api_key="sk-test",
        base_url="https://relay.example.com/v1",
        model="gpt-report-x",
        http_client=httpx.AsyncClient(transport=transport),
        **kwargs,
    )


_TEST_TEMPLATE_TEXT = (
    "Build the report.\nPROFILE: {profile_json}\nCONTRACT: {report_schema_json}\n"
)


def _install_test_template(monkeypatch, version: str = "v1", tmp_path: Path = None):
    """Installs a clearly-test prompt template so HTTP-layer tests can reach the wire.

    No production template ships in the repo (REPORT-02); provider tests exercise
    the request/response machinery against this explicitly temporary template.
    """
    from app.soulmate.services import report_providers as rp

    root = tmp_path or (Path(__file__).parent / "_tmp_report_prompts")
    prompts_dir = root / "soulmate-report"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / f"{version}.txt").write_text(_TEST_TEMPLATE_TEXT, encoding="utf-8")
    monkeypatch.setattr(rp, "REPORT_PROMPTS_DIR", root)
    rp.invalidate_report_prompt_template_cache()


@pytest.mark.asyncio
async def test_openai_provider_happy_path_returns_validated_report_and_metadata(
    monkeypatch, tmp_path, profile
):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        return _chat_response(_valid_report_json())

    _install_test_template(monkeypatch, tmp_path=tmp_path)

    async with _openai_provider_with(handler) as provider:
        result = await provider.generate(
            ReportGenerationInput(profile=profile, prompt_version="v1")
        )

    assert seen["url"] == "https://relay.example.com/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["payload"]["model"] == "gpt-report-x"
    assert '"preferredPartnerGender"' in seen["payload"]["messages"][0]["content"]
    assert result.provider == REPORT_PROVIDER_OPENAI_COMPATIBLE
    assert result.model == "gpt-report-x"
    assert result.prompt_version == "v1"
    assert result.prompt_sha256
    assert result.provider_request_id == "req-report-1"
    parse_soulmate_report_v1(result.report.model_dump(by_alias=True, exclude_none=True))


@pytest.mark.asyncio
async def test_openai_provider_parses_fenced_json_output(monkeypatch, tmp_path, profile):
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(f"```json\n{_valid_report_json()}\n```")

    _install_test_template(monkeypatch, tmp_path=tmp_path)

    async with _openai_provider_with(handler) as provider:
        result = await provider.generate(
            ReportGenerationInput(profile=profile, prompt_version="v1")
        )
    assert result.report.title == "Your Soulmate Report"


@pytest.mark.asyncio
async def test_openai_provider_rejects_reportv1_violating_output_permanently(
    monkeypatch, tmp_path, profile
):
    invalid = json.dumps(
        {
            "schemaVersion": "v1",
            "title": "<script>alert(1)</script>",
            "intro": "intro",
            "sections": [{"index": "01.", "title": "T", "body": "B"}],
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(invalid)

    _install_test_template(monkeypatch, tmp_path=tmp_path)

    async with _openai_provider_with(handler) as provider:
        with pytest.raises(ReportProviderError) as exc_info:
            await provider.generate(
                ReportGenerationInput(profile=profile, prompt_version="v1")
            )
    assert exc_info.value.retryable is False
    assert exc_info.value.error_code.value == "GENERATION_FAILED"


@pytest.mark.asyncio
async def test_openai_provider_rejects_non_json_output_permanently(monkeypatch, tmp_path, profile):
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response("Here is your soulmate reading, dear seeker...")

    _install_test_template(monkeypatch, tmp_path=tmp_path)

    async with _openai_provider_with(handler) as provider:
        with pytest.raises(ReportProviderError) as exc_info:
            await provider.generate(
                ReportGenerationInput(profile=profile, prompt_version="v1")
            )
    assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_openai_provider_maps_http_errors_by_retryability(monkeypatch, tmp_path, profile):
    _install_test_template(monkeypatch, tmp_path=tmp_path)
    for status, retryable in [(429, True), (500, True), (503, True), (400, False), (401, False)]:
        def handler(request: httpx.Request, _status=status) -> httpx.Response:
            return httpx.Response(
                _status,
                json={"error": {"message": f"provider said {_status}", "type": "test"}},
                request=httpx.Request("POST", "https://relay.example.com/v1/chat/completions"),
            )

        async with _openai_provider_with(handler) as provider:
            with pytest.raises(ReportProviderError) as exc_info:
                await provider.generate(
                    ReportGenerationInput(profile=profile, prompt_version="v1")
                )
        assert exc_info.value.retryable is retryable, f"HTTP {status}"
        assert f"provider said {status}" in exc_info.value.message


@pytest.mark.asyncio
async def test_openai_provider_network_failure_is_retryable(monkeypatch, tmp_path, profile):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install_test_template(monkeypatch, tmp_path=tmp_path)

    async with _openai_provider_with(handler) as provider:
        with pytest.raises(ReportProviderError) as exc_info:
            await provider.generate(
                ReportGenerationInput(profile=profile, prompt_version="v1")
            )
    assert exc_info.value.retryable is True
    assert exc_info.value.error_code.value == "PROVIDER_UNAVAILABLE"


@pytest.mark.asyncio
async def test_openai_provider_requires_configuration(profile):
    provider = OpenAICompatibleReportProvider(api_key="  ", base_url="https://x/v1", model="m")
    with pytest.raises(ReportProviderError) as exc_info:
        await provider.generate(ReportGenerationInput(profile=profile, prompt_version="v1"))
    assert exc_info.value.retryable is False

    provider = OpenAICompatibleReportProvider(api_key="sk", base_url="https://x/v1", model="  ")
    with pytest.raises(ReportProviderError):
        await provider.generate(ReportGenerationInput(profile=profile, prompt_version="v1"))


@pytest.mark.asyncio
async def test_api_key_never_leaks_into_error_surfaces(monkeypatch, tmp_path, profile):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={"error": {"message": "boom", "type": "server"}},
            request=httpx.Request("POST", "https://relay.example.com/v1/chat/completions"),
        )

    _install_test_template(monkeypatch, tmp_path=tmp_path)

    async with _openai_provider_with(handler) as provider:
        with pytest.raises(ReportProviderError) as exc_info:
            await provider.generate(
                ReportGenerationInput(profile=profile, prompt_version="v1")
            )
    err = exc_info.value
    assert "sk-test" not in str(err)
    assert "sk-test" not in json.dumps(err.details)
    assert "sk-test" not in str(getattr(err, "internal_error", ""))


def test_chat_completions_url_strips_trailing_slash():
    assert chat_completions_url("https://x.example.com/v1/") == "https://x.example.com/v1/chat/completions"


# ---------------------------------------------------------------------------
# Factory: pluggable switch, default disabled (REPORT-01/02)
# ---------------------------------------------------------------------------


def test_factory_fails_closed_by_default(monkeypatch):
    monkeypatch.setattr(settings, "soulmate_report_provider", None, raising=False)
    assert settings.is_report_generation_enabled is False
    with pytest.raises(ReportGenerationDisabledError):
        build_report_provider()


def test_factory_builds_mock_provider(monkeypatch):
    monkeypatch.setattr(settings, "soulmate_report_provider", "mock", raising=False)
    provider = build_report_provider()
    assert isinstance(provider, MockReportProvider)
    assert isinstance(provider, SoulmateReportGenerator)


def test_factory_builds_openai_compatible_provider(monkeypatch):
    monkeypatch.setattr(settings, "soulmate_report_provider", "openai_compatible", raising=False)
    provider = build_report_provider(api_key="sk-factory", base_url="https://f/v1", model="m-f")
    assert isinstance(provider, OpenAICompatibleReportProvider)
    assert provider.api_key == "sk-factory"
    assert provider.base_url == "https://f/v1"


def test_factory_rejects_unknown_provider_code(monkeypatch):
    monkeypatch.setattr(settings, "soulmate_report_provider", "psychic_hotline", raising=False)
    with pytest.raises(ReportProviderError) as exc_info:
        build_report_provider()
    assert exc_info.value.retryable is False


def test_v1_draft_template_loads_and_renders(profile):
    """The v1 draft (REPORT-02, PENDING OWNER APPROVAL) loads through the real machinery."""
    tpl = load_report_prompt_template("v1")
    assert sorted(tpl.placeholders) == ["profile_json", "report_schema_json"]
    rendered, used = render_report_prompt(
        ReportGenerationInput(profile=profile, prompt_version="v1")
    )
    assert used is tpl
    assert '"preferredPartnerGender": "male"' in rendered  # QUIZ-01: Q03, not Q02
    assert '"zodiacSign": "Virgo"' in rendered  # 1994-08-25
    assert '"keySoulmateQuality": "loyalty"' in rendered
    assert "{profile_json}" not in rendered and "{report_schema_json}" not in rendered
