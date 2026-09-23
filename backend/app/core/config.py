import ipaddress
import urllib.parse
from decimal import Decimal
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(ValueError):
    """Raised when application configuration is invalid or missing required keys."""
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --------------------------------------------------------------------------
    # 1. Application & Base URL (DOMAIN-01: No hardcoded domains)
    # --------------------------------------------------------------------------
    app_name: str = "Soulmate Path API"
    app_version: str = "v1"
    environment: str = Field(default="development", description="development | test | staging | production")
    debug: bool = False
    app_base_url: str = Field(default="http://localhost:3000", description="Canonical application base URL")
    api_prefix: str = "/api/soulmate"
    cors_allow_origins: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # --------------------------------------------------------------------------
    # 2. Database Connection (PostgreSQL 16)
    # --------------------------------------------------------------------------
    database_url: str = "postgresql://soulmate:soulmate_dev_password@localhost:5432/soulmate_dev"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False

    # --------------------------------------------------------------------------
    # 3. Soulmate Quiz & Business Timers (Spec §4, §10, TIME-01)
    # --------------------------------------------------------------------------
    soulmate_quiz_version: str = "soulmate-quiz-v1"
    soulmate_sketch_unlock_hours: int = 12
    soulmate_report_unlock_hours: int = 24
    soulmate_sketch_generation_mode: str = "on_demand"
    soulmate_report_generation_mode: str = "on_demand"

    # --------------------------------------------------------------------------
    # 4. PayPal Integration & Pricing (Spec §9, PAY-01, PAY-02, PAY-AUTH-01)
    # --------------------------------------------------------------------------
    paypal_env: str = Field(default="sandbox", description="sandbox | production")
    paypal_client_id: Optional[str] = None
    paypal_client_secret: Optional[str] = None
    paypal_webhook_id: Optional[str] = None
    paypal_product_id: Optional[str] = None
    paypal_soulmate_intro_plan_id: Optional[str] = None
    paypal_soulmate_standard_plan_id: Optional[str] = None

    soulmate_currency: str = "USD"
    # Centralized Decimal pricing (PAY-01: no hardcoded defaults)
    soulmate_intro_price: Optional[Decimal] = None
    soulmate_regular_price: Optional[Decimal] = None

    # --------------------------------------------------------------------------
    # 5. AI Image Generation / Sketch (Spec §11, ASSET-01, PROMPT-01)
    # --------------------------------------------------------------------------
    openai_api_key: Optional[str] = None
    soulmate_image_model: str = "gpt-image-2"
    soulmate_image_size: str = "1024x1536"
    soulmate_image_quality: str = "medium"
    soulmate_image_format: str = "webp"
    soulmate_sketch_prompt_version: str = "v1"

    # --------------------------------------------------------------------------
    # 6. Report Generation Feature Flag (Spec §13, REPORT-01, REPORT-02)
    # --------------------------------------------------------------------------
    soulmate_report_provider: Optional[str] = None
    soulmate_report_model: Optional[str] = None
    soulmate_report_prompt_version: Optional[str] = None

    # --------------------------------------------------------------------------
    # 7. Durable Object Storage / S3 / CDN (Spec §11.6, ASSET-01)
    # --------------------------------------------------------------------------
    object_storage_bucket: Optional[str] = None
    object_storage_region: str = "us-east-1"
    object_storage_endpoint: Optional[str] = None
    object_storage_access_key: Optional[str] = None
    object_storage_secret_key: Optional[str] = None
    object_storage_public_url_prefix: Optional[str] = None

    # --------------------------------------------------------------------------
    # 8. Async Job / Worker Configuration (Spec §12)
    # --------------------------------------------------------------------------
    redis_url: Optional[str] = None
    job_worker_concurrency: int = 4

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def is_sandbox(self) -> bool:
        return self.paypal_env.lower() == "sandbox"

    @property
    def is_report_generation_enabled(self) -> bool:
        """Report generation remains disabled until REPORT-01/02 are resolved."""
        return bool(self.soulmate_report_provider and self.soulmate_report_provider.strip())

    @property
    def intro_price(self) -> Optional[Decimal]:
        return self.soulmate_intro_price

    @property
    def regular_price(self) -> Optional[Decimal]:
        return self.soulmate_regular_price

    def validate_production_config(self) -> None:
        """
        Enforce strict validation of mandatory configuration keys for production.
        Fails fast with ConfigurationError listing all missing or insecure keys.
        """
        if not self.is_production:
            return

        missing_keys: List[str] = []

        # App Base URL check (DOMAIN-01)
        if not self.app_base_url:
            missing_keys.append("APP_BASE_URL (mandatory in production)")
        else:
            try:
                parsed_url = urllib.parse.urlparse(self.app_base_url)
                if parsed_url.scheme != "https":
                    missing_keys.append("APP_BASE_URL (must use HTTPS scheme in production)")
                if not parsed_url.netloc or not parsed_url.hostname:
                    missing_keys.append("APP_BASE_URL (must have a valid domain hostname in production)")
                else:
                    host = parsed_url.hostname.lower()
                    if host in ("localhost", "0.0.0.0"):
                        missing_keys.append("APP_BASE_URL (must not be localhost or 0.0.0.0 in production)")
                    else:
                        try:
                            ip = ipaddress.ip_address(host)
                            if ip.is_loopback or ip.is_private or ip.is_reserved or ip.is_unspecified:
                                missing_keys.append("APP_BASE_URL (must not use loopback or private IP in production)")
                        except ValueError:
                            # Valid domain hostname, which is expected
                            pass
            except Exception as e:
                missing_keys.append(f"APP_BASE_URL (invalid URL: {e})")

        # Database credentials check
        if "soulmate_dev_password" in self.database_url:
            missing_keys.append("DATABASE_URL (must not use dev default credentials in production)")

        # PayPal environment check
        if self.paypal_env.lower() != "production":
            missing_keys.append("PAYPAL_ENV (must be 'production' when ENVIRONMENT=production)")

        # PayPal credentials & plans
        if not self.paypal_client_id:
            missing_keys.append("PAYPAL_CLIENT_ID")
        if not self.paypal_client_secret:
            missing_keys.append("PAYPAL_CLIENT_SECRET")
        if not self.paypal_webhook_id:
            missing_keys.append("PAYPAL_WEBHOOK_ID")
        if not self.paypal_product_id:
            missing_keys.append("PAYPAL_PRODUCT_ID")
        if not self.paypal_soulmate_intro_plan_id:
            missing_keys.append("PAYPAL_SOULMATE_INTRO_PLAN_ID")

        # Pricing check (PAY-01)
        if self.soulmate_intro_price is None or self.soulmate_intro_price <= 0:
            missing_keys.append("SOULMATE_INTRO_PRICE (mandatory in production per PAY-01)")
        if self.soulmate_regular_price is None or self.soulmate_regular_price <= 0:
            missing_keys.append("SOULMATE_REGULAR_PRICE (mandatory in production per PAY-01)")

        # OpenAI Sketch Generator
        if not self.openai_api_key:
            missing_keys.append("OPENAI_API_KEY")

        # Durable Object Storage (ASSET-01)
        if not self.object_storage_bucket:
            missing_keys.append("OBJECT_STORAGE_BUCKET")
        if not self.object_storage_access_key:
            missing_keys.append("OBJECT_STORAGE_ACCESS_KEY")
        if not self.object_storage_secret_key:
            missing_keys.append("OBJECT_STORAGE_SECRET_KEY")

        if missing_keys:
            error_details = "\n  - " + "\n  - ".join(missing_keys)
            raise ConfigurationError(
                f"Production environment configuration validation failed! Missing or invalid keys:{error_details}"
            )


settings = Settings()
