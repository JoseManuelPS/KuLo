<identity>
You are a Senior Staff SRE and Software Architect specializing in Cloud Native technologies. Your expertise lies in building Python CLI tools that are highly efficient, resilient, and offer an impeccable developer experience (DX) for managing large-scale Kubernetes clusters.
</identity>

<thinking_process_directive>
Before writing code, perform an internal analysis following these steps:
1.  **Concurrency Architecture (Producer-Consumer)**:
    *   **Producers**: `asyncio` tasks that read K8s streams and push to an `asyncio.Queue`.
    *   **Consumer**: Dedicated task that reads from the queue and updates the `Rich` UI. Avoid mixing networking and drawing logic to prevent blocking the Loop or freezing the terminal.
2.  **Time Logic**: Implement a helper function to parse human-readable time strings (e.g., '10s', '5m', '1h') into integer seconds. This is mandatory as the Kubernetes API only accepts `since_seconds` (int).
3.  **Scope Resolution**: Define namespace priority: Argument -n (list) > Current context namespace > 'default'.
4.  **Resource Management**: Ensure stream connections close correctly upon receiving an interruption signal (SIGINT).
5.  **Output Efficiency**: When only one namespace is used, omit the [NAMESPACE] value in the output. When a pod has only one container, omit the [CONTAINER] value. Plan how to implement this optimization.
6.  **Modes of Operation**: Plan how to implement different operation modes and the restrictions applicable to each.
7.  **Color Management**: Plan how to implement consistent color management.
8.  **Inconsistent Pod Management**: Plan how to handle Pods in `Unknown`, `crashloopbackoff` states, etc.
</thinking_process_directive>

<task_specification>
Develop the professional script `kulo.py`. The goal is to visualize Kubernetes logs in an aggregated, filterable, and aesthetically superior manner.

### 1. KUBERNETES TECHNICAL REQUIREMENTS
- **Client**: Use the `kubernetes_asyncio` library for Python (critical for real concurrent streaming).
- **Project Management**: Use `uv` for dependency management and generate a modern `pyproject.toml`.
- **Authentication**: automatic loading from `~/.kube/config`.
- **Container Support**: The script must discover and show logs for: `initContainers`, `containers`, and `ephemeralContainers`.
- **Efficiency**: Minimize API calls. Use 'server-side' filtering (Label Selectors) whenever possible before 'client-side' filtering (Regex).
- **API Protection (Throttling)**: Introduce a safety limit to avoid saturating the API Server or the local client. Default to processing a maximum of 10 concurrent containers. If the selector returns more, show a Warning and process only the first N. Allow adjustment via `--max-containers`.

### 2. NAMESPACE LOGIC AND FILTERING
- **Namespaces**:
    - Default: Use the current context's namespace.
    - Custom: The `-n, --namespace` argument must accept a comma-separated list (e.g., `frontend,backend`).
- **Label Selectors (Server-side)**:
    - Add the `-l, --label-selector` argument (e.g., `app=frontend,tier=backend`).
    - **Priority**: This filter is applied in the Kubernetes API call to drastically reduce network and CPU load. Applied BEFORE regex filtering.
- **Regex Filtering**:
    - `-i, --include`: Only include pods whose names match the patterns (comma-separated list).
    - `-e, --exclude`: Omit pods matching these patterns (comma-separated list).
    - `--exclude-init`: Omit containers of type `initContainers`.
    - `--exclude-ephemeral`: Omit containers of type `ephemeralContainers`.
    - Filtering must be case-insensitive by default.

### 3. LOG MODES AND PARAMETERS
- **Snapshot Mode (Default)**: Shows the last `N` lines and terminates.
- **Follow Mode (`-f, --follow`)**:
    - Real-time streaming.
    - **Resilience**: Implement reconnection logic with *exponential backoff* if the stream is cut.
    - **Pod Rotation**: If a pod terminates and is replaced (e.g., RollingUpdate), the script must detect the new pod and attach automatically.
- **Time Window (`-s, --since`)**: Supports formats like '10m', '1h', '30s'.
- **Lines (`-t, --tail`)**: Defines how many lines to retrieve initially (default 25).

### 4. VISUAL INTERFACE ('Rich' Library)
- **Line Structure**: `[NAMESPACE][POD][CONTAINER] | Log message`.
- **JSON Intelligence**: Automatically detect if a log line is valid JSON. If so:
    - Parse the JSON and extract the log level ('level') to color the line (INFO=green, ERROR=red, WARN=yellow).
    - Extract the main message ('msg', 'message') to display it prominently.
    - Show remaining fields as dimmed metadata.
- **Colors**: Assign a unique color to each Pod to facilitate visual tracking.
- **Style**: Use `rich.console` for clean output, with informative tables at the start summarizing which pods are being observed.

### 5. CODE QUALITY (2025 STANDARDS)
- Python 3.12+ using Type Hints exhaustively.
- **Style and Naming**: Strict adherence to **PEP 8** for naming conventions and code formatting.
- Robust exception handling (permission denied, non-existent namespaces, deleted pods).
- Complete documentation following Google style.
- Implementation of `signal` for clean and orderly shutdown.
- Implementation of `pytest` for unit and integration tests.
</task_specification>

<cli_interface_reference>
| Argument | Alias | Type | Description |
| :--- | :--- | :--- | :--- |
| `--namespace` | `-n` | str | List of namespaces (comma-separated). |
| `--label-selector` | `-l` | str | K8s Label Selector (server-side). |
| `--include` | `-i` | str | Inclusion Regex (comma-separated). |
| `--exclude` | `-e` | str | Exclusion Regex (comma-separated). |
| `--exclude-init` | N/A | flag | Omit `initContainers`. |
| `--exclude-ephemeral` | N/A | flag | Omit `ephemeralContainers`. |
| `--follow` | `-f` | flag | Real-time streaming. |
| `--since` | `-s` | str | Time (e.g., 5m, 1h). Def: 10m. |
| `--tail` | `-t` | int | Tail lines. Def: 20. |
| `--max-containers` | N/A | int | Max concurrent streams limit. Def: 10. |
</cli_interface_reference>

<output_instructions>
1.  **Modern Project Configuration**:
    *   Generate a complete `pyproject.toml` compatible with `uv` (Astral).
    *   Include production dependencies (`kubernetes_asyncio`, `rich`) and development dependencies (`pytest`, `pytest-asyncio`, `respx` or `pytest-mock`).
    *   Provide `uv` commands to initialize the environment and run the tool.

2.  **Source Code**:
    *   Deliver the complete `kulo.py` code. Must include Google-style docstrings and correct shebang.
    *   Ensure the Producer-Consumer architecture is clearly separated into functions/classes.

3.  **Test Suite (Hybrid)**:
    *   **Unit (Mock-first)**: Generate `tests/test_unit.py`. Must validate internal logic (JSON parsing, throttling, queues) without network.
    *   **Integration (Real Cluster)**: Generate `tests/test_e2e.py`.
        *   These tests assume an active cluster (`kind` or `minikube`) and configured context.
        *   Must create real resources (Namespaces, Pods logging JSON and plain text), execute `kulo.py` against them, and validate output.
        *   Include **Chaos** scenarios: delete a pod while streaming to verify automatic reconnection.
        *   Mark these tests with `@pytest.mark.e2e` so they don't run by default.

4.  **Documentation**:
    *   `README.md`: Usage guide for humans.
    *   `AGENT.md`: Documentation **optimized for Reasoning Models (Gemini 3 / Claude 4.5)**. Must include:
        *   **Project Mind Map**: Relationships between Async/Sync components.
        *   **Architecture Context**: Explanation of key decisions (why kubernetes_asyncio, why Producer-Consumer).
        *   **Maintenance Protocols**: Precise instructions (suggested Chain-of-Thought prompts) for future agents to debug or extend the tool without breaking concurrency.
</output_instructions>