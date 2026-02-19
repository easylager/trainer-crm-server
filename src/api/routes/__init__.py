from .public import router as public_router
from .trainers import router as trainers_router
from .upload import router as upload_router

__all__ = ["public_router", "trainers_router", "upload_router"]
