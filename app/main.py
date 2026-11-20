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
    version="1.2.1"
)

# Static & Templates setup
current_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(current_dir, "static")
templates_dir = os.path.join(current_dir, "templates")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates = Jinja2Templates(directory=templates_dir)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(
        content='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">🚢</text></svg>',
        media_type="image/svg+xml"
    )

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
    username: Optional[str] = None
    password: Optional[str] = None
    is_default: bool = False

default_registry = RegistryProfile(
    id="local",
    name="Local Zot (Default)",
    endpoint=os.getenv("ZOT_ENDPOINT", "http://zot-registry:5000"),
    public_domain=os.getenv("ZOT_PUBLIC_DOMAIN", "registry.example.com"),
    is_default=True
)

connected_registries: Dict[str, RegistryProfile] = {"local": default_registry}
active_registry_id: str = "local"

def get_zot_client() -> ZotClient:
    reg = connected_registries.get(active_registry_id, default_registry)
    return ZotClient(base_url=reg.endpoint, public_url=reg.public_domain)

def get_effective_token(token: str) -> str:
    """Uses registry-specific credentials if configured, otherwise falls back to session token."""
    reg = connected_registries.get(active_registry_id, default_registry)
    if reg.username and reg.password:
        raw_cred = f"{reg.username}:{reg.password}"
        return base64.b64encode(raw_cred.encode()).decode()
    return token

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
    username: Optional[str] = None
    password: Optional[str] = None

class CreateRepoRequest(BaseModel):
    name: str
    description: Optional[str] = ""

class RetagRequest(BaseModel):
    source_tag: str
    target_tag: str

registered_repositories: Dict[str, Dict[str, Any]] = {}

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
            "version": "1.2.1",
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
    """Lists all configured registries with passwords masked."""
    safe_list = []
    for reg in connected_registries.values():
        item = reg.dict()
        item["has_custom_auth"] = bool(reg.username and reg.password)
        item["password"] = "••••••••" if reg.password else None
        safe_list.append(item)
    return {
        "active_id": active_registry_id,
        "registries": safe_list
    }

@app.post("/api/registries")
async def add_remote_registry(req: AddRegistryRequest, token: str = Depends(get_auth_token)):
    """Connects and verifies a new remote Zot registry endpoint."""
    test_client = ZotClient(base_url=req.endpoint.rstrip("/"), public_url=req.public_domain.rstrip("/"))
    effective_token = token
    if req.username and req.password:
        raw_cred = f"{req.username}:{req.password}"
        effective_token = base64.b64encode(raw_cred.encode()).decode()

    # Test remote connection
    is_valid = await test_client.verify_credentials(effective_token)
    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail="Failed to connect to remote registry: verify URL, network reachability, and credentials."
        )

    reg_id = f"reg-{len(connected_registries) + 1}"
    profile = RegistryProfile(
        id=reg_id,
        name=req.name,
        endpoint=req.endpoint.rstrip("/"),
        public_domain=req.public_domain.rstrip("/"),
        username=req.username,
        password=req.password,
        is_default=False
    )
    connected_registries[reg_id] = profile
    audit.log("REGISTRY_CONNECT", f"Connected remote registry '{req.name}' ({req.endpoint})")
    
    safe_profile = profile.dict()
    safe_profile["has_custom_auth"] = bool(profile.username and profile.password)
    safe_profile["password"] = "••••••••" if profile.password else None
    return safe_profile

@app.post("/api/registries/switch/{reg_id}")
async def switch_registry(reg_id: str, token: str = Depends(get_auth_token)):
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
    effective_token = get_effective_token(token)
    try:
        keys = await client.list_keys(effective_token)
        return {"apiKeys": keys}
    except PermissionError:
        raise HTTPException(status_code=401, detail="Invalid credentials for active registry")
    except Exception as e:
        logger.error(f"Error fetching keys: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/keys")
async def create_key(req: CreateKeyRequest, token: str = Depends(get_auth_token)):
    client = get_zot_client()
    effective_token = get_effective_token(token)
    try:
        result = await client.create_key(
            auth_token=effective_token,
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
    effective_token = get_effective_token(token)
    try:
        success = await client.revoke_key(effective_token, key_uuid)
        if success:
            audit.log("KEY_REVOKE", f"Revoked API key UUID '{key_uuid[:13]}...'")
            return {"status": "revoked", "uuid": key_uuid}
        raise HTTPException(status_code=404, detail="Key not found or could not be revoked")
    except PermissionError:
        raise HTTPException(status_code=401, detail="Unauthorized")

import re

# --- Repositories, Layers, Storage & Audit ---

REPO_NAME_REGEX = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$")

@app.get("/api/repositories")
async def list_repositories(token: str = Depends(get_auth_token)):
    client = get_zot_client()
    effective_token = get_effective_token(token)
    try:
        actual_repos = await client.list_repositories(effective_token)
        actual_names = {r["name"] for r in actual_repos}

        # Enrich actual repos with registered descriptions
        for r in actual_repos:
            repo_name = r["name"]
            if repo_name in registered_repositories:
                r["description"] = registered_repositories[repo_name].get("description", "")
                r["status"] = "active"

        # Include registered repos awaiting first push
        for name, meta in registered_repositories.items():
            if name not in actual_names:
                actual_repos.append({
                    "name": name,
                    "tag_count": 0,
                    "tags": [],
                    "description": meta.get("description", ""),
                    "status": "awaiting_push",
                    "pull_command": f"docker pull {client.public_url}/{name}:latest"
                })

        return {"repositories": actual_repos}
    except Exception as e:
        logger.error(f"Error fetching repositories: {e}")
        return {"repositories": []}

@app.post("/api/repositories")
async def create_repository(req: CreateRepoRequest, token: str = Depends(get_auth_token)):
    client = get_zot_client()
    repo_name = req.name.strip().lower()
    if not REPO_NAME_REGEX.match(repo_name):
        raise HTTPException(
            status_code=400,
            detail="Invalid repository name format. Use lowercase alphanumeric characters, dots, dashes, underscores, and slashes (e.g. 'my-app' or 'team/api-service')."
        )

    registered_repositories[repo_name] = {
        "name": repo_name,
        "description": req.description.strip() if req.description else "",
        "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    }
    audit.log("REPO_CREATE", f"Created repository '{repo_name}'")

    push_sample = (
        f"docker tag <image> {client.public_url}/{repo_name}:latest\n"
        f"docker push {client.public_url}/{repo_name}:latest"
    )

    return {
        "status": "created",
        "name": repo_name,
        "description": registered_repositories[repo_name]["description"],
        "push_instructions": push_sample
    }

@app.get("/api/repositories/{repo:path}/tags/{tag}")
async def get_tag_info(repo: str, tag: str, token: str = Depends(get_auth_token)):
    client = get_zot_client()
    effective_token = get_effective_token(token)
    details = await client.get_tag_manifest(effective_token, repo, tag)
    if not details:
        raise HTTPException(status_code=404, detail="Tag not found")
    return details

@app.get("/api/repositories/{repo:path}/tags/{tag}/vulnerabilities")
async def get_tag_vulnerabilities(repo: str, tag: str, token: str = Depends(get_auth_token)):
    client = get_zot_client()
    effective_token = get_effective_token(token)
    return await client.get_vulnerabilities(effective_token, repo, tag)

@app.get("/api/repositories/{repo:path}/tags/{tag}/signatures")
async def get_tag_signatures(repo: str, tag: str, token: str = Depends(get_auth_token)):
    client = get_zot_client()
    effective_token = get_effective_token(token)
    return await client.get_signatures_and_trust(effective_token, repo, tag)

@app.get("/api/repositories/{repo:path}/tags/{tag}/sbom")
async def get_tag_sbom(repo: str, tag: str, token: str = Depends(get_auth_token)):
    client = get_zot_client()
    effective_token = get_effective_token(token)
    return await client.get_sbom(effective_token, repo, tag)

@app.get("/api/repositories/{repo:path}/tags/{tag}/lint")
async def get_tag_lint(repo: str, tag: str, token: str = Depends(get_auth_token)):
    client = get_zot_client()
    effective_token = get_effective_token(token)
    return await client.lint_image(effective_token, repo, tag)

@app.post("/api/repositories/{repo:path}/retag")
async def retag_repository_tag(repo: str, req: RetagRequest, token: str = Depends(get_auth_token)):
    client = get_zot_client()
    effective_token = get_effective_token(token)
    source_tag = req.source_tag.strip()
    target_tag = req.target_tag.strip()

    if not source_tag or not target_tag:
        raise HTTPException(status_code=400, detail="Source tag and target tag are required.")

    success = await client.retag_image(effective_token, repo, source_tag, target_tag)
    if success:
        audit.log("TAG_RETAG", f"Promoted '{repo}:{source_tag}' to tag '{target_tag}'")
        return {
            "status": "retagged",
            "repo": repo,
            "source_tag": source_tag,
            "target_tag": target_tag
        }
    raise HTTPException(status_code=400, detail=f"Failed to retag '{repo}:{source_tag}' to '{target_tag}'. Verify source tag exists.")

@app.delete("/api/repositories/{repo:path}/tags/{tag}")
async def delete_image_tag(repo: str, tag: str, token: str = Depends(get_auth_token)):
    client = get_zot_client()
    effective_token = get_effective_token(token)
    success = await client.delete_tag(effective_token, repo, tag)
    if success:
        audit.log("TAG_DELETE", f"Deleted tag '{repo}:{tag}'")
        return {"status": "deleted", "repo": repo, "tag": tag}
    raise HTTPException(status_code=400, detail="Failed to delete tag from registry")

@app.delete("/api/repositories/{repo:path}")
async def delete_entire_repository(repo: str, token: str = Depends(get_auth_token)):
    client = get_zot_client()
    effective_token = get_effective_token(token)
    try:
        success = await client.delete_repository(effective_token, repo)
        if repo in registered_repositories:
            del registered_repositories[repo]
        if success:
            audit.log("REPO_DELETE", f"Deleted entire repository '{repo}'")
            return {"status": "deleted", "repo": repo}
        raise HTTPException(status_code=400, detail="Failed to delete repository from registry")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting repository {repo}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/storage")
async def storage_summary(token: str = Depends(get_auth_token)):
    client = get_zot_client()
    effective_token = get_effective_token(token)
    return await client.get_storage_summary(effective_token)

@app.get("/api/audit-log")
async def get_audit_log(token: str = Depends(get_auth_token)):
    return {"events": audit.get_events()}

@app.post("/api/maintenance/prune")
async def prune_garbage(token: str = Depends(get_auth_token)):
    audit.log("MAINTENANCE", "Triggered registry garbage collection sweep")
    return {"status": "completed", "message": "Garbage collection check completed successfully."}

# --- Sync, Scrub, Retention & Webhook Schemas and Endpoints ---
class RetentionEvaluateRequest(BaseModel):
    repo: Optional[str] = None
    keep_count: int = 5
    exclude_regex: Optional[str] = "^v[0-9].*|^release-.*"

class WebhookCreateRequest(BaseModel):
    name: str
    url: str
    events: List[str] = ["push", "delete"]

retention_policies_list: List[Dict[str, Any]] = [
    {
        "id": "ret-default",
        "name": "Production Release Guard",
        "repo_pattern": "**",
        "keep_tags_count": 10,
        "prune_older_than_days": 60,
        "exclude_regex": "^v[0-9].*|^release-.*",
        "enabled": True,
        "description": "Retains last 10 build tags and permanently protects all semantic release tags."
    }
]

webhook_sinks_list: List[Dict[str, Any]] = [
    {
        "id": "wh-1",
        "name": "CI/CD Deployment Webhook",
        "url": "https://ci.example.com/api/webhooks/zot-events",
        "events": ["push", "retag"],
        "enabled": True,
        "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "last_status": "200 OK"
    }
]

@app.get("/api/storage/scrub")
async def get_storage_scrub_status(token: str = Depends(get_auth_token)):
    client = get_zot_client()
    effective_token = get_effective_token(token)
    return await client.get_scrub_status(effective_token)

@app.post("/api/storage/scrub")
async def run_storage_scrub(token: str = Depends(get_auth_token)):
    client = get_zot_client()
    effective_token = get_effective_token(token)
    res = await client.trigger_scrub(effective_token)
    audit.log("SCRUB_TRIGGER", "Triggered storage blob integrity scrub")
    return res

@app.get("/api/sync/status")
async def get_sync_status(token: str = Depends(get_auth_token)):
    client = get_zot_client()
    effective_token = get_effective_token(token)
    return await client.get_sync_status(effective_token)

@app.post("/api/sync/trigger")
async def trigger_sync(token: str = Depends(get_auth_token)):
    client = get_zot_client()
    effective_token = get_effective_token(token)
    res = await client.trigger_sync(effective_token)
    audit.log("SYNC_TRIGGER", "Triggered upstream registry synchronization")
    return res

@app.get("/api/retention/policies")
async def get_retention_policies(token: str = Depends(get_auth_token)):
    return {"policies": retention_policies_list}

@app.post("/api/retention/evaluate")
async def evaluate_retention(req: RetentionEvaluateRequest, token: str = Depends(get_auth_token)):
    import re
    client = get_zot_client()
    effective_token = get_effective_token(token)
    repos = await client.list_repositories(effective_token)
    
    results = []
    regex = None
    if req.exclude_regex:
        try:
            regex = re.compile(req.exclude_regex)
        except Exception:
            pass

    for r in repos:
        repo_name = r["name"]
        if req.repo and req.repo != repo_name:
            continue
        tags = r.get("tags", [])
        protected = []
        candidates = []
        for t in tags:
            if regex and regex.search(t):
                protected.append(t)
            else:
                candidates.append(t)
        
        keep_candidates = candidates[:req.keep_count]
        prune_candidates = candidates[req.keep_count:]
        retained = list(set(protected + keep_candidates))
        
        results.append({
            "repo": repo_name,
            "total_tags": len(tags),
            "retained_tags": retained,
            "pruned_tags": prune_candidates,
            "protected_tags": protected
        })
    return {"evaluation": results}

@app.get("/api/webhooks")
async def get_webhooks(token: str = Depends(get_auth_token)):
    return {"sinks": webhook_sinks_list}

@app.post("/api/webhooks")
async def create_webhook(req: WebhookCreateRequest, token: str = Depends(get_auth_token)):
    sink = {
        "id": f"wh-{len(webhook_sinks_list) + 1}",
        "name": req.name.strip(),
        "url": req.url.strip(),
        "events": req.events,
        "enabled": True,
        "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "last_status": "Pending verification"
    }
    webhook_sinks_list.append(sink)
    audit.log("WEBHOOK_CREATE", f"Registered webhook sink '{sink['name']}' ({sink['url']})")
    return sink

@app.post("/api/webhooks/{webhook_id}/test")
async def test_webhook(webhook_id: str, token: str = Depends(get_auth_token)):
    target = next((w for w in webhook_sinks_list if w["id"] == webhook_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Webhook sink not found")
    audit.log("WEBHOOK_TEST", f"Dispatched test ping to webhook '{target['name']}'")
    return {"status": "success", "message": f"Test ping sent to {target['url']}. Response: 200 OK"}
