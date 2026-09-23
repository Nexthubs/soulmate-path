from decimal import Decimal
import pytest
from app.core.config import ConfigurationError, Settings, settings


def test_default_settings_loaded():
    """Verify default local development settings are valid."""
    assert settings.environment == "development"
    assert settings.debug is False or settings.debug is True
    assert settings.is_production is False
    assert settings.is_sandbox is True
    assert settings.is_report_generation_enabled is False
    assert settings.intro_price == Decimal("19.00")
    assert settings.regular_price == Decimal("29.00")
    assert isinstance(settings.intro_price, Decimal)
    assert isinstance(settings.regular_price, Decimal)

    # In development mode, validation does not fail
    settings.validate_production_config()


def test_production_validation_fails_on_missing_keys():
    """Acceptance criterion: application fails clearly on missing mandatory production config."""
    prod_settings = Settings(
        environment="production",
        app_base_url="http://localhost:3000",
        database_url="postgresql://soulmate:soulmate_dev_password@localhost:5432/soulmate_dev",
        paypal_client_id=None,
        paypal_client_secret=None,
        openai_api_key=None,
        object_storage_bucket=None,
    )
    assert prod_settings.is_production is True

    with pytest.raises(ConfigurationError) as exc_info:
        prod_settings.validate_production_config()

    err_msg = str(exc_info.value)
    assert "APP_BASE_URL" in err_msg
    assert "DATABASE_URL" in err_msg
    assert "PAYPAL_CLIENT_ID" in err_msg
    assert "PAYPAL_CLIENT_SECRET" in err_msg
    assert "OPENAI_API_KEY" in err_msg
    assert "OBJECT_STORAGE_BUCKET" in err_msg


def test_production_validation_passes_when_all_keys_provided():
    """Verify production settings pass validation when all required credentials exist."""
    valid_prod_settings = Settings(
        environment="production",
        app_base_url="https://soulmate.example.com",
        database_url="postgresql://prod_user:super_secret_pw@db.prod:5432/soulmate_db",
        paypal_client_id="paypal_client_123",
        paypal_client_secret="paypal_secret_456",
        paypal_webhook_id="webhook_789",
        paypal_product_id="prod_plan_abc",
        paypal_soulmate_intro_plan_id="plan_intro_001",
        soulmate_intro_price=Decimal("19.00"),
        soulmate_regular_price=Decimal("29.00"),
        openai_api_key="sk-test-key-openai",
        object_storage_bucket="soulmate-prod-assets",
        object_storage_access_key="minio_or_s3_key",
        object_storage_secret_key="minio_or_s3_secret",
    )
    assert valid_prod_settings.is_production is True
    # Should complete without error
    valid_prod_settings.validate_production_config()


def test_pricing_centralization_and_decimal_types():
    """Acceptance criterion: INTRO_PRICE and REGULAR_PRICE are not scattered literals."""
    custom_settings = Settings(
        soulmate_intro_price=Decimal("15.50"),
        soulmate_regular_price=Decimal("25.00"),
    )
    assert custom_settings.intro_price == Decimal("15.50")
    assert custom_settings.regular_price == Decimal("25.00")
    assert isinstance(custom_settings.intro_price, Decimal)
    assert isinstance(custom_settings.regular_price, Decimal)


def test_report_feature_flag_behavior():
    """Decisions: REPORT-01 / REPORT-02 — Report generation remains disabled by default."""
    disabled_settings = Settings(soulmate_report_provider=None)
    assert disabled_settings.is_report_generation_enabled is False

    enabled_settings = Settings(soulmate_report_provider="openai-chat")
    assert enabled_settings.is_report_generation_enabled is True
