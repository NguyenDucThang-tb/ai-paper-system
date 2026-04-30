from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt, JWTError

from app.db.session import get_db
from app.schemas.user import UserCreate, UserResponse
from app.schemas.auth import LoginRequest, TokenResponse, RefreshTokenRequest
from app.crud.user import create_user, get_user_by_email, authenticate_user
from app.crud.refresh_token import (
    create_refresh_token as save_refresh_token,
    revoke_refresh_token,
    is_refresh_token_revoked,
    rotate_refresh_token
)
from app.core.security import (
    create_access_token,
    create_refresh_token
)
from app.core.config import settings


router = APIRouter()


def get_scopes_for_role(role: str) -> list[str]:
    return (
        ["admin:read", "admin:write", "user:read", "user:write"]
        if role == "admin"
        else ["user:read", "user:write"]
    )


def build_token_response(db: Session, user, device_id: str | None = None):
    scopes = get_scopes_for_role(user.role)

    access_token = create_access_token({
        "sub": user.email,
        "role": user.role,
        "scopes": scopes
    })

    refresh_token = create_refresh_token({
        "sub": user.email,
        "type": "refresh"
    })

    save_refresh_token(
        db=db,
        token=refresh_token,
        user_email=user.email,
        device_id=device_id or "web",
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": user,
    }

# =========================
# REGISTER
# =========================
@router.post("/register", response_model=UserResponse)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    # nếu email đã tồn tại thì sẽ báo lỗi còn ko sẽ gọi đến create_user ở crud/user.py
    if get_user_by_email(db, str(user_in.email)):
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
    # so sánh xem username và password đã có trong database chưa 
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is inactive")

    return build_token_response(db=db, user=user, device_id="oauth2-form")


@router.post("/login/email", response_model=TokenResponse)
def login_with_email(
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, str(payload.email), payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is inactive")

    return build_token_response(
        db=db,
        user=user,
        device_id=payload.device_id,
    )

# =========================
# REFRESH TOKEN
# =========================
# khi access_token(15p) thì người dùng sử dụng referesh token(7 ngày) để server cấp access_token mới
@router.post("/refresh", response_model=TokenResponse)
def refresh(data: RefreshTokenRequest, db: Session = Depends(get_db)):
    try: 
        #kiểm tra token có hợp lệ không
        payload = jwt.decode(
            data.refresh_token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )

        # ktra xem có sử dụng refresh token không ( sử dụng access token thì không được)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")

        #lấy email người dùng
        email = payload.get("sub")
        if not email:
            raise HTTPException(status_code=401, detail="Invalid token")

        user = get_user_by_email(db, email)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        #  token cũ đã revoke
        if is_refresh_token_revoked(db, data.refresh_token):
            raise HTTPException(status_code=401, detail="Refresh token revoked")

        # tạo access token mới
        new_access = create_access_token({
            "sub": email,
            "role": user.role,
            "scopes": get_scopes_for_role(user.role)
        })
        
        # tạo refresh token mới
        new_refresh = create_refresh_token({
            "sub": email,
            "type": "refresh"
        })

        # thay đổi refresh token mới (khóa lại token cũ)
        success = rotate_refresh_token(
            db=db,
            old_token=data.refresh_token,
            new_token=new_refresh,
            user_email=email,
            device_id=data.device_id or "same-device"
        )

        if not success:
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "user": user,
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
