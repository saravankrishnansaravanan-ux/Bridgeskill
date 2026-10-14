import jwt
import bcrypt
import os
from datetime import datetime, timedelta, timezone
from fastapi import Request, HTTPException, status, Depends
from fastapi.security import APIKeyCookie, APIKeyHeader

JWT_SECRET = os.getenv("JWT_SECRET", "super_secret_bridge_skill_key_2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7

cookie_sec = APIKeyCookie(name="token", auto_error=False)
header_sec = APIKeyHeader(name="Authorization", auto_error=False)

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)

def verify_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None

async def get_current_user(
    request: Request,
    cookie_token: str = Depends(cookie_sec),
    header_token: str = Depends(header_sec)
) -> dict:
    token = None
    
    # Check header first
    if header_token:
        if header_token.lower().startswith("bearer "):
            token = header_token[7:]
        else:
            token = header_token
            
    # Check cookie if header not found
    if not token and cookie_token:
        token = cookie_token
        
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please login."
        )
        
    payload = verify_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials or token expired."
        )
        
    return payload

async def get_optional_current_user(
    request: Request,
    cookie_token: str = Depends(cookie_sec),
    header_token: str = Depends(header_sec)
) -> dict | None:
    token = None
    if header_token:
        if header_token.lower().startswith("bearer "):
            token = header_token[7:]
        else:
            token = header_token
            
    if not token and cookie_token:
        token = cookie_token
        
    if not token:
        return None
        
    payload = verify_access_token(token)
    return payload

def require_role(allowed_roles: list[str]):
    async def role_checker(current_user: dict = Depends(get_current_user)):
        if current_user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden. Access limited to roles: {', '.join(allowed_roles)}"
            )
        return current_user
    return role_checker
