"""
auth.py — Demo Mode (No Authentication)
=========================================
In the demo interface, authentication is disabled.
All endpoints return success so users can explore freely.
"""

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginRequest, response: Response):
    """Always succeeds in demo mode."""
    return {"status": "ok", "message": "Demo mode — no login required"}


@router.get("/check")
def check_auth(request: Request):
    """Always returns authenticated in demo mode."""
    return {"status": "ok", "user": "Demo User"}


@router.post("/logout")
def logout(request: Request, response: Response):
    """No-op in demo mode."""
    return {"status": "ok"}
