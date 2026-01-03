# KuLo - Kubernetes Logs

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

**KuLo** is a professional tool for aggregated, filterable, and aesthetically superior Kubernetes log visualization. Built with async I/O for real concurrent streaming from multiple pods and containers. Features an **interactive TUI mode** (similar to K9s) as the default experience, with a `--snap` option for snapshot/CLI mode.

## Features

- **Interactive TUI Mode** - K9s-style interface with keybindings, pod panel, and live filter editing (default mode)
- **Real-time Streaming** - View logs from multiple pods/containers in a single unified stream
- **Smart JSON Detection** - Automatically parse JSON logs, extract log levels, and apply color coding
- **Server-side Filtering** - Use Kubernetes label selectors for efficient pod selection
- **Client-side Filtering** - Regex patterns for fine-grained pod name filtering
- **Namespace Regex Support** - Select namespaces using regex patterns (e.g., `dev-.*`)
- **Snapshot Mode** - Fetch logs once with `--snap` for scripting and quick checks
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
# Stream logs in real-time (TUI mode - default)
kulo

# Stream logs from specific namespaces
kulo -n frontend,backend

# Stream logs from namespaces matching regex patterns
kulo -n 'dev-.*'              # All dev-* namespaces
kulo -n 'prod,staging-.*'     # Mix exact names and patterns

# Snapshot mode: fetch logs once without streaming (CLI output)
kulo --snap

# Filter by label selector (server-side, efficient)
kulo -l app=web,tier=frontend

# Filter pods matching regex patterns
kulo -f 'api-.*,web-.*'

# Exclude pods matching patterns
kulo -e 'test-.*,debug-.*'

# Combine filters
kulo -n production -l app=api -f 'api-v2.*'

# Snapshot: show logs from the last hour, 100 lines per container
kulo --snap -s 1h -t 100

# Limit concurrent streams (for large deployments)
kulo --max-containers 20
```

## Interactive TUI Mode

KuLo launches an interactive TUI by default (streaming mode). Use `--snap` for snapshot/CLI mode:

```
┌─────────────────────────────────────────────┬────────────────────┐
│ [api-server][main] | Request received       │ ● api-server       │
│ [api-server][main] | Processing user 123    │ ● web-frontend     │
│ [web-frontend][nginx] | GET /index.html 200 │ ○ worker-batch     │
│ [api-server][main] | Response sent in 45ms  │                    │
└─────────────────────────────────────────────┴────────────────────┘
 [n] Namespace  [i] Include  [e] Exclude  [p] Pods  [?] Help  [q] Quit
```

### TUI Keybindings

| Key | Action |
|-----|--------|
| `Space` | Pause/resume log streaming |
| `n` | Change namespace filter (supports regex) |
| `f` | Set filter pattern for pod names |
| `e` | Set exclude pattern for pod names |
| `l` | Set Kubernetes label selector |
| `p` | Toggle pod panel visibility |
| `a` | Enable all pods |
| `z` | Disable all pods |
| `c` | Clear log display |
| `s` | Toggle auto-scroll |
| `?` | Show/hide expanded help |
| `q` | Quit application |
| `Esc` | Close modal/overlay |

### Pod Panel

The right panel shows all discovered pods with their assigned colors:
- **● Filled circle**: Pod is active (logs shown)
- **○ Empty circle**: Pod is disabled (logs hidden)

Click on a pod or press Enter to toggle its visibility.

## CLI Reference

| Argument | Alias | Type | Default | Description |
|----------|-------|------|---------|-------------|
| `--namespace` | `-n` | str | context | Comma-separated namespaces or regex patterns |
| `--label-selector` | `-l` | str | - | K8s label selector (server-side) |
| `--filter` | `-f` | str | - | Filter pods matching regex (comma-separated) |
| `--exclude` | `-e` | str | - | Exclude pods matching regex (comma-separated) |
| `--exclude-init` | - | flag | false | Omit init containers |
| `--exclude-ephemeral` | - | flag | false | Omit ephemeral containers |
| `--snap` | - | flag | false | Snapshot mode: fetch logs once (CLI output) |
| `--since` | `-s` | str | 10m | Time window (e.g., 30s, 5m, 1h, 2d) |
| `--tail` | `-t` | int | 25 | Initial lines per container |
| `--max-containers` | - | int | 10 | Maximum concurrent streams (0 = unlimited) |
| `--no-color-logs` | - | flag | false | Disable log message colorization (plain output) |
| `--verbose` | `-v` | flag | false | Increase verbosity (-v, -vv) |

## Output Format

KuLo displays logs in a structured, aligned format (in `--snap` mode):

```
[NAMESPACE] POD (CONTAINER)      > Log message
```

All log prefixes are padded to the same width based on the containers being displayed (respecting `--max-containers`), ensuring clean alignment across all log lines.

### Smart Omission

- **Single namespace**: The `[NAMESPACE]` prefix is omitted
- **Single container per pod**: The `(CONTAINER)` suffix is omitted

### Deterministic Colors

Pods are assigned colors deterministically based on their names (sorted alphabetically). This ensures:
- Same pods always get the same colors across executions
- No color repetition until the palette (20 colors) is exhausted
- Visually distinct output for easier log tracking

### Log Colorization

KuLo uses pod colors for log messages to help visually distinguish logs from different pods:

- **Plain text logs**: Message is colored with the pod's assigned color
- **JSON logs**: 
  - `[LEVEL]` tag uses log level colors (green for INFO, yellow for WARN, red for ERROR, etc.)
  - Message uses the pod's assigned color
  - Metadata fields remain dimmed

Use `--no-color-logs` to disable all log message colorization for plain output.

### JSON Log Intelligence

When KuLo detects a JSON log line, it:

1. Extracts the log level (`level`, `severity`) for color coding the `[LEVEL]` tag:
   - `INFO` → Green
   - `WARN/WARNING` → Yellow
   - `ERROR/FATAL` → Red
   - `DEBUG` → Dimmed

2. Extracts the main message (`msg`, `message`) for prominent display (colored with pod color)

3. Shows remaining fields as dimmed metadata

**Example:**

```
Input:  {"level":"INFO","msg":"Request received","path":"/api/users","method":"GET"}
Output: api-server (api) > [INFO] Request received path=/api/users method=GET
```

The `[INFO]` tag appears in green (log level color), while "Request received" appears in the pod's assigned color.

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
                              ┌───────────────────┬──────┴──────┐
                              │                   │             │
                              v                   v             v
                     ┌─────────────────┐ ┌─────────────┐ ┌────────────┐
                     │  TUI (Textual)  │ │  CLI (Rich) │ │  Pod Panel │
                     │   Log Panel     │ │   Console   │ │  Help Bar  │
                     └─────────────────┘ └─────────────┘ └────────────┘
```

This architecture:
- Prevents UI blocking from network I/O
- Enables true concurrent streaming from multiple containers
- Handles reconnection and pod rotation gracefully
- Default TUI mode for interactive exploration, `--snap` for CLI output

See [AGENT.md](AGENT.md) for detailed architecture documentation.

## Requirements

- Python 3.12+
- Access to a Kubernetes cluster via `~/.kube/config`
- Permissions to list pods and read logs

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please read the contribution guidelines and submit pull requests for any enhancements.

