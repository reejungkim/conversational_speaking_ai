"""
Authentication Router
Handles login, registration, and OAuth (Kakao, Naver)
"""
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime, timedelta
import httpx
from jose import JWTError, jwt
from passlib.context import CryptContext

from supabase import create_client, Client
import sys
sys.path.append('..')
from config import get_settings

router = APIRouter()
settings = get_settings()

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Supabase client
supabase: Client = create_client(settings.supabase_url, settings.supabase_key)


# ==================== Pydantic Models ====================

class UserLogin(BaseModel):
    """Login request model"""
    username: str
    password: str


class UserRegister(BaseModel):
    """Registration request model"""
    username: str
    email: EmailStr
    password: str
    full_name: Optional[str] = None


class TokenResponse(BaseModel):
    """Token response model"""
    access_token: str
    token_type: str = "bearer"
    user: dict


class OAuthCallback(BaseModel):
    """OAuth callback data"""
    code: str
    state: Optional[str] = None


# ==================== Helper Functions ====================

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.jwt_expiration_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash"""
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    """Hash a password"""
    return pwd_context.hash(password)


# ==================== Auth Endpoints ====================

@router.post("/login", response_model=TokenResponse)
async def login(credentials: UserLogin):
    """
    Authenticate user with username and password
    """
    try:
        # Query user from Supabase
        result = supabase.table("users").select("*").eq("username", credentials.username).execute()
        
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )
        
        user = result.data[0]
        
        # Verify password
        if not verify_password(credentials.password, user.get("password_hash", "")):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )
        
        # Create access token
        token = create_access_token(data={"sub": user["username"], "user_id": user["id"]})
        
        return TokenResponse(
            access_token=token,
            user={
                "id": user["id"],
                "username": user["username"],
                "full_name": user.get("full_name"),
                "email": user.get("email"),
                "is_admin": user.get("is_admin", False)
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login failed: {str(e)}"
        )


@router.post("/register", response_model=TokenResponse)
async def register(user_data: UserRegister):
    """
    Register a new user
    """
    try:
        # Check if username exists
        existing = supabase.table("users").select("id").eq("username", user_data.username).execute()
        if existing.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists"
            )
        
        # Check if email exists
        existing_email = supabase.table("users").select("id").eq("email", user_data.email).execute()
        if existing_email.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        
        # Create user
        new_user = supabase.table("users").insert({
            "username": user_data.username,
            "email": user_data.email,
            "password_hash": hash_password(user_data.password),
            "full_name": user_data.full_name,
            "is_admin": False,
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        
        user = new_user.data[0]
        
        # Create access token
        token = create_access_token(data={"sub": user["username"], "user_id": user["id"]})
        
        return TokenResponse(
            access_token=token,
            user={
                "id": user["id"],
                "username": user["username"],
                "full_name": user.get("full_name"),
                "email": user.get("email"),
                "is_admin": False
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}"
        )


# ==================== OAuth Endpoints ====================

@router.get("/oauth/kakao")
async def kakao_login():
    """
    Initiate Kakao OAuth login
    Returns the authorization URL to redirect the user to
    """
    if not settings.kakao_client_id:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Kakao OAuth not configured"
        )
    
    auth_url = (
        f"https://kauth.kakao.com/oauth/authorize"
        f"?client_id={settings.kakao_client_id}"
        f"&redirect_uri={settings.kakao_redirect_uri}"
        f"&response_type=code"
    )
    return {"authorization_url": auth_url}


@router.post("/oauth/kakao/callback", response_model=TokenResponse)
async def kakao_callback(callback: OAuthCallback):
    """
    Handle Kakao OAuth callback
    Exchange authorization code for access token and user info
    """
    try:
        async with httpx.AsyncClient() as client:
            # Exchange code for token
            token_response = await client.post(
                "https://kauth.kakao.com/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.kakao_client_id,
                    "client_secret": settings.kakao_client_secret,
                    "redirect_uri": settings.kakao_redirect_uri,
                    "code": callback.code
                }
            )
            token_data = token_response.json()
            
            if "error" in token_data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Kakao OAuth error: {token_data.get('error_description')}"
                )
            
            # Get user info
            user_response = await client.get(
                "https://kapi.kakao.com/v2/user/me",
                headers={"Authorization": f"Bearer {token_data['access_token']}"}
            )
            kakao_user = user_response.json()
            
            # Extract user info
            kakao_id = str(kakao_user["id"])
            kakao_account = kakao_user.get("kakao_account", {})
            profile = kakao_account.get("profile", {})
            
            email = kakao_account.get("email", f"kakao_{kakao_id}@placeholder.com")
            nickname = profile.get("nickname", f"kakao_user_{kakao_id}")
            
            # Find or create user
            existing = supabase.table("users").select("*").eq("oauth_provider", "kakao").eq("oauth_id", kakao_id).execute()
            
            if existing.data:
                user = existing.data[0]
            else:
                # Create new user
                new_user = supabase.table("users").insert({
                    "username": f"kakao_{kakao_id}",
                    "email": email,
                    "full_name": nickname,
                    "oauth_provider": "kakao",
                    "oauth_id": kakao_id,
                    "is_admin": False,
                    "created_at": datetime.utcnow().isoformat()
                }).execute()
                user = new_user.data[0]
            
            # Create JWT token
            token = create_access_token(data={"sub": user["username"], "user_id": user["id"]})
            
            return TokenResponse(
                access_token=token,
                user={
                    "id": user["id"],
                    "username": user["username"],
                    "full_name": user.get("full_name"),
                    "email": user.get("email"),
                    "oauth_provider": "kakao"
                }
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Kakao OAuth failed: {str(e)}"
        )


@router.get("/oauth/naver")
async def naver_login():
    """
    Initiate Naver OAuth login
    Returns the authorization URL to redirect the user to
    """
    if not settings.naver_client_id:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Naver OAuth not configured"
        )
    
    auth_url = (
        f"https://nid.naver.com/oauth2.0/authorize"
        f"?client_id={settings.naver_client_id}"
        f"&redirect_uri={settings.naver_redirect_uri}"
        f"&response_type=code"
        f"&state=random_state_string"
    )
    return {"authorization_url": auth_url}


@router.post("/oauth/naver/callback", response_model=TokenResponse)
async def naver_callback(callback: OAuthCallback):
    """
    Handle Naver OAuth callback
    Exchange authorization code for access token and user info
    """
    try:
        async with httpx.AsyncClient() as client:
            # Exchange code for token
            token_response = await client.post(
                "https://nid.naver.com/oauth2.0/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.naver_client_id,
                    "client_secret": settings.naver_client_secret,
                    "code": callback.code,
                    "state": callback.state
                }
            )
            token_data = token_response.json()
            
            if "error" in token_data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Naver OAuth error: {token_data.get('error_description')}"
                )
            
            # Get user info
            user_response = await client.get(
                "https://openapi.naver.com/v1/nid/me",
                headers={"Authorization": f"Bearer {token_data['access_token']}"}
            )
            naver_data = user_response.json()
            naver_user = naver_data.get("response", {})
            
            # Extract user info
            naver_id = naver_user.get("id")
            email = naver_user.get("email", f"naver_{naver_id}@placeholder.com")
            nickname = naver_user.get("nickname") or naver_user.get("name", f"naver_user_{naver_id}")
            
            # Find or create user
            existing = supabase.table("users").select("*").eq("oauth_provider", "naver").eq("oauth_id", naver_id).execute()
            
            if existing.data:
                user = existing.data[0]
            else:
                # Create new user
                new_user = supabase.table("users").insert({
                    "username": f"naver_{naver_id}",
                    "email": email,
                    "full_name": nickname,
                    "oauth_provider": "naver",
                    "oauth_id": naver_id,
                    "is_admin": False,
                    "created_at": datetime.utcnow().isoformat()
                }).execute()
                user = new_user.data[0]
            
            # Create JWT token
            token = create_access_token(data={"sub": user["username"], "user_id": user["id"]})
            
            return TokenResponse(
                access_token=token,
                user={
                    "id": user["id"],
                    "username": user["username"],
                    "full_name": user.get("full_name"),
                    "email": user.get("email"),
                    "oauth_provider": "naver"
                }
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Naver OAuth failed: {str(e)}"
        )


@router.get("/me")
async def get_current_user(token: str):
    """
    Get current user from JWT token
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        username = payload.get("sub")
        
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        result = supabase.table("users").select("*").eq("username", username).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="User not found")
        
        user = result.data[0]
        return {
            "id": user["id"],
            "username": user["username"],
            "full_name": user.get("full_name"),
            "email": user.get("email"),
            "is_admin": user.get("is_admin", False),
            "oauth_provider": user.get("oauth_provider")
        }
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
