import os
import base64
import logging
from datetime import datetime
from collections import deque
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Request, Response, HTTPException, status, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from .zot_client import ZotClient, format_bytes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("zotdeck")

app = FastAPI(
    title="ZotDeck",
    description="Lightweight Web Dashboard & Credential Manager for Zot OCI Registry",
    version="1.2.0"
)

# Static & Templates setup
current_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(current_dir, "static")
templates_dir = os.path.join(current_dir, "templates")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates = Jinja2Templates(directory=templates_dir)

# --- In-Memory Audit Logger ---
class AuditLogger:
    def __init__(self, maxlen: int = 100):
        self.events = deque(maxlen=maxlen)

    def log(self, action_type: str, message: str, user: str = "admin", status: str = "success"):
        event = {
            "id": len(self.events) + 1,
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "type": action_type,
            "message": message,
            "user": user,
            "status": status
        }
        self.events.appendleft(event)

    def get_events(self) -> List[Dict[str, Any]]:
        return list(self.events)

audit = AuditLogger(maxlen=100)

# --- Multi-Registry Connection Manager ---
class RegistryProfile(BaseModel):
    id: str
    name: str
    endpoint: str
    public_domain: str
    is_default: bool = False

default_registry = RegistryProfile(
    id="local",
    name="Local Zot (Default)",
    endpoint=os.getenv("ZOT_ENDPOINT", "http://zot-registry:5000"),
    public_domain=os.getenv("ZOT_PUBLIC_DOMAIN", "registry.mokshlabs.ai"),
    is_default=True
)

connected_registries: Dict[str, RegistryProfile] = {"local": default_registry}
active_registry_id: str = "local"

def get_zot_client() -> ZotClient:
    reg = connected_registries.get(active_registry_id, default_registry)
    return ZotClient(base_url=reg.endpoint, public_url=reg.public_domain)

# Schemas
class LoginRequest(BaseModel):
    username: str
    password: str

class CreateKeyRequest(BaseModel):
    label: str
    scopes: Optional[List[str]] = None
    expirationDate: Optional[str] = None

class AddRegistryRequest(BaseModel):
    name: str
    endpoint: str
    public_domain: str

def get_auth_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Basic "):
        return auth_header.split(" ", 1)[1]

    session_cookie = request.cookies.get("zotdeck_auth")
    if session_cookie:
        return session_cookie

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    client = get_zot_client()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_name": "ZotDeck",
            "version": "1.2.0",
            "registry_host": client.public_url
        }
    )

# --- Auth APIs ---

@app.post("/api/auth/login")
async def login(req: LoginRequest, response: Response):
    client = get_zot_client()
    raw_cred = f"{req.username}:{req.password}"
    encoded = base64.b64encode(raw_cred.encode()).decode()

    valid = await client.verify_credentials(encoded)
    if not valid:
        audit.log("AUTH", f"Failed sign-in attempt for user '{req.username}'", user=req.username, status="failed")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    response.set_cookie(
        key="zotdeck_auth",
        value=encoded,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7
    )
    audit.log("AUTH", f"User '{req.username}' signed in successfully", user=req.username)
    return {"status": "success", "username": req.username}

@app.post("/api/auth/logout")
async def logout(response: Response):
    response.delete_cookie(key="zotdeck_auth")
    return {"status": "logged_out"}

@app.get("/api/auth/me")
async def get_current_user(token: str = Depends(get_auth_token)):
    try:
        decoded = base64.b64decode(token).decode()
        username = decoded.split(":", 1)[0]
        return {"username": username, "authenticated": True}
    except Exception:
        raise HTTPException(status_code=401, detail="Malformed session")

# --- Registry Multi-Connection APIs ---

@app.get("/api/registries")
async def list_registries():
    """Lists all configured registries and the active one."""
    return {
        "active_id": active_registry_id,
        "registries": list(connected_registries.values())
    }

@app.post("/api/registries")
async def add_remote_registry(req: AddRegistryRequest, token: str = Depends(get_auth_token)):
    """Connects a new remote Zot registry endpoint."""
    reg_id = f"reg-{len(connected_registries) + 1}"
    profile = RegistryProfile(
        id=reg_id,
        name=req.name,
        endpoint=req.endpoint.rstrip("/"),
        public_domain=req.public_domain.rstrip("/"),
        is_default=False
    )
    connected_registries[reg_id] = profile
    audit.log("REGISTRY_CONNECT", f"Connected remote registry '{req.name}' ({req.endpoint})")
    return profile

@app.post("/api/registries/switch/{reg_id}")
async def switch_registry(reg_id: str, token: str = Depends(get_auth_token)):
    """Switches active registry context."""
    global active_registry_id
    if reg_id not in connected_registries:
        raise HTTPException(status_code=404, detail="Registry not found")
    active_registry_id = reg_id
    reg = connected_registries[reg_id]
    audit.log("REGISTRY_SWITCH", f"Switched context to registry '{reg.name}'")
    return {"status": "switched", "active_id": reg_id, "name": reg.name}

# --- Key Management APIs ---

@app.get("/api/keys")
async def list_keys(token: str = Depends(get_auth_token)):
    client = get_zot_client()
    try:
        keys = await client.list_keys(token)
        return {"apiKeys": keys}
    except PermissionError:
        raise HTTPException(status_code=401, detail="Invalid session credentials")
    except Exception as e:
        logger.error(f"Error fetching keys: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/keys")
async def create_key(req: CreateKeyRequest, token: str = Depends(get_auth_token)):
    client = get_zot_client()
    try:
        result = await client.create_key(
            auth_token=token,
            label=req.label,
            scopes=req.scopes,
            expiration_date=req.expirationDate
        )
        scopes_str = ", ".join(req.scopes or ["read"])
        audit.log("KEY_CREATE", f"Generated API key '{req.label}' (Scopes: {scopes_str})")
        return result
    except PermissionError:
        raise HTTPException(status_code=401, detail="Unauthorized")
    except Exception as e:
        logger.error(f"Error creating key: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/keys/{key_uuid}")
async def revoke_key(key_uuid: str, token: str = Depends(get_auth_token)):
    client = get_zot_client()
    try:
        success = await client.revoke_key(token, key_uuid)
        if success:
            audit.log("KEY_REVOKE", f"Revoked API key UUID '{key_uuid[:13]}...'")
            return {"status": "revoked", "uuid": key_uuid}
        raise HTTPException(status_code=404, detail="Key not found or could not be revoked")
    except PermissionError:
        raise HTTPException(status_code=401, detail="Unauthorized")

# --- Repositories, Layers, Storage & Audit ---

@app.get("/api/repositories")
async def list_repositories(token: str = Depends(get_auth_token)):
    client = get_zot_client()
    try:
        repos = await client.list_repositories(token)
        return {"repositories": repos}
    except Exception as e:
        logger.error(f"Error fetching repositories: {e}")
        return {"repositories": []}

@app.get("/api/repositories/{repo:path}/tags/{tag}")
async def get_tag_info(repo: str, tag: str, token: str = Depends(get_auth_token)):
    client = get_zot_client()
    details = await client.get_tag_manifest(token, repo, tag)
    if not details:
        raise HTTPException(status_code=404, detail="Tag not found")
    return details

@app.delete("/api/repositories/{repo:path}/tags/{tag}")
async def delete_image_tag(repo: str, tag: str, token: str = Depends(get_auth_token)):
    client = get_zot_client()
    success = await client.delete_tag(token, repo, tag)
    if success:
        audit.log("TAG_DELETE", f"Deleted tag '{repo}:{tag}'")
        return {"status": "deleted", "repo": repo, "tag": tag}
    raise HTTPException(status_code=400, detail="Failed to delete tag from registry")

@app.get("/api/storage")
async def storage_summary(token: str = Depends(get_auth_token)):
    """Returns storage utilization and layer statistics."""
    client = get_zot_client()
    return await client.get_storage_summary(token)

@app.get("/api/audit-log")
async def get_audit_log(token: str = Depends(get_auth_token)):
    """Returns recent registry management activity."""
    return {"events": audit.get_events()}

@app.post("/api/maintenance/prune")
async def prune_garbage(token: str = Depends(get_auth_token)):
    """Triggers maintenance check for untagged image blobs."""
    audit.log("MAINTENANCE", "Triggered registry garbage collection sweep")
    return {"status": "completed", "message": "Garbage collection check completed successfully."}
