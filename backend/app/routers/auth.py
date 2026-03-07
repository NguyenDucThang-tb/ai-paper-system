from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt, JWTError
import uuid

from app.db.session import get_db
from app.schemas.user import UserCreate, UserResponse
from app.schemas.auth import TokenResponse, RefreshTokenRequest
from app.crud.user import create_user, get_user_by_email, authenticate_user
from app.crud.refresh_token import (
    create_refresh_token as save_refresh_token,
    revoke_refresh_token,
    is_refresh_token_revoked
)
from app.core.security import (
    create_access_token,
    create_refresh_token
)
from app.core.config import settings
from app.crud.refresh_token import (
    create_refresh_token as save_refresh_token,
    revoke_refresh_token,
    is_refresh_token_revoked,
    rotate_refresh_token
)


router = APIRouter()

# =========================
# REGISTER
# =========================
@router.post("/register", response_model=UserResponse)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    if get_user_by_email(db, user_in.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    return create_user(db, user_in)

# =========================
# LOGIN
# =========================
@router.post("/login", response_model=TokenResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    scopes = (
        ["admin:read", "admin:write", "user:read", "user:write"]
        if user.role == "admin"
        else ["user:read", "user:write"]
    )

    access_token = create_access_token({
        "sub": user.email,
        "role": user.role,
        "scopes": scopes
    })

    refresh_token = create_refresh_token({
        "sub": user.email,
        "type": "refresh"
    })

    device_id = "thang" #str(uuid.uuid4())  # 👈 mỗi device 1 token

    save_refresh_token(
        db=db,
        token=refresh_token,
        user_email=user.email,
        device_id=device_id
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

# =========================
# REFRESH TOKEN
# =========================
@router.post("/refresh", response_model=TokenResponse)
def refresh(data: RefreshTokenRequest, db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(
            data.refresh_token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )

        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")

        email = payload.get("sub")
        if not email:
            raise HTTPException(status_code=401, detail="Invalid token")

        # 🔒 token cũ đã revoke?
        if is_refresh_token_revoked(db, data.refresh_token):
            raise HTTPException(status_code=401, detail="Refresh token revoked")

        new_access = create_access_token({"sub": email})

        new_refresh = create_refresh_token({
            "sub": email,
            "type": "refresh"
        })

        # 🔁 ROTATE
        success = rotate_refresh_token(
            db=db,
            old_token=data.refresh_token,
            new_token=new_refresh,
            user_email=email,
            device_id="same-device"
        )

        if not success:
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer"
        }

    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

# =========================
# LOGOUT
# =========================
@router.post("/logout")
def logout(data: RefreshTokenRequest, db: Session = Depends(get_db)):
    revoked = revoke_refresh_token(db, data.refresh_token)
    if not revoked:
        raise HTTPException(status_code=400, detail="Invalid refresh token")
    return {"message": "Logged out successfully"}
