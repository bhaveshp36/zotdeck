# ZotDeck 🚢

> **Lightweight Web Dashboard, Scoped Credential Manager, and OCI Image Catalog for Zot Registry.**  
> Single container • Minimal resource footprint • Zero external database required • 100% OCI Distribution Spec compliant.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![OCI: Distribution Spec](https://img.shields.io/badge/OCI-Distribution%20Spec-indigo.svg)](https://opencontainers.org/)
[![Docker Pulls](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](#-quickstart)

---

## 💡 What is ZotDeck?

**ZotDeck** is an open-source, resource-efficient web dashboard and credential gateway designed specifically for the [Zot OCI Container Registry](https://github.com/project-zot/zot). 

While enterprise registries like CNCF Harbor deliver powerful features, they often require substantial infrastructure—demanding 1.5+ GB RAM, PostgreSQL, Redis, and 6 to 9 interdependent microservice containers. For homelabs, edge nodes, small teams, and lightweight Kubernetes clusters, this overhead is excessive.

**Zot + ZotDeck** provides a complete, modern, and lightweight container registry management solution without sacrificing enterprise security or developer experience.

---

## ⚡ Key Features at a Glance

| Feature | Description |
| :--- | :--- |
| **🔑 Scoped Credential Hub** | Issue and revoke granular API tokens (`read`, `create`, `update`) scoped to specific repositories (`repo:myapp` or custom globs) with customizable expiration presets (30d, 90d, 180d, 1y, 2y) so master passwords are never exposed to CI/CD runners. |
| **📦 Image Catalog & Layer Inspector** | Search repositories, view all tags/versions, inspect compressed layer sizes, content digests, target OS/architecture (`linux/amd64`, `linux/arm64`), and Docker build history. |
| **🛡️ Vulnerability Scanner (CVEs)** | Native Trivy-powered vulnerability inspection displaying severity counts (`Critical`, `High`, `Medium`, `Low`), CVE IDs with NIST NVD links, affected package versions, and fixed versions. |
| **🔏 Digital Signatures & Image Trust** | Detect and verify **Cosign** and **Notation** signatures via OCI 1.1 Referrers to enforce container provenance and supply-chain trust. |
| **📋 SBOM Packages Explorer** | Inspect Software Bill of Materials attachments in **SPDX** and **CycloneDX** formats, displaying package components, declared licenses, and Syft/Cosign export commands. |
| **🧹 Container Security Linter** | Automated 5-point static container audit grading images on unprivileged non-root execution, immutable tagging, layer optimization, and footprint efficiency. |
| **🔄 Upstream Mirroring & Replication** | Manage Zot as a pull-through cache and automated mirror for Docker Hub, Quay, and GHCR with custom prefix mappings and on-demand sync triggers. |
| **⏳ Tag Retention Simulator** | Interactive lifecycle rule builder to eliminate obsolete CI/CD build tags with dry-run simulation while protecting semantic releases (`v*`, `release-*`). |
| **🔔 Webhook Event Sinks** | Register external notification endpoints to dispatch instant payloads to Slack, Discord, or CI pipelines on image push, retag, or deletion events. |
| **🔍 Storage Integrity & Bit-Rot Scrubbing** | Re-verify content-addressable storage blobs on disk against SHA-256 descriptors to prevent silent filesystem degradation or bit-rot. |
| **🏷️ Instant Zero-Transfer Retagging** | Promote image tags (e.g. promoting `commit-sha` $\rightarrow$ `staging` $\rightarrow$ `latest`) in under 20ms using pure OCI manifest aliasing without downloading or re-uploading layers. |
| **📁 Repository Lifecycle Management** | Pre-register repository namespaces with custom descriptions before pushing images, and delete repositories or individual tags with safety confirmations. |
| **🌐 Multi-Registry Connection Switcher** | Manage local, staging, and remote Zot instances from a unified interface with per-registry credentials and connection verification. |
| **🌓 Dual Light & Dark Themes** | Responsive modern UI built with Tailwind CSS, system theme detection, `localStorage` persistence, and pure inline SVGs (zero external icon CDN dependencies). |
| **💻 Multi-Platform Code Generator** | Copy-paste deployment snippets for Docker CLI, Podman, Kubernetes `imagePullSecrets`, Helm OCI, GitHub Actions, and GitLab CI. |
| **🛡️ Real-Time Security Audit Log** | In-memory activity stream tracking logins, API key creation/revocation, tag promotions, and deletions. |
| **📖 OpenAPI / Swagger Documentation** | Interactive REST API documentation available out of the box at `/docs`. |

---

## 📊 Comparison: ZotDeck vs Harbor vs Alternatives

| Capability / Metric | ZotDeck + Zot | CNCF Harbor | Docker Registry UI | Portus |
| :--- | :--- | :--- | :--- | :--- |
| **Resource Footprint** | **Minimal (~88 MiB total)** | Heavy (~1.5 GB - 2 GB) | Minimal (~60 MiB) | Moderate (~600 MiB) |
| **Container Count** | **2 containers** (Registry + UI) | 6 to 9 containers | 1 UI container | 4+ containers |
| **External Database** | **None** | PostgreSQL required | None | MariaDB / MySQL |
| **Cache / Queue Engine** | **None** | Redis required | None | Background workers |
| **Startup Time** | **< 1.0 second** | 45 - 90 seconds | ~3 seconds | ~30 seconds |
| **Scoped API Key Generation**| **Yes (`read`, `create`)** | Robot Accounts | No (Basic auth only) | App Tokens |
| **Instant Manifest Retagging**| **Yes (< 20ms OCI PUT)** | Manual replication | No (Requires pull/push)| No |
| **Multi-Registry Switcher** | **Built-in** | Replication endpoints | No | No |
| **Light & Dark Theme** | **Yes (Tailwind CSS)** | Partial | Dark mode only | Light only |

---

## 🚀 Quickstart

### 1. Run with Docker Compose (Recommended)

Create a `docker-compose.yml` file to launch Zot and ZotDeck together:

```yaml
version: "3.8"

services:
  zot-registry:
    image: ghcr.io/project-zot/zot-linux-amd64:latest
    container_name: zot-registry
    restart: unless-stopped
    ports:
      - "5000:5000"
    volumes:
      - ./zot-config.json:/etc/zot/config.json:ro
      - ./data:/var/lib/registry
    networks:
      - zot-net

  zotdeck:
    image: bhaveshp36/zotdeck:latest
    container_name: zotdeck
    restart: unless-stopped
    ports:
      - "8089:8000"
    environment:
      - ZOT_ENDPOINT=http://zot-registry:5000
      - ZOT_PUBLIC_DOMAIN=registry.example.com
    depends_on:
      - zot-registry
    networks:
      - zot-net

networks:
  zot-net:
    driver: bridge
```

Start the stack:

```bash
docker compose up -d
```

Open `http://localhost:8089` in your browser to access the ZotDeck dashboard.

---

### 2. Standalone Docker Run

If you already have a running Zot registry:

```bash
docker run -d \
  --name zotdeck \
  -p 8089:8000 \
  -e ZOT_ENDPOINT=http://<your-zot-host>:5000 \
  -e ZOT_PUBLIC_DOMAIN=registry.example.com \
  bhaveshp36/zotdeck:latest
```

---

## ⚙️ Configuration Reference

Configure ZotDeck using standard environment variables:

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `PORT` | `8000` | Internal HTTP listening port for the Uvicorn web server |
| `ZOT_ENDPOINT` | `http://zot-registry:5000` | Internal network URL pointing to your backend Zot instance |
| `ZOT_PUBLIC_DOMAIN` | `registry.example.com` | Public host domain used to format Docker and Kubernetes snippets |

---

## 🏗️ Architecture & Technical Stack

```
   ┌──────────────────────────────────────────────────────────────┐
   │                        Web Browser                           │
   │           Alpine.js + Tailwind CSS (Responsive UI)           │
   └──────────────────────────────┬───────────────────────────────┘
                                  │ HTTP / JSON API
                                  ▼
   ┌──────────────────────────────────────────────────────────────┐
   │                   ZotDeck Web Service                        │
   │       FastAPI • Uvicorn • Async HTTPX • Single Container     │
   │    [Credential Hub] [Manifest Retagger] [Audit Stream]       │
   └──────────────────────────────┬───────────────────────────────┘
                                  │ OCI Distribution API (HTTP/2)
                                  ▼
   ┌──────────────────────────────────────────────────────────────┐
   │                    Zot OCI Registry                          │
   │       Single Binary • Content-Addressable Storage Blob       │
   └──────────────────────────────────────────────────────────────┘
```

- **Backend**: Python 3.11 (Alpine Linux base), FastAPI, Uvicorn ASGI, HTTPX async client.
- **Frontend**: Pure Tailwind CSS, Alpine.js reactive components, inline SVGs (zero Node.js build dependencies, zero external CDN reliance).
- **Container Hardening**: Unprivileged non-root user (`UID 1000:1000`), minimal attack surface, read-only root compatibility.

---

## ❓ Frequently Asked Questions (FAQ)

### How does 1-click retagging work without pulling or re-pushing layers?
Under the OCI Image Specification, an image tag is a reference pointing to a manifest descriptor digest (`sha256:...`). When you promote or retag an image in ZotDeck, the application performs:
1. `GET /v2/<repo>/manifests/<source_tag>` to retrieve the manifest payload and media type.
2. `PUT /v2/<repo>/manifests/<target_tag>` with that exact manifest content.
Zot associates the new tag pointer with the existing content-addressable blobs in disk storage. The entire operation completes in $< 20\text{ ms}$ over HTTP and consumes zero bandwidth for layer transfers.

### Can I restrict an API key to a specific repository or image?
Yes. When issuing an API key in ZotDeck, you can bind the credential to a dedicated repository or namespace pattern (e.g. `repo:backend` or custom globs). ZotDeck embeds the repository scope directly into the token's metadata, presents repository badges in the credential dashboard, and automatically formats repository-specific Docker push commands. For strict 403 Forbidden boundary enforcement across multi-tenant setups, Zot pairs this with its declarative `accessControl.repositories` policies.

### Why use ZotDeck instead of Harbor?
Harbor is an enterprise-grade solution but requires massive infrastructure (PostgreSQL, Redis, multiple pods, 1.5+ GB RAM). ZotDeck paired with Zot gives you private registry management, layer inspection, and scoped credentials using under 90 MiB RAM total—making it ideal for homelabs, resource-constrained VPS instances, and lightweight CI/CD setups.

### Can ZotDeck manage multiple remote Zot registries?
Yes. The built-in **Multi-Registry Switcher** allows you to connect multiple internal, staging, and remote production Zot instances, configure independent authentication tokens, and toggle between them on the fly.

### Does ZotDeck store passwords or require an external database?
No. ZotDeck is completely stateless and does not require an external database. Authentication is verified directly against your configured Zot registry using standard Basic / API token handshakes.

---

## 🎯 Use Cases

- **Self-Hosted Homelabs**: Run a private container registry on a Raspberry Pi or low-cost VPS alongside Nextcloud, Home Assistant, and media servers.
- **CI/CD Build Farms**: Issue dedicated, scoped API tokens to GitHub Actions, GitLab CI, or Jenkins runners with expiration dates.
- **Edge Computing & IoT**: Deploy an ultra-light registry on edge appliances with strict memory constraints.
- **Air-Gapped & Offline Environments**: Single-container deployment with zero external network phone-homes or CDN dependencies.

---

## 🤝 Contributing

Contributions, bug reports, and feature requests are welcome!
1. Check the [open issues](https://github.com/bhaveshp36/zotdeck/issues).
2. Read the [Contributing Guide](CONTRIBUTING.md) to set up a local development environment.
3. Open a Pull Request on branch `main`.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
