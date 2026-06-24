from EvernightAI.core.protocol.auth import AuthDeviceProtocol
from EvernightAI.core.schema.auth import Principal
from EvernightAI.interface.cli.schema import EvernightConfig


class CliAuthDeviceProtocol(AuthDeviceProtocol):
    def principal_for_config(self, config: EvernightConfig) -> Principal: ...

    def principal(self, credential: object) -> Principal: ...
