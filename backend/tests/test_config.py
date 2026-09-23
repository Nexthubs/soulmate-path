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
    assert settings.intro_price is None
    assert settings.regular_price is None

    # In development mode, validation does not fail
    settings.validate_production_config()


def test_app_startup_fails_in_production_with_missing_config(monkeypatch):
    """Verify FastAPI application lifespan startup fails immediately when mandatory production config is missing (C-1, H-1)."""
    from starlette.testclient import TestClient
    from app.main import app

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "paypal_client_id", None)

    with pytest.raises(ConfigurationError) as exc_info:
        with TestClient(app):
            pass

    err_msg = str(exc_info.value)
    assert "Production environment configuration validation failed" in err_msg
    assert "PAYPAL_CLIENT_ID" in err_msg


def test_app_startup_succeeds_in_development_mode():
    """Verify FastAPI application starts cleanly in development mode."""
    from starlette.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200


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
        paypal_env="production",
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


def test_production_validation_rejects_insecure_and_loopback_urls():
    """Verify production rejects non-HTTPS, localhost, 127.0.0.1, or private IP base URLs."""
    base_kwargs = dict(
        environment="production",
        database_url="postgresql://prod_user:super_secret_pw@db.prod:5432/soulmate_db",
        paypal_env="production",
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

    # 1. Loopback IP http://127.0.0.1:3000
    with pytest.raises(ConfigurationError) as exc1:
        Settings(app_base_url="http://127.0.0.1:3000", **base_kwargs).validate_production_config()
    assert "APP_BASE_URL" in str(exc1.value)

    # 2. Non-HTTPS http://example.com
    with pytest.raises(ConfigurationError) as exc2:
        Settings(app_base_url="http://example.com", **base_kwargs).validate_production_config()
    assert "HTTPS" in str(exc2.value)

    # 3. Localhost https://localhost:3000
    with pytest.raises(ConfigurationError) as exc3:
        Settings(app_base_url="https://localhost:3000", **base_kwargs).validate_production_config()
    assert "localhost" in str(exc3.value)


def test_production_validation_rejects_sandbox_paypal_env():
    """Verify production requires PAYPAL_ENV=production."""
    base_kwargs = dict(
        environment="production",
        app_base_url="https://soulmate.example.com",
        database_url="postgresql://prod_user:super_secret_pw@db.prod:5432/soulmate_db",
        paypal_env="sandbox",
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
    with pytest.raises(ConfigurationError) as exc:
        Settings(**base_kwargs).validate_production_config()
    assert "PAYPAL_ENV" in str(exc.value)


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
