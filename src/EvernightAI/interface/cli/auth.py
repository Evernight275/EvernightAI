import hmac
import os

from EvernightAI.core.error.auth import AuthRequiredError
from EvernightAI.core.protocol.auth import AuthDeviceProtocol
from EvernightAI.core.schema.auth import Principal
from EvernightAI.interface.cli.protocol import CliAuthDeviceProtocol
from EvernightAI.interface.cli.schema import AuthUserConfig, EvernightConfig


class ConfigCliAuthDevice(CliAuthDeviceProtocol):
    def __init__(self, api_key_device: AuthDeviceProtocol | None = None) -> None:
        self._api_key_device = api_key_device

    def principal_for_config(self, config: EvernightConfig) -> Principal:
        api_key = os.getenv("EVERNIGHTAI_CLI_API_KEY")
        if api_key is not None and api_key != "":
            return self.principal((api_key, config))

        username = os.getenv("EVERNIGHTAI_CLI_USERNAME")
        if username is not None:
            password = os.getenv("EVERNIGHTAI_CLI_PASSWORD")
            for user in config.auth.users:
                if (
                    user.username == username
                    and user.password is not None
                    and password is not None
                    and hmac.compare_digest(user.password.encode(), password.encode())
                ):
                    return _principal_from_user(user)
            raise AuthRequiredError("Invalid CLI login credentials")
        if len(config.auth.users) == 1 and config.auth.users[0].password is not None:
            return _principal_from_user(config.auth.users[0])
        raise AuthRequiredError(
            "EVERNIGHTAI_CLI_USERNAME and EVERNIGHTAI_CLI_PASSWORD are required"
        )

    def principal(self, credential: object) -> Principal:
        if not isinstance(credential, tuple) or len(credential) != 2:
            raise AuthRequiredError("CLI authentication required")

        api_key, config = credential
        if not isinstance(api_key, str) or api_key == "":
            raise AuthRequiredError("CLI authentication required")
        if not isinstance(config, EvernightConfig):
            raise AuthRequiredError("Invalid CLI authentication config")

        if self._api_key_device is None:
            raise AuthRequiredError("Invalid CLI API key")
        return self._api_key_device.principal(api_key)


def _principal_from_user(config: AuthUserConfig) -> Principal:
    return Principal(
        principal_id=config.username,
        principal_type=config.principal_type,
        roles=config.roles,
        permissions=config.permissions,
        metadata=config.metadata,
    )
