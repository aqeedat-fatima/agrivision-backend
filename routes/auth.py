from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from database import SessionLocal
from models import User

router = APIRouter(prefix="/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class SignUpRequest(BaseModel):
    full_name: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UpdateProfileRequest(BaseModel):
    user_id: int
    full_name: str
    email: EmailStr
    phone: str | None = None
    location: str | None = None


class ChangePasswordRequest(BaseModel):
    user_id: int
    current_password: str
    new_password: str


def user_payload(user: User):
    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "location": user.location,
    }


@router.post("/signup")
def signup(req: SignUpRequest, db: Session = Depends(get_db)):
    email = req.email.lower().strip()

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    user = User(
        full_name=req.full_name.strip(),
        email=email,
        password_hash=pwd_context.hash(req.password),
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return {"message": "Account created", "user": user_payload(user)}


@router.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    email = req.email.lower().strip()

    user = db.query(User).filter(User.email == email).first()

    if not user or not pwd_context.verify(req.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Invalid email or password")

    return user_payload(user)


@router.post("/update-profile")
def update_profile(req: UpdateProfileRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == req.user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_email = req.email.lower().strip()

    existing = (
        db.query(User)
        .filter(User.email == new_email, User.id != req.user_id)
        .first()
    )

    if existing:
        raise HTTPException(status_code=400, detail="Email already used by another account")

    user.full_name = req.full_name.strip()
    user.email = new_email
    user.phone = req.phone.strip() if req.phone else None
    user.location = req.location.strip() if req.location else None

    db.commit()
    db.refresh(user)

    return {"message": "Profile updated", "user": user_payload(user)}


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == req.user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not pwd_context.verify(req.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect current password")

    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")

    user.password_hash = pwd_context.hash(req.new_password)
    db.commit()

    return {"message": "Password updated"}

class ResetPasswordRequest(BaseModel):
    email: EmailStr
    new_password: str


@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email.lower().strip()).first()

    if not user:
        raise HTTPException(status_code=404, detail="No account found with this email")

    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    user.password_hash = pwd_context.hash(req.new_password)
    db.commit()

    return {"message": "Password reset successfully"}