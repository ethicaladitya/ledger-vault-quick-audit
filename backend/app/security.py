import base64, hashlib, hmac, json, os, secrets, time
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from .database import get_db
from .models import User

JWT_SECRET = os.getenv("JWT_SECRET", "replace-this-secret-in-production")
bearer = HTTPBearer(auto_error=False)
def hash_password(password: str) -> str:
    salt=secrets.token_bytes(16); digest=hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1); return "scrypt$"+base64.urlsafe_b64encode(salt).decode()+"$"+base64.urlsafe_b64encode(digest).decode()
def verify_password(password: str, encoded: str) -> bool:
    try:
        _, salt, digest=encoded.split("$"); salt_b=base64.urlsafe_b64decode(salt); expected=base64.urlsafe_b64decode(digest); actual=hashlib.scrypt(password.encode(), salt=salt_b, n=2**14, r=8, p=1); return hmac.compare_digest(actual, expected)
    except Exception: return False
def token_for(user: User) -> str:
    payload={"sub":user.id,"workspace_id":user.workspace_id,"role":user.role,"exp":int(time.time())+86400}; raw=base64.urlsafe_b64encode(json.dumps(payload,separators=(",", ":")).encode()).decode().rstrip("="); sig=hmac.new(JWT_SECRET.encode(),raw.encode(),hashlib.sha256).hexdigest(); return raw+"."+sig
def current_user(credentials: HTTPAuthorizationCredentials|None=Depends(bearer), db: Session=Depends(get_db)) -> User:
    if not credentials: raise HTTPException(401,"Login required")
    try:
        raw,sig=credentials.credentials.split(".")
        if not hmac.compare_digest(sig,hmac.new(JWT_SECRET.encode(),raw.encode(),hashlib.sha256).hexdigest()): raise ValueError()
        payload=json.loads(base64.urlsafe_b64decode(raw+"=="))
        if payload["exp"]<time.time(): raise ValueError()
        user=db.get(User,int(payload["sub"]))
        if not user or not user.is_active: raise ValueError()
        return user
    except Exception: raise HTTPException(401,"Invalid or expired session")
