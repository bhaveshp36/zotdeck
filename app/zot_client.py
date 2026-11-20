import os
import base64
import logging
from typing import List, Dict, Any, Optional
import httpx

logger = logging.getLogger("zotdeck.client")

def format_bytes(size_bytes: int) -> str:
    """Formats bytes into human readable format."""
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(size_bytes)
    while size >= 1024.0 and i < len(units) - 1:
        size /= 1024.0
        i += 1
    return f"{size:.2f} {units[i]}"

class ZotClient:
    def __init__(self, base_url: Optional[str] = None, public_url: Optional[str] = None):
        self.base_url = (base_url or os.getenv("ZOT_ENDPOINT", "http://zot-registry:5000")).rstrip("/")
        self.public_url = (public_url or os.getenv("ZOT_PUBLIC_DOMAIN", "registry.mokshlabs.ai")).rstrip("/")

    def _get_auth_header(self, auth_token: str) -> Dict[str, str]:
        if ":" in auth_token:
            encoded = base64.b64encode(auth_token.encode()).decode()
            return {"Authorization": f"Basic {encoded}"}
        return {"Authorization": f"Basic {auth_token}"}

    async def verify_credentials(self, auth_token: str) -> bool:
        headers = self._get_auth_header(auth_token)
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(f"{self.base_url}/v2/", headers=headers)
                return resp.status_code == 200
            except Exception as e:
                logger.error(f"Failed to connect to Zot at {self.base_url}: {e}")
                return False

    async def list_keys(self, auth_token: str) -> List[Dict[str, Any]]:
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
        headers = self._get_auth_header(auth_token)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(f"{self.base_url}/zot/auth/apikey?id={key_uuid}", headers=headers)
            if resp.status_code in (200, 204):
                return True
            elif resp.status_code == 401:
                raise PermissionError("Unauthorized")
            return False

    async def list_repositories(self, auth_token: str) -> List[Dict[str, Any]]:
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
        """Fetches detailed manifest, layer breakdowns, and image configuration."""
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
            raw_layers = manifest.get("layers", [])
            total_size = sum(l.get("size", 0) for l in raw_layers)

            formatted_layers = []
            for idx, l in enumerate(raw_layers):
                l_size = l.get("size", 0)
                formatted_layers.append({
                    "index": idx + 1,
                    "digest": l.get("digest", "")[:19] + "...",
                    "full_digest": l.get("digest", ""),
                    "size_bytes": l_size,
                    "formatted_size": format_bytes(l_size),
                    "media_type": l.get("mediaType", "")
                })

            # Fetch Config blob if present for architecture, OS, and history
            config_desc = manifest.get("config", {})
            config_digest = config_desc.get("digest")
            arch = "unknown"
            os_name = "linux"
            created_at = None
            history_commands = []

            if config_digest:
                try:
                    blob_resp = await client.get(f"{self.base_url}/v2/{repo}/blobs/{config_digest}", headers=headers)
                    if blob_resp.status_code == 200:
                        cfg_json = blob_resp.json()
                        arch = cfg_json.get("architecture", arch)
                        os_name = cfg_json.get("os", os_name)
                        created_at = cfg_json.get("created")
                        for h in cfg_json.get("history", []):
                            cmd = h.get("created_by", "")
                            if cmd:
                                history_commands.append(cmd)
                except Exception as e:
                    logger.debug(f"Could not load config blob {config_digest}: {e}")

            return {
                "repo": repo,
                "tag": tag,
                "digest": digest,
                "short_digest": digest[:19] + "..." if digest else "",
                "schemaVersion": manifest.get("schemaVersion"),
                "mediaType": manifest.get("mediaType"),
                "architecture": arch,
                "os": os_name,
                "created_at": created_at,
                "size_bytes": total_size,
                "formatted_size": format_bytes(total_size),
                "layer_count": len(raw_layers),
                "layers": formatted_layers,
                "history": history_commands[:15],
                "pull_command": f"docker pull {self.public_url}/{repo}:{tag}"
            }

    async def get_storage_summary(self, auth_token: str) -> Dict[str, Any]:
        """Calculates total registry image footprint and layer deduplication statistics."""
        repos = await self.list_repositories(auth_token)
        total_tags = 0
        unique_layer_digests = {}

        for r in repos:
            repo_name = r["name"]
            total_tags += len(r.get("tags", []))
            for tag in r.get("tags", [])[:10]: # Sample tags
                try:
                    info = await self.get_tag_manifest(auth_token, repo_name, tag)
                    for l in info.get("layers", []):
                        f_digest = l.get("full_digest")
                        if f_digest and f_digest not in unique_layer_digests:
                            unique_layer_digests[f_digest] = l.get("size_bytes", 0)
                except Exception:
                    continue

        total_bytes = sum(unique_layer_digests.values())

        return {
            "total_repositories": len(repos),
            "total_tags": total_tags,
            "unique_layers": len(unique_layer_digests),
            "total_bytes": total_bytes,
            "formatted_size": format_bytes(total_bytes)
        }

    async def retag_image(self, auth_token: str, repo: str, source_tag: str, target_tag: str) -> bool:
        """Promotes or retags an image tag to a new target tag without pulling or pushing layers."""
        headers = self._get_auth_header(auth_token)
        headers["Accept"] = (
            "application/vnd.docker.distribution.manifest.v2+json, "
            "application/vnd.oci.image.manifest.v1+json, "
            "application/vnd.docker.distribution.manifest.list.v2+json, "
            "application/vnd.oci.image.index.v1+json"
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            get_resp = await client.get(f"{self.base_url}/v2/{repo}/manifests/{source_tag}", headers=headers)
            if get_resp.status_code != 200:
                logger.error(f"Failed to fetch source manifest for retag: {get_resp.status_code} {get_resp.text}")
                return False

            content_type = get_resp.headers.get("Content-Type") or "application/vnd.docker.distribution.manifest.v2+json"
            manifest_content = get_resp.content

            put_headers = self._get_auth_header(auth_token)
            put_headers["Content-Type"] = content_type
            put_resp = await client.put(
                f"{self.base_url}/v2/{repo}/manifests/{target_tag}",
                headers=put_headers,
                content=manifest_content
            )
            return put_resp.status_code in (200, 201)

    async def delete_repository(self, auth_token: str, repo: str) -> bool:
        """Deletes all image tags and manifests associated with a repository."""
        headers = self._get_auth_header(auth_token)
        async with httpx.AsyncClient(timeout=20.0) as client:
            tags_resp = await client.get(f"{self.base_url}/v2/{repo}/tags/list", headers=headers)
            if tags_resp.status_code == 404:
                return True
            if tags_resp.status_code != 200:
                return False

            tags = tags_resp.json().get("tags", []) or []
            all_deleted = True
            for tag in tags:
                del_ok = await self.delete_tag(auth_token, repo, tag)
                if not del_ok:
                    all_deleted = False
            return all_deleted

    async def delete_tag(self, auth_token: str, repo: str, tag_or_digest: str) -> bool:
        headers = self._get_auth_header(auth_token)
        async with httpx.AsyncClient(timeout=10.0) as client:
            # First attempt: direct tag deletion (Zot OCI extension: deletes only this tag pointer)
            resp = await client.delete(f"{self.base_url}/v2/{repo}/manifests/{tag_or_digest}", headers=headers)
            if resp.status_code in (200, 202, 204):
                return True

            # Fallback for strict OCI v2 registries: resolve digest and delete manifest
            if not tag_or_digest.startswith("sha256:"):
                details = await self.get_tag_manifest(auth_token, repo, tag_or_digest)
                digest = details.get("digest")
                if digest:
                    digest_resp = await client.delete(f"{self.base_url}/v2/{repo}/manifests/{digest}", headers=headers)
                    return digest_resp.status_code in (200, 202, 204)

            return False
