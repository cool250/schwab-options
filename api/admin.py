"""Admin-only user management (Settings → Users). No self-service sign-up:
the admin creates accounts, resets passwords, and disables or deletes users.
Mounted with Depends(require_admin) in api/app.py."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api import users
from api.auth import require_admin
from api.users import User
from broker.schwab.auth import LEGACY_OWNER_ID, delete_user_tokens

router = APIRouter()


class CreateUserRequest(BaseModel):
    username: str
    password: str
    isAdmin: bool = False
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[str] = None


class SetPasswordRequest(BaseModel):
    password: str


class UpdateUserRequest(BaseModel):
    disabled: bool


def _get_or_404(user_id: int) -> User:
    user = users.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such user")
    return user


@router.get("/users")
def list_users():
    return [u.public() for u in users.list_users()]


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(req: CreateUserRequest):
    try:
        return users.create_user(
            req.username, req.password, is_admin=req.isAdmin,
            first_name=req.firstName, last_name=req.lastName, email=req.email,
        ).public()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/users/{user_id}/password")
def reset_password(user_id: int, req: SetPasswordRequest):
    """Set a user's password (e.g. they forgot it). Signs them out everywhere."""
    _get_or_404(user_id)
    try:
        users.set_password(user_id, req.password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"ok": True}


@router.patch("/users/{user_id}")
def update_user(user_id: int, req: UpdateUserRequest, admin: User = Depends(require_admin)):
    """Enable/disable an account. Disabling signs the user out immediately."""
    user = _get_or_404(user_id)
    if req.disabled and user.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You can't disable your own account")
    if req.disabled and user.is_admin and users.active_admin_count() <= 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Can't disable the last active admin")
    users.set_disabled(user_id, req.disabled)
    return users.get_user(user_id).public()


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin: User = Depends(require_admin)):
    """Delete an account and its stored Schwab token."""
    user = _get_or_404(user_id)
    if user.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You can't delete your own account")
    if user.id == LEGACY_OWNER_ID:
        # Owns the original token store (TOKEN_FILE); disable instead.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The original admin can't be deleted")
    if user.is_admin and users.active_admin_count() <= 1 and not user.disabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Can't delete the last active admin")
    delete_user_tokens(user.id)
    users.delete_user(user.id)
    return {"ok": True}
