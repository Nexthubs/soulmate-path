"""
PayPal REST API Client (DEV-SPEC §9.1–9.2, §22, §25, Decisions: PAY-AUTH-01).
Provides authenticated, asynchronous interaction with PayPal v1 catalog products and billing plans.
"""

import base64
import logging
import time
from typing import Any, Dict, List, Optional
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

PAYPAL_BASE_URLS = {
    "sandbox": "https://api-m.sandbox.paypal.com",
    "production": "https://api-m.paypal.com",
}


class PayPalAPIError(Exception):
    """Exception raised when a PayPal API request fails."""

    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


class PayPalAuthError(PayPalAPIError):
    """Exception raised when PayPal OAuth authentication fails."""
    pass


class PayPalClient:
    """
    Asynchronous client for interacting with the PayPal REST API.
    Handles OAuth2 token acquisition, caching, renewal, and catalog/billing endpoints.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        environment: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        timeout: float = 30.0,
    ):
        self.client_id = client_id or settings.paypal_client_id
        self.client_secret = client_secret or settings.paypal_client_secret
        env_raw = (environment or settings.paypal_env or "sandbox").lower().strip()
        if env_raw not in PAYPAL_BASE_URLS:
            raise ValueError(f"Invalid PayPal environment '{env_raw}'. Must be 'sandbox' or 'production'.")
        self.environment = env_raw
        self.base_url = PAYPAL_BASE_URLS[self.environment]
        self.timeout = timeout

        self._http_client = http_client
        self._owns_http_client = http_client is None

        # OAuth2 token caching
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=self.timeout)
            self._owns_http_client = True
        return self._http_client

    async def close(self) -> None:
        """Close the underlying HTTP client if owned by this instance."""
        if self._owns_http_client and self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    async def __aenter__(self) -> "PayPalClient":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    # --------------------------------------------------------------------------
    # OAuth2 Authentication
    # --------------------------------------------------------------------------

    async def get_access_token(self, force_refresh: bool = False) -> str:
        """
        Retrieve a valid OAuth2 bearer access token for PayPal API requests.
        Tokens are cached until near expiry.
        """
        now = time.time()
        # Use cached token if valid for at least another 60 seconds
        if not force_refresh and self._access_token and (self._token_expires_at - now > 60):
            return self._access_token

        if not self.client_id or not self.client_secret:
            raise PayPalAuthError("PayPal client_id and client_secret must be configured to authenticate.")

        client = await self._get_client()
        auth_header = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode("utf-8")
        headers = {
            "Authorization": f"Basic {auth_header}",
            "Accept": "application/json",
            "Accept-Language": "en_US",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {"grant_type": "client_credentials"}

        try:
            resp = await client.post(
                f"{self.base_url}/v1/oauth2/token",
                headers=headers,
                data=data,
            )
        except Exception as e:
            logger.error("Failed to connect to PayPal OAuth endpoint: %s", str(e))
            raise PayPalAuthError(f"Network error connecting to PayPal OAuth endpoint: {e}") from e

        if resp.status_code != 200:
            logger.error("PayPal OAuth authentication failed with HTTP %s", resp.status_code)
            try:
                err_data = resp.json()
            except Exception:
                err_data = {"raw": resp.text}
            raise PayPalAuthError(
                f"PayPal OAuth failed (HTTP {resp.status_code}): {err_data.get('error_description', 'Authentication error')}",
                status_code=resp.status_code,
                details=err_data,
            )

        token_data = resp.json()
        self._access_token = token_data["access_token"]
        expires_in = int(token_data.get("expires_in", 3600))
        self._token_expires_at = now + expires_in
        return self._access_token

    async def _request(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> httpx.Response:
        """Execute an authenticated request with bearer token and error handling."""
        token = await self.get_access_token()
        client = await self._get_client()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if request_id:
            headers["PayPal-Request-Id"] = request_id

        url = f"{self.base_url}{path}"
        try:
            resp = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=json_body,
                params=params,
            )
        except Exception as e:
            logger.error("PayPal API request %s %s failed: %s", method, path, str(e))
            raise PayPalAPIError(f"Network error communicating with PayPal: {e}") from e

        return resp

    # --------------------------------------------------------------------------
    # Catalog Products API (/v1/catalogs/products)
    # --------------------------------------------------------------------------

    async def create_product(
        self,
        name: str,
        description: Optional[str] = None,
        product_type: str = "SERVICE",
        category: str = "ONLINE_SERVICES",
        image_url: Optional[str] = None,
        home_url: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a reusable product catalog item on PayPal."""
        payload: Dict[str, Any] = {
            "name": name,
            "type": product_type,
            "category": category,
        }
        if description:
            payload["description"] = description
        if image_url:
            payload["image_url"] = image_url
        if home_url:
            payload["home_url"] = home_url

        resp = await self._request("POST", "/v1/catalogs/products", json_body=payload, request_id=request_id)
        if resp.status_code not in (200, 201):
            try:
                err_data = resp.json()
            except Exception:
                err_data = {"raw": resp.text}
            raise PayPalAPIError(
                f"Failed to create PayPal product (HTTP {resp.status_code}): {err_data.get('message', 'Unknown error')}",
                status_code=resp.status_code,
                details=err_data,
            )
        return resp.json()

    async def get_product(self, product_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve catalog product details by ID. Returns None if 404."""
        resp = await self._request("GET", f"/v1/catalogs/products/{product_id}")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            try:
                err_data = resp.json()
            except Exception:
                err_data = {"raw": resp.text}
            raise PayPalAPIError(
                f"Failed to fetch PayPal product {product_id} (HTTP {resp.status_code})",
                status_code=resp.status_code,
                details=err_data,
            )
        return resp.json()

    async def list_products(self, page: int = 1, page_size: int = 20) -> List[Dict[str, Any]]:
        """List catalog products."""
        params = {"page": page, "page_size": page_size}
        resp = await self._request("GET", "/v1/catalogs/products", params=params)
        if resp.status_code != 200:
            try:
                err_data = resp.json()
            except Exception:
                err_data = {"raw": resp.text}
            raise PayPalAPIError(
                f"Failed to list PayPal products (HTTP {resp.status_code})",
                status_code=resp.status_code,
                details=err_data,
            )
        data = resp.json()
        return data.get("products", [])

    # --------------------------------------------------------------------------
    # Billing Plans API (/v1/billing/plans)
    # --------------------------------------------------------------------------

    async def create_plan(
        self,
        plan_payload: Dict[str, Any],
        request_id: Optional[str] = None,
        auto_activate: bool = True,
    ) -> Dict[str, Any]:
        """
        Create a reusable billing plan on PayPal.
        If created in 'CREATED' status and auto_activate is True, activates the plan to 'ACTIVE'.
        """
        resp = await self._request("POST", "/v1/billing/plans", json_body=plan_payload, request_id=request_id)
        if resp.status_code not in (200, 201):
            try:
                err_data = resp.json()
            except Exception:
                err_data = {"raw": resp.text}
            raise PayPalAPIError(
                f"Failed to create PayPal billing plan (HTTP {resp.status_code}): {err_data.get('message', 'Unknown error')}",
                status_code=resp.status_code,
                details=err_data,
            )
        plan_data = resp.json()
        plan_id = plan_data.get("id")

        # Activate if required and not already ACTIVE
        if auto_activate and plan_id and plan_data.get("status") in ("CREATED", "INACTIVE"):
            activated = await self.activate_plan(plan_id)
            if activated:
                plan_data["status"] = "ACTIVE"

        return plan_data

    async def get_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve billing plan details by ID. Returns None if 404."""
        resp = await self._request("GET", f"/v1/billing/plans/{plan_id}")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            try:
                err_data = resp.json()
            except Exception:
                err_data = {"raw": resp.text}
            raise PayPalAPIError(
                f"Failed to fetch PayPal billing plan {plan_id} (HTTP {resp.status_code})",
                status_code=resp.status_code,
                details=err_data,
            )
        return resp.json()

    async def list_plans(
        self,
        product_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> List[Dict[str, Any]]:
        """List billing plans, optionally filtered by product_id."""
        params: Dict[str, Any] = {"page": page, "page_size": page_size}
        if product_id:
            params["product_id"] = product_id

        resp = await self._request("GET", "/v1/billing/plans", params=params)
        if resp.status_code != 200:
            try:
                err_data = resp.json()
            except Exception:
                err_data = {"raw": resp.text}
            raise PayPalAPIError(
                f"Failed to list PayPal billing plans (HTTP {resp.status_code})",
                status_code=resp.status_code,
                details=err_data,
            )
        data = resp.json()
        return data.get("plans", [])

    async def activate_plan(self, plan_id: str) -> bool:
        """Activate a billing plan so it can be subscribed to."""
        resp = await self._request("POST", f"/v1/billing/plans/{plan_id}/activate")
        if resp.status_code in (200, 204):
            return True
        logger.warning("Failed to activate PayPal plan %s (HTTP %s): %s", plan_id, resp.status_code, resp.text)
        return False

    async def deactivate_plan(self, plan_id: str) -> bool:
        """Deactivate a billing plan."""
        resp = await self._request("POST", f"/v1/billing/plans/{plan_id}/deactivate")
        return resp.status_code in (200, 204)
