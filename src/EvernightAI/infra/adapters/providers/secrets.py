import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from EvernightAI.core.error.provider import ProviderConfigurationError
from EvernightAI.core.protocol.provider import ProviderSecretResolverProtocol


class EnvironmentProviderSecretResolver(ProviderSecretResolverProtocol):
    PREFIX = "env:"

    def resolve(self, secret_ref: str) -> str:
        if not secret_ref.startswith(self.PREFIX):
            raise ProviderConfigurationError(
                "Provider secret references must use the env:VARIABLE format"
            )
        variable = secret_ref.removeprefix(self.PREFIX)
        if not variable:
            raise ProviderConfigurationError(
                "Provider environment secret reference is empty"
            )
        value = os.getenv(variable)
        if value is None or value == "":
            raise ProviderConfigurationError(
                f"Provider secret environment variable {variable} is not set"
            )
        return value


class LocalProviderSecretCipher:
    PREFIX = "encrypted:"

    def __init__(self, database_path: str | Path) -> None:
        self._key_path = (
            Path(f"{database_path}.provider-key")
            if str(database_path) != ":memory:"
            else None
        )
        self._memory_key: bytes | None = None

    def encrypt(self, secret: str, *, allow_create: bool) -> str:
        token = self._cipher(allow_create=allow_create).encrypt(secret.encode("utf-8"))
        return self.PREFIX + token.decode("ascii")

    def decrypt(self, secret_ref: str) -> str:
        try:
            return (
                self._cipher(allow_create=False)
                .decrypt(secret_ref.removeprefix(self.PREFIX).encode("ascii"))
                .decode("utf-8")
            )
        except (InvalidToken, UnicodeError) as exc:
            raise ProviderConfigurationError(
                "The saved provider credential cannot be decrypted"
            ) from exc

    def _cipher(self, *, allow_create: bool) -> Fernet:
        try:
            if self._key_path is None:
                if self._memory_key is None:
                    self._memory_key = Fernet.generate_key()
                return Fernet(self._memory_key)
            if allow_create:
                try:
                    descriptor = os.open(
                        self._key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                    )
                except FileExistsError:
                    pass
                else:
                    with os.fdopen(descriptor, "wb") as file:
                        file.write(Fernet.generate_key())
                        file.flush()
                        os.fsync(file.fileno())
            return Fernet(self._key_path.read_bytes())
        except (OSError, ValueError) as exc:
            raise ProviderConfigurationError(
                "The provider credential key file is missing, invalid or inaccessible; "
                "restore the .provider-key file alongside the database"
            ) from exc
