import os
import base64
import logging
from typing import List, Dict, Any, Optional
import httpx

logger = logging.getLogger("zotdeck.client")

class ZotClient:
    def __init__(self, base_url: Optional[str] = None):
        # Default to internal container network URL or localhost
        self.base_url = (base_url or os.getenv("ZOT_ENDPOINT", "http://zot-registry:5000")).rstrip("/")
        self.public_url = os.getenv("ZOT_PUBLIC_DOMAIN", "registry.mokshlabs.ai").rstrip("/")

    def _get_auth_header(self, auth_token: str) -> Dict[str, str]:
        """Accepts either a pre-encoded Basic token or username:password string."""
        if ":" in auth_token:
            encoded = base64.b64encode(auth_token.encode()).decode()
            return {"Authorization": f"Basic {encoded}"}
        return {"Authorization": f"Basic {auth_token}"}

    async def verify_credentials(self, auth_token: str) -> bool:
        """Pings /v2/ to test if credentials are valid."""
        headers = self._get_auth_header(auth_token)
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(f"{self.base_url}/v2/", headers=headers)
                return resp.status_code == 200
            except Exception as e:
                logger.error(f"Failed to connect to Zot at {self.base_url}: {e}")
                return False

    async def list_keys(self, auth_token: str) -> List[Dict[str, Any]]:
        """Lists active API keys from Zot."""
        headers = self._get_auth_header(auth_token)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self.base_url}/zot/auth/apikey", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("apiKeys", [])
            elif resp.status_code == 401:
                raise PermissionError("Unauthorized")
            else:
                logger.warning(f"Zot list keys error: {resp.status_code} {resp.text}")
                return []

    async def create_key(
        self,
        auth_token: str,
        label: str,
        scopes: Optional[List[str]] = None,
        expiration_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Issues a new API key."""
        headers = self._get_auth_header(auth_token)
        headers["Content-Type"] = "application/json"
        payload: Dict[str, Any] = {"label": label}
        if scopes:
            payload["scopes"] = scopes
        if expiration_date:
            payload["expirationDate"] = expiration_date

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{self.base_url}/zot/auth/apikey", headers=headers, json=payload)
            if resp.status_code in (200, 201):
                return resp.json()
            elif resp.status_code == 401:
                raise PermissionError("Unauthorized")
            else:
                raise RuntimeError(f"Zot API error ({resp.status_code}): {resp.text}")

    async def revoke_key(self, auth_token: str, key_uuid: str) -> bool:
        """Revokes an API key by its UUID."""
        headers = self._get_auth_header(auth_token)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(f"{self.base_url}/zot/auth/apikey?id={key_uuid}", headers=headers)
            if resp.status_code in (200, 204):
                return True
            elif resp.status_code == 401:
                raise PermissionError("Unauthorized")
            return False

    async def list_repositories(self, auth_token: str) -> List[Dict[str, Any]]:
        """Lists all repositories and their tags."""
        headers = self._get_auth_header(auth_token)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self.base_url}/v2/_catalog", headers=headers)
            if resp.status_code != 200:
                return []

            repos = resp.json().get("repositories", []) or []
            repo_list = []

            for repo in repos:
                tags_resp = await client.get(f"{self.base_url}/v2/{repo}/tags/list", headers=headers)
                tags = []
                if tags_resp.status_code == 200:
                    tags = tags_resp.json().get("tags", []) or []

                repo_list.append({
                    "name": repo,
                    "tag_count": len(tags),
                    "tags": tags,
                    "pull_command": f"docker pull {self.public_url}/{repo}:latest"
                })

            return repo_list

    async def get_tag_manifest(self, auth_token: str, repo: str, tag: str) -> Dict[str, Any]:
        """Fetches manifest details for a tag."""
        headers = self._get_auth_header(auth_token)
        headers["Accept"] = (
            "application/vnd.docker.distribution.manifest.v2+json, "
            "application/vnd.oci.image.manifest.v1+json, "
            "application/vnd.docker.distribution.manifest.list.v2+json, "
            "application/vnd.oci.image.index.v1+json"
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self.base_url}/v2/{repo}/manifests/{tag}", headers=headers)
            if resp.status_code != 200:
                return {}

            digest = resp.headers.get("Docker-Content-Digest") or resp.headers.get("ETag", "").strip('"')
            manifest = resp.json()
            layers = manifest.get("layers", [])
            total_size = sum(l.get("size", 0) for l in layers)

            return {
                "digest": digest,
                "schemaVersion": manifest.get("schemaVersion"),
                "mediaType": manifest.get("mediaType"),
                "size_bytes": total_size,
                "layer_count": len(layers),
            }

    async def delete_tag(self, auth_token: str, repo: str, tag_or_digest: str) -> bool:
        """Deletes a manifest by tag or digest."""
        digest = tag_or_digest
        if not tag_or_digest.startswith("sha256:"):
            # Resolve tag to digest first
            details = await self.get_tag_manifest(auth_token, repo, tag_or_digest)
            digest = details.get("digest")
            if not digest:
                return False

        headers = self._get_auth_header(auth_token)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(f"{self.base_url}/v2/{repo}/manifests/{digest}", headers=headers)
            return resp.status_code in (200, 202, 204)
