"""Authentication endpoints for KiteConnect OAuth"""

from fastapi import APIRouter, HTTPException, Response, Request
from pydantic import BaseModel
from typing import Optional
from loguru import logger

from ..config.settings import Settings
from ..core.kite_client import KiteClient

router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory session store (use Redis in production)
_sessions: dict = {}
_kite_clients: dict = {}


class CallbackRequest(BaseModel):
    request_token: str


class UserResponse(BaseModel):
    user_id: str
    user_name: str
    email: str
    broker: str


def get_settings() -> Settings:
    return Settings()


@router.get("/login-url")
async def get_login_url():
    """Get the Kite Connect login URL."""
    config = get_settings()
    login_url = f"https://kite.zerodha.com/connect/login?api_key={config.kite_api_key}&v=3"
    return {"url": login_url}


@router.post("/callback")
async def auth_callback(request: CallbackRequest, response: Response):
    """Exchange request token for access token."""
    config = get_settings()
    
    try:
        kite = KiteClient(
            api_key=config.kite_api_key,
            access_token="",
            paper_mode=True,
            mock_mode=False
        )
        
        # Generate session
        session_data = kite.generate_session(request.request_token, config.kite_api_secret)
        access_token = session_data.get("access_token")
        
        if not access_token:
            raise HTTPException(status_code=400, detail="Failed to get access token")
        
        # Get user profile
        user_data = session_data.get("user", {})
        
        # Store session
        session_id = f"session_{user_data.get('user_id', 'unknown')}"
        _sessions[session_id] = {
            "access_token": access_token,
            "user": user_data
        }
        
        # Set session cookie
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            max_age=86400,  # 24 hours
            samesite="lax"
        )
        
        logger.info(f"User logged in: {user_data.get('user_id')}")
        
        return {
            "user": {
                "user_id": user_data.get("user_id", ""),
                "user_name": user_data.get("user_name", ""),
                "email": user_data.get("email", ""),
                "broker": user_data.get("broker", "ZERODHA")
            }
        }
        
    except Exception as e:
        logger.error(f"Auth callback failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/logout")
async def logout(request: Request, response: Response):
    """Logout and clear session."""
    session_id = request.cookies.get("session_id")
    
    if session_id and session_id in _sessions:
        del _sessions[session_id]
    
    response.delete_cookie("session_id")
    return {"message": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def get_current_user(request: Request):
    """Get current authenticated user."""
    session_id = request.cookies.get("session_id")
    
    if not session_id or session_id not in _sessions:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    session = _sessions[session_id]
    user = session.get("user", {})
    
    return UserResponse(
        user_id=user.get("user_id", ""),
        user_name=user.get("user_name", ""),
        email=user.get("email", ""),
        broker=user.get("broker", "ZERODHA")
    )


def get_access_token(request: Request) -> Optional[str]:
    """Helper to get access token from session."""
    session_id = request.cookies.get("session_id")
    if session_id and session_id in _sessions:
        return _sessions[session_id].get("access_token")
    return None


def get_any_valid_access_token() -> Optional[str]:
    """Get access token from any active session (for WebSocket use)."""
    for session_id, session_data in _sessions.items():
        token = session_data.get("access_token")
        if token:
            return token
    return None
