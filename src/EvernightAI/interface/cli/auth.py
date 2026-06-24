import os

from EvernightAI.core.error.auth import AuthRequiredError
from EvernightAI.core.schema.auth import Principal
from EvernightAI.interface.cli.protocol import CliAuthDeviceProtocol
from EvernightAI.interface.cli.schema import AuthPrincipalConfig, EvernightConfig


class ConfigCliAuthDevice(CliAuthDeviceProtocol):
    def principal_for_config(self, config: EvernightConfig) -> Principal:
        api_key = os.getenv("EVERNIGHTAI_CLI_API_KEY")
        if api_key is not None and api_key != "":
            return self.principal((api_key, config))

        principals_with_key = [
            principal
            for principal in config.auth.principals
            if principal.api_key is not None
        ]
        if len(principals_with_key) == 1:
            return _principal_from_config(principals_with_key[0])

        if not principals_with_key:
            raise AuthRequiredError("CLI authentication required")

        raise AuthRequiredError("EVERNIGHTAI_CLI_API_KEY is required")

    def principal(self, credential: object) -> Principal:
        if not isinstance(credential, tuple) or len(credential) != 2:
            raise AuthRequiredError("CLI authentication required")

        api_key, config = credential
        if not isinstance(api_key, str) or api_key == "":
            raise AuthRequiredError("CLI authentication required")
        if not isinstance(config, EvernightConfig):
            raise AuthRequiredError("Invalid CLI authentication config")

        for principal in config.auth.principals:
            if principal.api_key == api_key:
                return _principal_from_config(principal)

        raise AuthRequiredError("Invalid CLI API key")


def _principal_from_config(config: AuthPrincipalConfig) -> Principal:
    return Principal(
        principal_id=config.principal_id,
        principal_type=config.principal_type,
        roles=config.roles,
        permissions=config.permissions,
        metadata=config.metadata,
    )
