from fastapi import APIRouter, Security
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get(
    "/dashboard",
    dependencies=[Security(get_current_user, scopes=["admin:read"])]
)
def admin_dashboard(
    admin: User = Security(get_current_user, scopes=["admin:read"])
):
    return {
        "message": "Admin dashboard",
        "email": admin.email
    }
