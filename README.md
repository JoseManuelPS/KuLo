# KuLo - Kubernetes Log Aggregator

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

**KuLo** is a professional CLI tool for aggregated, filterable, and aesthetically superior Kubernetes log visualization. Built with async I/O for real concurrent streaming from multiple pods and containers.

## Features

- **Aggregated Log Streaming** - View logs from multiple pods/containers in a single unified stream
- **Smart JSON Detection** - Automatically parse JSON logs, extract log levels, and apply color coding
- **Server-side Filtering** - Use Kubernetes label selectors for efficient pod selection
- **Client-side Filtering** - Regex patterns for fine-grained pod name filtering
- **Namespace Regex Support** - Select namespaces using regex patterns (e.g., `dev-.*`)
- **Follow Mode** - Real-time streaming with automatic reconnection on failures
- **Pod Rotation** - Auto-detect new pods during rolling updates
- **Beautiful Output** - Rich terminal UI with aligned prefixes and deterministic color coding per pod
- **Single Binary** - Distribute as a self-contained executable

## Installation

### Using uv (Recommended)

```bash
# Clone the repository
git clone https://github.com/kulo/kulo.git
cd kulo

# Install with uv
uv sync

# (Optional) Activate the virtual environment
# This allows you to run 'kulo' directly without 'uv run'
source .venv/bin/activate

# Run KuLo
uv run kulo --help
# Or if activated: kulo --help
```

### Using pip

```bash
pip install -e .
kulo --help
```

### Binary Distribution

Download the pre-built binary for your platform from the releases page:

```bash
# Download and make executable
chmod +x kulo-linux-amd64
sudo mv kulo-linux-amd64 /usr/local/bin/kulo

# Verify installation
kulo --version
```

## Quick Start

```bash
# View logs from the current namespace (last 10 minutes, 25 lines per container)
kulo

# View logs from specific namespaces
kulo -n frontend,backend

# View logs from namespaces matching regex patterns
kulo -n 'dev-.*'              # All dev-* namespaces
kulo -n 'prod,staging-.*'     # Mix exact names and patterns

# Follow logs in real-time
kulo -f

# Filter by label selector (server-side, efficient)
kulo -l app=web,tier=frontend

# Include only pods matching regex patterns
kulo -i 'api-.*,web-.*'

# Exclude pods matching patterns
kulo -e 'test-.*,debug-.*'

# Combine filters
kulo -n production -l app=api -i 'api-v2.*' -f

# Show logs from the last hour, 100 lines per container
kulo -s 1h -t 100

# Limit concurrent streams (for large deployments)
kulo --max-containers 20
```

## CLI Reference

| Argument | Alias | Type | Default | Description |
|----------|-------|------|---------|-------------|
| `--namespace` | `-n` | str | context | Comma-separated namespaces or regex patterns |
| `--label-selector` | `-l` | str | - | K8s label selector (server-side) |
| `--include` | `-i` | str | - | Include pods matching regex (comma-separated) |
| `--exclude` | `-e` | str | - | Exclude pods matching regex (comma-separated) |
| `--exclude-init` | - | flag | false | Omit init containers |
| `--exclude-ephemeral` | - | flag | false | Omit ephemeral containers |
| `--follow` | `-f` | flag | false | Real-time streaming mode |
| `--since` | `-s` | str | 10m | Time window (e.g., 30s, 5m, 1h, 2d) |
| `--tail` | `-t` | int | 25 | Initial lines per container |
| `--max-containers` | - | int | 10 | Maximum concurrent streams |
| `--verbose` | `-v` | flag | false | Increase verbosity (-v, -vv) |

## Output Format

KuLo displays logs in a structured, aligned format:

```
[NAMESPACE][POD][CONTAINER]      | Log message
```

All log prefixes are padded to the same width based on the longest pod/container combination, ensuring clean alignment across all log lines.

### Smart Omission

- **Single namespace**: The `[NAMESPACE]` prefix is omitted
- **Single container per pod**: The `[CONTAINER]` prefix is omitted

### Deterministic Colors

Pods are assigned colors deterministically based on their names (sorted alphabetically). This ensures:
- Same pods always get the same colors across executions
- No color repetition until the palette (20 colors) is exhausted
- Visually distinct output for easier log tracking

### JSON Log Intelligence

When KuLo detects a JSON log line, it:

1. Extracts the log level (`level`, `severity`) for color coding:
   - `INFO` → Green
   - `WARN/WARNING` → Yellow
   - `ERROR/FATAL` → Red
   - `DEBUG` → Dimmed

2. Extracts the main message (`msg`, `message`) for prominent display

3. Shows remaining fields as dimmed metadata

**Example:**

```
Input:  {"level":"INFO","msg":"Request received","path":"/api/users","method":"GET"}
Output: [api-server][api] | [INFO] Request received path=/api/users method=GET
```

## Development

### Setup

```bash
# Clone and setup
git clone https://github.com/kulo/kulo.git
cd kulo

# Install with development dependencies
uv sync --all-extras

# Run tests
uv run pytest

# Run linting
uv run ruff check src/
uv run mypy src/
```

### Dependency Management

This project uses `uv` for lightning-fast dependency management.

- **`pyproject.toml`**: Defines high-level dependencies and project metadata.
- **`uv.lock`**: A lockfile ensuring reproducible installs across all environments. Do not edit this file manually.
- **Updating dependencies**: To update all packages to their latest compatible versions:
  ```bash
  uv lock --upgrade
  uv sync
  ```

### Running Tests

```bash
# Unit tests only (no cluster required)
uv run pytest tests/test_unit.py

# E2E tests (requires kind/minikube cluster)
uv run pytest -m e2e tests/test_e2e.py

# All tests with coverage
uv run pytest --cov=kulo
```

### Building Binary

```bash
# Build for current platform
uv run python scripts/build.py

# Build with custom name
uv run python scripts/build.py --name kulo-linux-amd64

# Debug build
uv run python scripts/build.py --debug
```

## Architecture

KuLo uses a **Producer-Consumer** pattern for efficient log streaming:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   K8s API       │────>│   Producers     │────>│   Queue         │
│   (Streams)     │     │   (async tasks) │     │   (asyncio)     │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         │
                                                         v
                                                ┌─────────────────┐
                                                │   Consumer      │
                                                │   (UI render)   │
                                                └────────┬────────┘
                                                         │
                                                         v
                                                ┌─────────────────┐
                                                │   Rich Console  │
                                                └─────────────────┘
```

This architecture:
- Prevents UI blocking from network I/O
- Enables true concurrent streaming from multiple containers
- Handles reconnection and pod rotation gracefully

See [AGENT.md](AGENT.md) for detailed architecture documentation.

## Requirements

- Python 3.12+
- Access to a Kubernetes cluster via `~/.kube/config`
- Permissions to list pods and read logs

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please read the contribution guidelines and submit pull requests for any enhancements.

