import os

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
