"""First-class Orbio provider abstraction for VESSEL.

Implements real Orbio gateway validation, masked credential representation,
and official Remote MCP boundary for account/key self-management.
Fails closed when remote capabilities or authorizations are unavailable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

ORBIO_GATEWAY_ENDPOINT = "https://api.orbio.so/api/v1/chat/completions"
ORBIO_MODELS_ENDPOINT = "https://api.orbio.so/api/v1/models"
OPENROUTER_MODELS_ENDPOINT = ORBIO_MODELS_ENDPOINT
ORBIO_AUTH_KEY_ENDPOINT = "https://api.orbio.so/api/v1/auth/key"
OPENROUTER_AUTH_KEY_ENDPOINT = ORBIO_AUTH_KEY_ENDPOINT
ORBIO_KEY_ENDPOINT = "https://api.orbio.so/api/v1/key"
OPENROUTER_CREDITS_ENDPOINT = "https://openrouter.ai/api/v1/credits"
ORBIO_MCP_ENDPOINT = "https://www.orbio.so/api/mcp"
ROBINHOOD_ORBIO_CONTRACT = "0xAa07A0e9209e16aC99708C3EC70159c6eF3128A3"
ROBINHOOD_RPC_ENDPOINT = "https://rpc.mainnet.chain.robinhood.com"
ROBINHOOD_BLOCKSCOUT_URL = "https://robinhoodchain.blockscout.com"
DEFAULT_PROBE_MODEL = "openai/gpt-4.1-mini"
CACHE_TTL_SECONDS = 60.0


def calculate_orbio_tier(holdings: float) -> dict[str, Any]:
    """Calculate operator tier and inference entitlements based on $ORBIO token holdings."""
    if holdings >= 250_000:
        return {
            "tier": "sovereign",
            "tier_name": "Sovereign",
            "label": "Tier 3 // Sovereign",
            "min_holdings": 250_000,
            "quota_multiplier": 5.0,
            "features": ["Uncapped Concurrency", "Priority Auto-Routing", "Frontier Reasoning"],
        }
    elif holdings >= 50_000:
        return {
            "tier": "builder",
            "tier_name": "Builder",
            "label": "Tier 2 // Builder",
            "min_holdings": 50_000,
            "quota_multiplier": 2.5,
            "features": ["High Concurrency", "Smart Dynamic Routing"],
        }
    elif holdings >= 10_000:
        return {
            "tier": "explorer",
            "tier_name": "Explorer",
            "label": "Tier 1 // Explorer",
            "min_holdings": 10_000,
            "quota_multiplier": 1.0,
            "features": ["Standard Routing", "Frontier Models Access"],
        }
    else:
        return {
            "tier": "community",
            "tier_name": "Community",
            "label": "Community Tier",
            "min_holdings": 0,
            "quota_multiplier": 0.5,
            "features": ["Basic Inference"],
        }

CURATED_MODELS = [
    {
        "id": "openrouter/auto",
        "name": "OpenRouter Auto (Smart Dynamic Routing)",
        "context_length": 200000,
        "pricing": {"prompt": "Variable", "completion": "Variable"},
        "recommended": True,
        "description": "Dynamically selects the best and most cost-effective provider for each prompt.",
    },
    {
        "id": "anthropic/claude-sonnet-4.5",
        "name": "Claude Sonnet 4.5",
        "context_length": 200000,
        "pricing": {"prompt": "0.000003", "completion": "0.000015"},
        "recommended": True,
        "description": "Anthropic's flagship agentic coding and reasoning model.",
    },
    {
        "id": "anthropic/claude-3.5-sonnet",
        "name": "Claude 3.5 Sonnet",
        "context_length": 200000,
        "pricing": {"prompt": "0.000003", "completion": "0.000015"},
        "recommended": True,
        "description": "Industry benchmark for tool use, coding precision, and complex instructions.",
    },
    {
        "id": "deepseek/deepseek-r1",
        "name": "DeepSeek R1",
        "context_length": 64000,
        "pricing": {"prompt": "0.00000055", "completion": "0.00000219"},
        "recommended": True,
        "description": "Open-weight frontier reasoning model optimized for mathematical and logic rigor.",
    },
    {
        "id": "deepseek/deepseek-chat",
        "name": "DeepSeek V3",
        "context_length": 64000,
        "pricing": {"prompt": "0.00000014", "completion": "0.00000028"},
        "recommended": True,
        "description": "High-throughput, ultra-low cost coding and conversation model.",
    },
    {
        "id": "openai/gpt-4o",
        "name": "GPT-4o",
        "context_length": 128000,
        "pricing": {"prompt": "0.0000025", "completion": "0.00001"},
        "recommended": True,
        "description": "OpenAI multimodal flagship for structured outputs and complex agent workflows.",
    },
    {
        "id": "openai/gpt-4o-mini",
        "name": "GPT-4o Mini",
        "context_length": 128000,
        "pricing": {"prompt": "0.00000015", "completion": "0.0000006"},
        "recommended": False,
        "description": "Fast and economical model for small tasks and probes.",
    },
    {
        "id": "openai/gpt-4.1-mini",
        "name": "GPT-4.1 Mini",
        "context_length": 128000,
        "pricing": {"prompt": "0.0000002", "completion": "0.0000008"},
        "recommended": False,
        "description": "VESSEL default inference probe model.",
    },
]


class UnsupportedCapability(RuntimeError):
    """The provider has not supplied a verified implementation of a capability."""


class OrbioError(Exception):
    """Base error for Orbio operations. Sanitized for safety."""


class InvalidOrbioCredential(OrbioError):
    """Provider rejected the credential. Upstream bodies are never leaked."""


class OrbioManagementUnavailable(OrbioError):
    """Remote MCP account management capability is not authorized or configured."""


class OrbioNetworkError(OrbioError):
    """Connection or timeout error while contacting Orbio."""


def mask_key(key: str) -> str:
    """Return a safe masked representation of an Orbio API key.

    Examples:
        sk-orbio-abc123456789 -> sk-orbio-••••6789
        anykey12345678        -> any••••5678
        short                 -> ••••••••
    """
    if not isinstance(key, str) or len(key) < 8:
        return "••••••••"
    if key.startswith("sk-orbio-") and len(key) > 13:
        return f"sk-orbio-••••{key[-4:]}"
    if key.startswith("sk-") and len(key) > 7:
        return f"sk-••••{key[-4:]}"
    return f"{key[:3]}••••{key[-4:]}"


@dataclass(frozen=True)
class OrbioCapabilities:
    credential_validation: bool = False
    balance_read: bool = False
    credential_rotation: bool = False
    key_claim: bool = False
    top_up: bool = False
    key_management: bool = False
    usage_analytics: bool = False


class OrbioAdapter(Protocol):
    @property
    def capabilities(self) -> OrbioCapabilities: ...

    async def validate_credential(self, credential: str) -> dict[str, Any]: ...

    async def claim_key(self, name: str = "vessel-operator-key") -> dict[str, Any]: ...

    async def fetch_model_catalog(self, api_key: str | None = None) -> list[dict[str, Any]]: ...

    async def fetch_usage_analytics(self, api_key: str | None = None) -> dict[str, Any]: ...

    async def fetch_wallet_holdings(self, wallet_address: str) -> dict[str, Any]: ...

    async def get_balance(self, account_reference: str | None = None) -> dict[str, Any]: ...

    async def get_key_status(self, key_reference: str | None = None) -> dict[str, Any]: ...

    async def create_key(self, name: str, authorization_reference: str | None = None) -> dict[str, Any]: ...

    async def revoke_key(self, key_id: str, authorization_reference: str | None = None) -> dict[str, Any]: ...

    async def get_usage(self, account_reference: str | None = None) -> dict[str, Any]: ...

    async def connection_status(self, credential: str | None = None) -> dict[str, Any]: ...


class OrbioGatewayClient:
    """Direct inference gateway client for validating Orbio API keys.

    Uses the minimal safe request: a 16-token prompt asking for READY.
    Never sends project contents, and never exposes provider response bodies.
    """

    def __init__(
        self,
        endpoint: str = ORBIO_GATEWAY_ENDPOINT,
        probe_model: str = DEFAULT_PROBE_MODEL,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.endpoint = endpoint
        self.probe_model = probe_model
        self.timeout = timeout
        self.transport = transport

    async def validate(self, api_key: str) -> dict[str, Any]:
        if not isinstance(api_key, str) or not 1 <= len(api_key) <= 8192 or any(c.isspace() for c in api_key):
            raise InvalidOrbioCredential("Invalid provider credential format.")

        payload = {
            "model": self.probe_model,
            "messages": [{"role": "user", "content": "Reply with exactly READY."}],
            "max_tokens": 16,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "VESSEL-Inference-Probe/1.0",
        }

        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout) as client:
                response = await client.post(self.endpoint, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise OrbioNetworkError("Orbio gateway request timed out.") from exc
        except httpx.RequestError as exc:
            raise OrbioNetworkError("Could not connect to Orbio gateway.") from exc

        if response.status_code in (401, 403):
            raise InvalidOrbioCredential("Provider rejected credential: unauthorized.")
        if response.status_code != 200:
            raise InvalidOrbioCredential("Provider rejected inference probe.")

        try:
            body = response.json()
            if (
                body.get("model") != self.probe_model
                or not body.get("choices")
                or body["choices"][0].get("finish_reason") != "stop"
                or body["choices"][0].get("message", {}).get("content", "").strip() != "READY"
            ):
                raise InvalidOrbioCredential("Provider returned unexpected probe response.")
        except (ValueError, KeyError, IndexError) as exc:
            raise InvalidOrbioCredential("Malformed provider response.") from exc

        return {
            "valid": True,
            "verified_at": time.time(),
            "model": self.probe_model,
            "masked_key": mask_key(api_key),
        }


class OrbioRemoteMCPClient:
    """Client for official Orbio Remote MCP account and key management.

    Documented capabilities:
      - orbio_get_balance
      - orbio_create_key
      - orbio_get_key_status
      - orbio_revoke_key

    If MCP authorization is not configured in the current environment,
    this client fails closed and reports capability unavailable.
    """

    def __init__(
        self,
        mcp_endpoint: str | None = None,
        mcp_auth_token: str | None = None,
        transport: Any | None = None,
    ):
        import os
        self.mcp_endpoint = mcp_endpoint or os.environ.get("ORBIO_MCP_URL") or ORBIO_MCP_ENDPOINT
        self.mcp_auth_token = mcp_auth_token or os.environ.get("ORBIO_MCP_TOKEN")
        self.transport = transport

    @property
    def is_configured(self) -> bool:
        return bool(self.mcp_endpoint and self.mcp_auth_token)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.is_configured:
            raise OrbioManagementUnavailable("Orbio Remote MCP authorization is not configured.")

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments or {}},
            "id": 1,
        }
        headers = {
            "Authorization": f"Bearer {self.mcp_auth_token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=15.0) as client:
                response = await client.post(self.mcp_endpoint, headers=headers, json=payload)  # type: ignore
        except Exception as exc:
            raise OrbioNetworkError("Failed to reach Orbio Remote MCP server.") from exc

        if response.status_code in (401, 403):
            raise OrbioManagementUnavailable("Orbio Remote MCP authorization was rejected.")
        if response.status_code != 200:
            raise OrbioManagementUnavailable("Orbio Remote MCP tool call failed.")

        try:
            data = response.json()
            if "error" in data:
                raise OrbioManagementUnavailable("Orbio Remote MCP reported an error.")
            return data.get("result", {})
        except Exception as exc:
            raise OrbioManagementUnavailable("Invalid response from Orbio Remote MCP.") from exc

    async def get_balance(self) -> dict[str, Any]:
        if not self.is_configured:
            return {
                "available": False,
                "amount": None,
                "currency": "CREDIT",
                "reason": "Not available without Orbio Remote MCP authorization",
            }
        result = await self.call_tool("orbio_get_balance")
        return {
            "available": True,
            "amount": result.get("balance"),
            "currency": result.get("currency", "CREDIT"),
            "updated_at": time.time(),
        }

    async def get_key_status(self, key_id: str | None = None) -> dict[str, Any]:
        if not self.is_configured:
            return {
                "available": False,
                "status": "active_inference_only",
                "reason": "Remote key inspection requires Orbio Remote MCP",
            }
        args = {"key_id": key_id} if key_id else {}
        result = await self.call_tool("orbio_get_key_status", args)
        return {
            "available": True,
            "status": result.get("status", "unknown"),
            "created_at": result.get("created_at"),
            "expires_at": result.get("expires_at"),
        }

    async def create_key(self, name: str) -> dict[str, Any]:
        if not self.is_configured:
            raise OrbioManagementUnavailable("Cannot create keys without Orbio Remote MCP authorization.")
        result = await self.call_tool("orbio_create_key", {"name": name})
        return result

    async def claim_key(self, name: str = "vessel-operator-key") -> dict[str, Any]:
        if not self.is_configured:
            raise OrbioManagementUnavailable("Cannot claim keys without Orbio Remote MCP authorization.")
        result = await self.call_tool("orbio_claim_key", {"name": name})
        return result

    async def revoke_key(self, key_id: str) -> dict[str, Any]:
        if not self.is_configured:
            raise OrbioManagementUnavailable("Cannot revoke keys without Orbio Remote MCP authorization.")
        result = await self.call_tool("orbio_revoke_key", {"key_id": key_id})
        return result


class RealOrbioAdapter:
    """Production Orbio adapter providing real gateway validation and MCP management."""

    def __init__(
        self,
        gateway_client: OrbioGatewayClient | None = None,
        mcp_client: OrbioRemoteMCPClient | None = None,
        clock: Any = time.time,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.gateway = gateway_client or OrbioGatewayClient(transport=transport)
        self.mcp = mcp_client or OrbioRemoteMCPClient(transport=transport)
        self.clock = clock
        self.transport = transport
        self._cache: dict[str, tuple[float, Any]] = {}

    @property
    def capabilities(self) -> OrbioCapabilities:
        return OrbioCapabilities(
            credential_validation=True,
            balance_read=self.mcp.is_configured,
            credential_rotation=self.mcp.is_configured,
            key_claim=self.mcp.is_configured,
            top_up=False,
            key_management=self.mcp.is_configured,
            usage_analytics=True,
        )

    async def claim_key(self, name: str = "vessel-operator-key") -> dict[str, Any]:
        if not self.mcp.is_configured:
            return {
                "success": False,
                "status": "mcp_not_configured",
                "message": "Orbio Remote MCP is not configured. Connect your wallet at https://orbio.so to stake $ORBIO and claim a key, or enter your sk-or-v1-... key manually.",
                "url": "https://orbio.so",
            }
        try:
            result = await self.mcp.claim_key(name)
            key = result.get("key") or result.get("api_key")
            if key and isinstance(key, str):
                return {
                    "success": True,
                    "status": "claimed",
                    "key": key,
                    "masked_key": mask_key(key),
                    "name": name,
                }
            return {
                "success": False,
                "status": "claim_failed",
                "message": result.get("message", "MCP did not return a valid key."),
            }
        except OrbioManagementUnavailable as exc:
            return {
                "success": False,
                "status": "mcp_unavailable",
                "message": str(exc),
                "url": "https://orbio.so",
            }

    async def fetch_model_catalog(self, api_key: str | None = None) -> list[dict[str, Any]]:
        cached = self._get_cached("model_catalog")
        if cached is not None:
            return cached

        models_list: list[dict[str, Any]] = [dict(m) for m in CURATED_MODELS]
        curated_ids = {m["id"] for m in CURATED_MODELS}

        try:
            headers = {"User-Agent": "VESSEL-Inference-Probe/1.0"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(ORBIO_MODELS_ENDPOINT, headers=headers)
                if resp.status_code == 200:
                    raw_data = resp.json().get("data", [])
                    for item in raw_data:
                        m_id = item.get("id")
                        if not m_id or m_id in curated_ids:
                            continue
                        raw_pricing = item.get("pricing")
                        pricing = {"prompt": "Variable", "completion": "Variable"}
                        if isinstance(raw_pricing, dict):
                            pricing["prompt"] = str(raw_pricing.get("prompt") if raw_pricing.get("prompt") is not None else "Variable")
                            pricing["completion"] = str(raw_pricing.get("completion") if raw_pricing.get("completion") is not None else "Variable")
                        models_list.append({
                            "id": m_id,
                            "name": item.get("name") or m_id,
                            "context_length": int(item.get("context_length", 32000) or 32000),
                            "pricing": pricing,
                            "recommended": False,
                            "description": item.get("description", "") or "",
                        })
        except Exception:
            pass

        self._set_cached("model_catalog", models_list)
        return models_list

    def _get_cached(self, key: str) -> Any | None:
        if key in self._cache:
            ts, value = self._cache[key]
            if self.clock() - ts < CACHE_TTL_SECONDS:
                return value
            del self._cache[key]
        return None

    def _set_cached(self, key: str, value: Any) -> None:
        self._cache[key] = (self.clock(), value)

    def clear_cache(self) -> None:
        self._cache.clear()

    async def validate_credential(self, credential: str) -> dict[str, Any]:
        result = await self.gateway.validate(credential)
        self._set_cached(f"val_{mask_key(credential)}", result)
        return result

    async def get_balance(self, account_reference: str | None = None) -> dict[str, Any]:
        cached = self._get_cached(f"balance_{mask_key(account_reference) if account_reference else 'default'}")
        if cached is not None:
            return cached
        if self.mcp.is_configured:
            try:
                balance = await self.mcp.get_balance()
                if balance.get("available"):
                    self._set_cached(f"balance_{mask_key(account_reference) if account_reference else 'default'}", balance)
                    return balance
            except Exception:
                pass
        if account_reference:
            analytics = await self.fetch_usage_analytics(account_reference)
            if analytics.get("available") and analytics.get("remaining_credits") is not None:
                balance = {
                    "available": True,
                    "amount": analytics.get("remaining_credits"),
                    "currency": "USD",
                    "reason": None,
                    "updated_at": self.clock(),
                }
                self._set_cached(f"balance_{mask_key(account_reference) if account_reference else 'default'}", balance)
                return balance
        return {
            "available": False,
            "amount": None,
            "currency": "CREDIT",
            "reason": "Not available without Orbio Remote MCP authorization",
        }

    async def get_key_status(self, key_reference: str | None = None) -> dict[str, Any]:
        cache_key = f"status_{key_reference or 'default'}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached
        status = await self.mcp.get_key_status(key_reference)
        self._set_cached(cache_key, status)
        return status

    async def create_key(self, name: str, authorization_reference: str | None = None) -> dict[str, Any]:
        return await self.mcp.create_key(name)

    async def revoke_key(self, key_id: str, authorization_reference: str | None = None) -> dict[str, Any]:
        self.clear_cache()
        return await self.mcp.revoke_key(key_id)

    async def fetch_usage_analytics(self, api_key: str | None = None) -> dict[str, Any]:
        """Fetch live credit balance and consumption analytics for an Orbio key."""
        if not api_key:
            return {
                "available": False,
                "reason": "No Orbio API key configured",
                "usage": 0.0,
                "total_credits": None,
                "remaining_credits": None,
                "percent_used": 0.0,
                "limit": None,
                "rate_limits": {
                    "requests_per_minute": 120,
                    "tokens_per_minute": 60000,
                    "concurrent": 32,
                },
                "rate_limit": None,
                "label": None,
            }

        cached = self._get_cached(f"usage_{mask_key(api_key)}")
        if cached is not None:
            return cached

        usage_val = 0.0
        usage_known = False
        remaining_known = False
        observed = False
        total_credits_val = None
        remaining_val = 0.0
        limit_val = None
        rate_limit_val = None
        rpm_val = 120
        tpm_val = 60000
        concurrent_val = 32
        label_val = None
        is_free = False

        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://vessel-dashboard.cloud-ip.cc",
                "X-Title": "VESSEL Agent Continuity",
            }
            async with httpx.AsyncClient(timeout=10.0, transport=self.transport) as client:
                # Query 1: Orbio auth/key endpoint
                resp_key = await client.get(ORBIO_AUTH_KEY_ENDPOINT, headers=headers)
                if resp_key.status_code == 200:
                    k_data = resp_key.json().get("data", {})
                    observed = observed or any(k_data.get(k) is not None for k in ("usage", "limit", "limit_remaining"))
                    usage_known = usage_known or k_data.get("usage") is not None
                    remaining_known = remaining_known or k_data.get("limit_remaining") is not None
                    usage_val = float(k_data.get("usage", 0.0) or 0.0)
                    limit_val = k_data.get("limit")
                    remaining_val = float(k_data.get("limit_remaining", 0.0) or 0.0)
                    is_free = bool(k_data.get("is_free_tier", False))
                    rate_limit_val = k_data.get("rate_limit")
                    label_val = k_data.get("label")
                    if isinstance(rate_limit_val, dict):
                        rpm_val = int(rate_limit_val.get("requests", 120) or 120)

                # Query 2: OpenRouter credits endpoint
                resp_cred = await client.get(OPENROUTER_CREDITS_ENDPOINT, headers=headers)
                if resp_cred.status_code == 200:
                    c_data = resp_cred.json().get("data", {})
                    if "total_credits" in c_data and c_data["total_credits"] is not None:
                        observed = True
                        total_credits_val = float(c_data["total_credits"])

                # Query 3: Orbio v1/key endpoint for exact balance object and concurrency
                resp_v1 = await client.get(ORBIO_KEY_ENDPOINT, headers=headers)
                if resp_v1.status_code == 200:
                    v1_data = resp_v1.json()
                    bal = v1_data.get("balance", {})
                    if "available" in bal:
                        observed = True
                        remaining_known = True
                        remaining_val = float(bal.get("available", remaining_val) or remaining_val)
                    if "used" in bal:
                        observed = True
                        usage_known = True
                        usage_val = float(bal.get("used", usage_val) or usage_val)
                    rd = v1_data.get("rate_limit", {})
                    if isinstance(rd, dict):
                        rpm_val = int(rd.get("requests_per_minute", rpm_val) or rpm_val)
                        concurrent_val = int(rd.get("concurrent", concurrent_val) or concurrent_val)
        except Exception:
            pass

        if not observed:
            return {
                "available": False,
                "reason": "Credit telemetry could not be verified",
                "usage": None,
                "total_credits": None,
                "remaining_credits": None,
                "percent_used": None,
                "limit": None,
                "rate_limits": None,
                "rate_limit": None,
                "label": None,
            }

        if total_credits_val is None:
            if limit_val is not None and float(limit_val) > 0:
                total_credits_val = float(limit_val)
            elif remaining_known and usage_known:
                total_credits_val = round(remaining_val + usage_val, 4)

        remaining = (
            round(remaining_val, 4) if remaining_known
            else round(max(0.0, total_credits_val - usage_val), 4)
            if total_credits_val is not None and usage_known else None
        )
        pct = (
            round(min(100.0, (usage_val / total_credits_val) * 100.0), 1)
            if (total_credits_val and total_credits_val > 0 and usage_known)
            else None
        )

        rate_limits = {
            "requests_per_minute": rpm_val,
            "tokens_per_minute": tpm_val,
            "concurrent": concurrent_val,
        }

        analytics = {
            "available": True,
            "usage": round(usage_val, 4) if usage_known else None,
            "total_credits": round(total_credits_val, 4) if total_credits_val is not None else None,
            "remaining_credits": remaining,
            "percent_used": pct,
            "limit": limit_val,
            "rate_limits": rate_limits,
            "rate_limit": rate_limit_val or rate_limits,
            "is_free_tier": is_free,
            "label": label_val,
            "checked_at": self.clock(),
        }
        self._set_cached(f"usage_{mask_key(api_key)}", analytics)
        return analytics

    async def fetch_wallet_holdings(self, wallet_address: str) -> dict[str, Any]:
        """Verify Robinhood Chain (EVM) wallet address and calculate $ORBIO holding tier."""
        import re

        if not wallet_address:
            return {
                "valid": False,
                "error": "Wallet address is required.",
                "wallet_address": "",
                "holdings": 0.0,
                **calculate_orbio_tier(0.0),
            }

        is_evm = bool(re.match(r"^0x[a-fA-F0-9]{40}$", wallet_address))
        if not is_evm:
            return {
                "valid": False,
                "error": "Invalid Robinhood Chain address. Must be a 42-character 0x hex address.",
                "wallet_address": wallet_address,
                "holdings": 0.0,
                **calculate_orbio_tier(0.0),
            }

        cached = self._get_cached(f"wallet_{wallet_address}")
        if cached is not None:
            return cached

        holdings_val = None
        network = "Robinhood Chain"

        # Query live $ORBIO ERC-20 balance on Robinhood Chain
        try:
            padded_addr = wallet_address.lower().replace("0x", "").rjust(64, "0")
            call_data = f"0x70a08231{padded_addr}"  # balanceOf(address)
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_call",
                "params": [
                    {
                        "to": ROBINHOOD_ORBIO_CONTRACT,
                        "data": call_data,
                    },
                    "latest",
                ],
            }
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "VESSEL-Agent/1.0",
            }
            async with httpx.AsyncClient(timeout=8.0, transport=self.transport) as client:
                resp = await client.post(ROBINHOOD_RPC_ENDPOINT, json=payload, headers=headers)
                if resp.status_code == 200:
                    raw_result = resp.json().get("result")
                    if isinstance(raw_result, str) and raw_result.startswith("0x"):
                        int_balance = int(raw_result, 16)
                        holdings_val = round(int_balance / 1e18, 4)
        except Exception:
            pass

        tier_info = calculate_orbio_tier(holdings_val) if holdings_val is not None else None
        tier_number = {"sovereign": 3, "builder": 2, "explorer": 1}.get(tier_info["tier"], 0) if tier_info else None

        tier_perks = {
            "multiplier": tier_info["quota_multiplier"],
            "routing_priority": tier_info["features"][0] if tier_info["features"] else "Standard",
            "description": ", ".join(tier_info["features"]),
        } if tier_info else None

        explorer_url = f"{ROBINHOOD_BLOCKSCOUT_URL}/token/{ROBINHOOD_ORBIO_CONTRACT}?a={wallet_address}"

        result = {
            "valid": True,
            "available": holdings_val is not None,
            "reason": None if holdings_val is not None else "Robinhood Chain balance lookup is unavailable",
            "network": network,
            "wallet_address": wallet_address,
            "masked_wallet": f"{wallet_address[:6]}...{wallet_address[-4:]}" if len(wallet_address) > 10 else wallet_address,
            "holdings": holdings_val,
            "explorer_url": explorer_url,
            "tier": tier_info["tier"] if tier_info else None,
            "tier_level": tier_number,
            "tier_name": tier_info["tier_name"] if tier_info else None,
            "label": tier_info["label"] if tier_info else None,
            "min_holdings": tier_info["min_holdings"] if tier_info else None,
            "quota_multiplier": tier_info["quota_multiplier"] if tier_info else None,
            "features": tier_info["features"] if tier_info else [],
            "tier_perks": tier_perks,
            "checked_at": self.clock(),
        }
        self._set_cached(f"wallet_{wallet_address}", result)
        return result

    async def get_usage(self, account_reference: str | None = None) -> dict[str, Any]:
        return await self.fetch_usage_analytics(account_reference)

    async def connection_status(self, credential: str | None = None) -> dict[str, Any]:
        cached = self._get_cached(f"conn_{mask_key(credential) if credential else 'none'}")
        if cached is not None:
            return cached

        balance_info = await self.get_balance(credential)
        status: dict[str, Any] = {
            "gateway": {
                "endpoint": self.gateway.endpoint,
                "model": self.gateway.probe_model,
                "status": "ready" if credential else "unconfigured",
            },
            "mcp": {
                "configured": self.mcp.is_configured,
                "capabilities": [
                    "orbio_get_balance",
                    "orbio_claim_key",
                    "orbio_create_key",
                    "orbio_get_key_status",
                    "orbio_revoke_key",
                ]
                if self.mcp.is_configured
                else [],
            },
            "balance": balance_info,
            "checked_at": self.clock(),
        }
        self._set_cached(f"conn_{mask_key(credential) if credential else 'none'}", status)
        return status


class UnsupportedOrbioAdapter:
    """Legacy fail-closed adapter for environments with no verified Orbio adapter."""

    capabilities = OrbioCapabilities()

    async def validate_credential(self, credential_reference: str) -> None:
        raise UnsupportedCapability("Orbio credential validation has not been verified")

    async def get_balance(self, account_reference: str | None = None) -> None:
        raise UnsupportedCapability("Orbio balance access has not been verified")

    async def rotate_credential(self, credential_reference: str, authorization_reference: str) -> None:
        raise UnsupportedCapability("Orbio credential rotation has not been verified")

    async def top_up(self, account_reference: str, authorization_reference: str) -> None:
        raise UnsupportedCapability("Orbio top-up has not been verified")

    async def fetch_usage_analytics(self, api_key: str) -> dict[str, Any]:
        raise UnsupportedCapability("Orbio usage analytics has not been verified")

    async def fetch_wallet_holdings(self, wallet_address: str) -> dict[str, Any]:
        raise UnsupportedCapability("Orbio wallet holdings has not been verified")
