import ipaddress
import re
import urllib.parse
from decimal import Decimal
from typing import Any, List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_DOMAIN_LABEL_REGEX = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def _is_valid_domain_hostname(hostname: str) -> bool:
    """
    Validates hostname against RFC 1035/1123 domain name syntax:
    - Overall length <= 253 characters.
    - No spaces or forbidden characters.
    - Labels separated by single dots (no empty labels like '..').
    - At least 2 labels (e.g. 'domain.com', not single-word 'bad host').
    - Each label 1-63 chars, alphanumeric with optional interior hyphens.
    - TLD must be >= 2 characters, alphabetic or Punycode ('xn--').
    """
    if not hostname or len(hostname) > 253:
        return False
    if hostname.endswith("."):
        hostname = hostname[:-1]
    labels = hostname.split(".")
    if len(labels) < 2:
        return False
    for label in labels:
        if not label or len(label) > 63:
            return False
        if not _DOMAIN_LABEL_REGEX.match(label):
            return False
    tld = labels[-1]
    if not (tld.isalpha() or tld.startswith("xn--")) or len(tld) < 2:
        return False
    return True


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

    # Soulmate Session & Cookie Auth (DEV-SPEC §6, §15.1, §20)
    session_secret_key: str = Field(
        default="dev-insecure-session-secret-key-soulmate-2026",
        description="HMAC secret key for signing anonymous session ownership tokens",
    )
    session_cookie_name: str = "soulmate_sid"
    session_cookie_max_age_days: int = 30

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

    @field_validator("soulmate_intro_price", "soulmate_regular_price", mode="before")
    @classmethod
    def _coerce_empty_price_to_none(cls, v: Any) -> Any:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return v

    # PAY-02: Re-subscription intro-price eligibility policy ('blocked' | 'single_intro' | 'allow_intro')
    soulmate_resubscription_policy: str = Field(
        default="blocked",
        description="Policy for returning subscribers: 'blocked' (PAY-02 default), 'single_intro', or 'allow_intro'",
    )

    # --------------------------------------------------------------------------
    # 5. AI Image Generation / Sketch (Spec §11, ASSET-01, PROMPT-01)
    # --------------------------------------------------------------------------
    # OPENAI_BASE_URL allows OpenAI-compatible gateways (e.g. self-hosted proxies);
    # it must point to the API root (no trailing /images/generations path).
    openai_base_url: str = "https://api.openai.com/v1"
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
    job_worker_enabled: bool = True
    job_worker_poll_seconds: float = 2.0

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
                            # Not an IP address -> validate as RFC 1123 domain hostname
                            if any(c.isspace() for c in parsed_url.netloc) or not _is_valid_domain_hostname(host):
                                missing_keys.append("APP_BASE_URL (must have a valid domain hostname in production)")
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

        # Re-subscription policy check (PAY-02)
        valid_policies = {"blocked", "single_intro", "allow_intro"}
        if self.soulmate_resubscription_policy.lower() not in valid_policies:
            missing_keys.append(f"SOULMATE_RESUBSCRIPTION_POLICY (must be one of {valid_policies})")

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

        # Session Secret Key check (DEV-SPEC §20)
        if (
            not self.session_secret_key
            or "dev-insecure" in self.session_secret_key
            or len(self.session_secret_key) < 32
        ):
            missing_keys.append("SESSION_SECRET_KEY (must be configured with a secure key >= 32 chars in production)")

        if missing_keys:
            error_details = "\n  - " + "\n  - ".join(missing_keys)
            raise ConfigurationError(
                f"Production environment configuration validation failed! Missing or invalid keys:{error_details}"
            )


settings = Settings()
