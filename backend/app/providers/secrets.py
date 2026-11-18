"""Secret storage backed by OS credential manager (Windows Credential Manager via keyring)."""

from abc import ABC, abstractmethod

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

KEYRING_SERVICE_NAME = "ai-engineering-agent"


def _account_name(provider_name: str) -> str:
    return f"{provider_name.strip().lower()}_api_key"


class SecretStore(ABC):
    """Abstract interface for storing and deleting provider API keys securely."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Human-readable identifier of the secret backend without sensitive details."""

    @abstractmethod
    def get_api_key(self, provider_name: str) -> str | None:
        """Retrieve stored API key for provider, or None if not configured."""

    @abstractmethod
    def set_api_key(self, provider_name: str, api_key: str) -> None:
        """Persist API key securely in the credential store."""

    @abstractmethod
    def delete_api_key(self, provider_name: str) -> None:
        """Remove API key from the credential store if present."""

    def has_api_key(self, provider_name: str) -> bool:
        """Return whether a non-empty key exists without exposing key material."""
        key = self.get_api_key(provider_name)
        return bool(key and key.strip())


class KeyringSecretStore(SecretStore):
    """Credential store delegating to Python keyring (WinVaultKeyring on Windows)."""

    def __init__(self, service_name: str = KEYRING_SERVICE_NAME) -> None:
        self._service_name = service_name

    @property
    def backend_name(self) -> str:
        """Return active keyring backend class name."""
        return type(keyring.get_keyring()).__name__

    def get_api_key(self, provider_name: str) -> str | None:
        """Read secret from OS credential vault."""
        try:
            value = keyring.get_password(self._service_name, _account_name(provider_name))
        except KeyringError as exc:
            raise RuntimeError("Failed to read credential from system keyring") from exc
        if not value or not value.strip():
            return None
        return value.strip()

    def set_api_key(self, provider_name: str, api_key: str) -> None:
        """Write secret into OS credential vault."""
        cleaned = api_key.strip()
        if not cleaned:
            raise ValueError("API key must not be empty")
        try:
            keyring.set_password(self._service_name, _account_name(provider_name), cleaned)
        except KeyringError as exc:
            raise RuntimeError("Failed to store credential in system keyring") from exc

    def delete_api_key(self, provider_name: str) -> None:
        """Delete secret from OS credential vault."""
        try:
            keyring.delete_password(self._service_name, _account_name(provider_name))
        except PasswordDeleteError:
            return
        except KeyringError as exc:
            raise RuntimeError("Failed to delete credential from system keyring") from exc
