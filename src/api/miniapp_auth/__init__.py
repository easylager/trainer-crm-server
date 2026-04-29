"""Mini App authentication: platform-neutral principal + per-host verifiers + FastAPI deps."""

from src.api.miniapp_auth.deps import (
    MiniappCredentialIn,
    get_admin_miniapp_principal,
    get_client_miniapp_principal,
    get_trainer_miniapp_principal,
    get_trainer_miniapp_principal_multipart,
    reject_unsupported_miniapp_platform,
    require_miniapp_credential_in,
    require_miniapp_credential_in_multipart,
)
from src.api.miniapp_auth.principal_keys import client_catalog_telegram_key, trainer_legacy_telegram_id_for_storage
from src.api.miniapp_auth.telegram import verify_telegram_init_data_principal
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.api.miniapp_auth.vk_launch_params import verify_vk_miniapp_launch_principal

__all__ = [
    "MiniAppPlatform",
    "MiniAppPrincipal",
    "MiniappCredentialIn",
    "verify_telegram_init_data_principal",
    "verify_vk_miniapp_launch_principal",
    "client_catalog_telegram_key",
    "trainer_legacy_telegram_id_for_storage",
    "reject_unsupported_miniapp_platform",
    "require_miniapp_credential_in",
    "require_miniapp_credential_in_multipart",
    "get_client_miniapp_principal",
    "get_trainer_miniapp_principal",
    "get_trainer_miniapp_principal_multipart",
    "get_admin_miniapp_principal",
]
