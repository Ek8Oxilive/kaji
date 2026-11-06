from collections.abc import Callable

from .proxmox import ProxmoxClient


def get_client_factory() -> Callable[..., ProxmoxClient]:
    """Fabrique de clients Proxmox (surchargée dans les tests)."""
    return ProxmoxClient
