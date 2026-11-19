import os
import base64
import logging
from typing import Optional, List
from fastapi import FastAPI, Request, Response, HTTPException, status, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from .zot_client import ZotClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("zotdeck")

app = FastAPI(
    title="ZotDeck",
    description="Lightweight Web Dashboard & Credential Manager for Zot OCI Registry",
    version="1.0.0"
)

# Static & Templates setup
current_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(current_dir, "static")
templates_dir = os.path.join(current_dir, "templates")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates = Jinja2Templates(directory=templates_dir)
zot = ZotClient()

# Schemas
class LoginRequest(BaseModel):
    username: str
    password: str

class CreateKeyRequest(BaseModel):
    label: str
    scopes: Optional[List[str]] = None
    expirationDate: Optional[str] = None

def get_auth_token(request: Request) -> str:
    """Extracts credentials token from session cookie or Authorization header."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Basic "):
        return auth_header.split(" ", 1)[1]

    session_cookie = request.cookies.get("zotdeck_auth")
    if session_cookie:
        return session_cookie

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    """Renders the main dashboard page."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_name": "ZotDeck",
            "version": "1.0.0",
            "registry_host": zot.public_url
        }
    )

# --- Auth APIs ---

@app.post("/api/auth/login")
async def login(req: LoginRequest, response: Response):
    """Validates user against Zot backend and returns session token."""
    raw_cred = f"{req.username}:{req.password}"
    encoded = base64.b64encode(raw_cred.encode()).decode()

    valid = await zot.verify_credentials(encoded)
    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    # Set cookie valid for 7 days
    response.set_cookie(
        key="zotdeck_auth",
        value=encoded,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7
    )
    return {"status": "success", "username": req.username}

@app.post("/api/auth/logout")
async def logout(response: Response):
    """Logs out by clearing the session cookie."""
    response.delete_cookie(key="zotdeck_auth")
    return {"status": "logged_out"}

@app.get("/api/auth/me")
async def get_current_user(token: str = Depends(get_auth_token)):
    """Returns current user details if session is valid."""
    try:
        decoded = base64.b64decode(token).decode()
        username = decoded.split(":", 1)[0]
        return {"username": username, "authenticated": True}
    except Exception:
        raise HTTPException(status_code=401, detail="Malformed session")

# --- Key Management APIs ---

@app.get("/api/keys")
async def list_keys(token: str = Depends(get_auth_token)):
    """Lists all active application API keys."""
    try:
        keys = await zot.list_keys(token)
        return {"apiKeys": keys}
    except PermissionError:
        raise HTTPException(status_code=401, detail="Invalid session credentials")
    except Exception as e:
        logger.error(f"Error fetching keys: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/keys")
async def create_key(req: CreateKeyRequest, token: str = Depends(get_auth_token)):
    """Generates a new API key."""
    try:
        result = await zot.create_key(
            auth_token=token,
            label=req.label,
            scopes=req.scopes,
            expiration_date=req.expirationDate
        )
        return result
    except PermissionError:
        raise HTTPException(status_code=401, detail="Unauthorized")
    except Exception as e:
        logger.error(f"Error creating key: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/keys/{key_uuid}")
async def revoke_key(key_uuid: str, token: str = Depends(get_auth_token)):
    """Immediately revokes an API key."""
    try:
        success = await zot.revoke_key(token, key_uuid)
        if success:
            return {"status": "revoked", "uuid": key_uuid}
        raise HTTPException(status_code=404, detail="Key not found or could not be revoked")
    except PermissionError:
        raise HTTPException(status_code=401, detail="Unauthorized")

# --- Registry & Image APIs ---

@app.get("/api/repositories")
async def list_repositories(token: str = Depends(get_auth_token)):
    """Lists repositories and tags."""
    try:
        repos = await zot.list_repositories(token)
        return {"repositories": repos}
    except Exception as e:
        logger.error(f"Error fetching repositories: {e}")
        return {"repositories": []}

@app.get("/api/repositories/{repo:path}/tags/{tag}")
async def get_tag_info(repo: str, tag: str, token: str = Depends(get_auth_token)):
    """Fetches size, digest, and layer metadata for a specific tag."""
    details = await zot.get_tag_manifest(token, repo, tag)
    if not details:
        raise HTTPException(status_code=404, detail="Tag not found")
    return details

@app.delete("/api/repositories/{repo:path}/tags/{tag}")
async def delete_image_tag(repo: str, tag: str, token: str = Depends(get_auth_token)):
    """Deletes an image tag / manifest from the registry."""
    success = await zot.delete_tag(token, repo, tag)
    if success:
        return {"status": "deleted", "repo": repo, "tag": tag}
    raise HTTPException(status_code=400, detail="Failed to delete tag from registry")

@app.get("/api/system")
async def system_info(token: str = Depends(get_auth_token)):
    """Returns registry summary statistics."""
    keys = await zot.list_keys(token)
    repos = await zot.list_repositories(token)
    return {
        "backend": zot.base_url,
        "public_domain": zot.public_url,
        "total_repositories": len(repos),
        "total_keys": len(keys),
        "status": "online"
    }
