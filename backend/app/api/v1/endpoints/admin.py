from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import AdminUserUpdate, UserListResponse, UserResponse

router = APIRouter()

VALID_ROLES = {"user", "admin"}

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


@router.get(
    "/users",
    response_model=UserListResponse,
    dependencies=[Security(get_current_user, scopes=["admin:read"])],
)
def list_users(
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    db: Session = Depends(get_db),
):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)

    query = db.query(User)
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            (User.email.ilike(pattern)) |
            (User.full_name.ilike(pattern))
        )
    if role:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)

    total = query.count()
    users = (
        query.order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": users,
    }


@router.patch(
    "/users/{user_id}",
    response_model=UserResponse,
    dependencies=[Security(get_current_user, scopes=["admin:write"])],
)
def update_user_by_admin(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    data = payload.model_dump(exclude_unset=True)
    if "role" in data and data["role"] not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")

    for field, value in data.items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


@router.post(
    "/users/{user_id}/activate",
    response_model=UserResponse,
    dependencies=[Security(get_current_user, scopes=["admin:write"])],
)
def activate_user(
    user_id: int,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = True
    db.commit()
    db.refresh(user)
    return user


@router.post(
    "/users/{user_id}/deactivate",
    response_model=UserResponse,
    dependencies=[Security(get_current_user, scopes=["admin:write"])],
)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Security(get_current_user, scopes=["admin:write"]),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Admin cannot deactivate own account")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    db.commit()
    db.refresh(user)
    return user
