"""Explicit capability boundary for an unverified Orbio management integration.

No Orbio endpoint, model, tool name, rotation or top-up API is assumed here.
Supply a separately verified adapter to implement an authorized capability.
"""

from dataclasses import dataclass
from typing import Protocol


class UnsupportedCapability(RuntimeError):
    """The provider has not supplied a verified implementation of a capability."""


@dataclass(frozen=True)
class OrbioCapabilities:
    credential_validation: bool = False
    balance_read: bool = False
    credential_rotation: bool = False
    top_up: bool = False


class OrbioAdapter(Protocol):
    @property
    def capabilities(self) -> OrbioCapabilities: ...

    async def validate_credential(self, credential_reference: str): ...

    async def get_balance(self, account_reference: str): ...

    async def rotate_credential(self, credential_reference: str, authorization_reference: str): ...

    async def top_up(self, account_reference: str, authorization_reference: str): ...


class UnsupportedOrbioAdapter:
    """Default adapter: fail closed without attempting paid or remote actions."""

    capabilities = OrbioCapabilities()

    async def validate_credential(self, credential_reference: str):
        raise UnsupportedCapability("Orbio credential validation has not been verified")

    async def get_balance(self, account_reference: str):
        raise UnsupportedCapability("Orbio balance access has not been verified")

    async def rotate_credential(self, credential_reference: str, authorization_reference: str):
        raise UnsupportedCapability("Orbio credential rotation has not been verified")

    async def top_up(self, account_reference: str, authorization_reference: str):
        raise UnsupportedCapability("Orbio top-up has not been verified")
