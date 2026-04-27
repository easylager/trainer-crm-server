from .public import router as public_router
from .redirects import router as redirects_router
from .trainers import router as trainers_router
from .upload import router as upload_router
from .webapp import router as webapp_router
from .webhooks import router as webhooks_router

__all__ = [
    "public_router",
    "redirects_router",
    "trainers_router",
    "upload_router",
    "webapp_router",
    "webhooks_router",
]
