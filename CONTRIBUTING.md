# Contributing to ZotDeck

Thank you for your interest in contributing to ZotDeck!

## Local Development Setup

### Prerequisites
- Python 3.11+
- Docker or Podman
- Git

### 1. Clone the repository
```bash
git clone https://github.com/bhaveshp36/zotdeck.git
cd zotdeck
```

### 2. Set up virtual environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Run the development server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Build the container locally
```bash
docker build -t zotdeck:dev .
```

## Pull Request Guidelines

1. Fork the repository and create your branch from `main`.
2. Ensure your changes maintain low memory overhead and clean async I/O.
3. Test your endpoints and templates thoroughly.
4. Submit a Pull Request describing your changes and benefits.
