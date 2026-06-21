from typing import Annotated, cast

from fastapi import Depends, Request

from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol


def get_interface(request: Request) -> EvernightInterfaceProtocol:
    return cast(EvernightInterfaceProtocol, request.app.state.interface)


InterfaceDependency = Annotated[EvernightInterfaceProtocol, Depends(get_interface)]
