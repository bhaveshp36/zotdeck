# ZotDeck 🚢

> **Ultra-lightweight Web Dashboard, Scoped Credential Manager, and OCI Image Catalog for Zot Registry.**  
> Single container • Under **45 MiB RAM** • Zero external database required.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![Memory: <45MB](https://img.shields.io/badge/RAM-~40MiB-emerald.svg)](#performance--footprint)
[![OCI: Distribution Spec](https://img.shields.io/badge/OCI-Distribution%20Spec-indigo.svg)](https://opencontainers.org/)

---

## 💡 Why ZotDeck?

Modern cloud-native pipelines need private, fast, and secure container image registries. While enterprise registries like Harbor require substantial infrastructure (~1.5 GB RAM, external databases, and multiple background services), **Zot** provides an OCI-native, high-performance registry in a single binary (~48 MiB RAM).

**ZotDeck** completes the picture: a web dashboard and credential gateway tailored for Zot:
- **Footprint**: Runs under **45 MiB RAM** in a single Alpine container.
- **Security-First**: Generates scoped, revocable application API keys (`read`, `create`) so you never expose master passwords to CI/CD runners.
- **OCI-Native Speed**: Performs 1-click tag promotions and retagging in under 20ms using pure manifest aliasing without layer re-uploads.

---

## ✨ Features

### 🔑 Scoped Credential Hub
- Issue scoped API keys (`read` for pulling, `create/update` for pushing).
- Configure optional key expiration dates.
- Generate one-click `docker login` snippets for deployment scripts.
- Instant 1-click credential revocation to invalidate compromised tokens immediately.

### 📦 Image Catalog & Layer Inspector
- Explore all repositories, tags, and digests stored in the registry.
- Inspect individual OCI image layers, compressed sizes, and media types.
- View target architecture (`linux/amd64`, `linux/arm64`) and Docker build command history.
- Pre-register new repository namespaces with custom descriptions before pushing images.

### 🏷️ 1-Click Zero-Transfer Tag Promotion
- Promote image tags (e.g. promoting `commit-sha` to `staging` or `latest`) in under 20ms.
- Implements standard OCI manifest retrieval and publication—no downloading or re-uploading layer blobs.

### 🌐 Multi-Registry Connection Switcher
- Connect multiple internal, staging, and production Zot registries within a single interface.
- Support for per-registry authentication tokens with credential masking.
- Pre-flight endpoint and credential validation.

### 🌓 Dual Light & Dark Theme
- Responsive UI built with Tailwind CSS.
- Persistent theme preference via `localStorage`.
- Pure inline SVGs for zero external icon CDN dependencies.

### 💻 Multi-Platform Integration Code Generator
Interactive deployment snippets pre-populated with your registry domain:
- **Docker CLI**: Login, tag, and push commands.
- **Podman**: Rootless container workflows.
- **Kubernetes**: Ready-to-apply `kubectl create secret docker-registry` commands.
- **Helm OCI**: Chart package and push instructions.
- **GitHub Actions**: Copy-paste CI workflow blocks using encrypted secrets.
- **GitLab CI**: Production `.gitlab-ci.yml` pipeline stages.

### 🛡️ Real-Time Audit Log & Maintenance
- In-memory activity stream recording user logins, key creation, revocations, and tag deletions.
- Storage analytics: Calculates deduplicated layer footprints across content-addressable blobs.
- 1-click registry garbage collection triggers.

### 📖 Interactive OpenAPI Swagger Documentation
- Fully documented REST API available at `/docs` (Swagger UI) and `/redoc`.

---

## 🚀 Quickstart

### Option 1: Docker Run

```bash
docker run -d \
  --name zotdeck \
  -p 8089:8000 \
  -e ZOT_ENDPOINT=http://zot-registry:5000 \
  -e ZOT_PUBLIC_DOMAIN=registry.example.com \
  bhaveshp36/zotdeck:latest
```

### Option 2: Docker Compose (Zot + ZotDeck)

Deploy both Zot and ZotDeck together in seconds:

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

---

## ⚙️ Configuration Reference

| Environment Variable | Default Value | Description |
| :--- | :--- | :--- |
| `PORT` | `8000` | Internal HTTP listening port for Uvicorn |
| `ZOT_ENDPOINT` | `http://zot-registry:5000` | Backend network URL to reach the Zot Registry |
| `ZOT_PUBLIC_DOMAIN` | `registry.example.com` | Public host domain shown in pull/push snippets |

---

## 📊 Performance & Footprint

| Metric | ZotDeck | Traditional Enterprise Registries |
| :--- | :--- | :--- |
| **Idle Memory (RAM)** | **~40 MiB** | ~1,200 MiB - 1,800 MiB |
| **Container Count** | **1 single container** | 6 - 9 containers |
| **External Database** | **None (Zero DB)** | PostgreSQL / Redis / Clair |
| **Startup Time** | **< 1.0s** | ~45s - 90s |

---

## 🛠️ Architecture & Tech Stack

- **Backend**: Python 3.11 (Alpine), FastAPI, Uvicorn, HTTPX (async I/O)
- **Frontend**: Tailwind CSS, Alpine.js (reactive state without heavy node build steps)
- **Security**: Non-root container execution (`UID 1000`), scoped token isolation

---

## 🤝 Contributing

Contributions, bug reports, and suggestions are welcome! Please refer to [CONTRIBUTING.md](CONTRIBUTING.md) for details on setting up a local development environment.

---

## 📄 License

This project is open-source software licensed under the [MIT License](LICENSE).
