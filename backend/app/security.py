from datetime import datetime, timedelta, timezone
import bcrypt, jwt
from fastapi import HTTPException, status
from .config import settings
def hash_password(password: str) -> str: return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
def verify_password(password: str, hashed: str) -> bool: return bcrypt.checkpw(password.encode(), hashed.encode())
def create_token(user_id: str) -> str: return jwt.encode({'sub': user_id, 'exp': datetime.now(timezone.utc)+timedelta(minutes=settings.jwt_expire_minutes)}, settings.jwt_secret, algorithm='HS256')
def decode_token(token: str) -> str:
    try: return jwt.decode(token, settings.jwt_secret, algorithms=['HS256'])['sub']
    except jwt.PyJWTError: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid or expired token')
