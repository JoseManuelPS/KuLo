# KuLo - Agent Documentation

> This document is optimized for AI reasoning models (Claude, GPT-5, Gemini) to understand,
> maintain, and extend the KuLo codebase without breaking concurrency or architecture patterns.

## Project Mind Map

```
kulo/
├── src/
│   ├── main.py      ─────────────────────┐
│   │   • CLI entry point (argparse)      │
│   │   • Argument validation             │
│   │   • Orchestration flow              │
│   │                                     │
│   ├── client.py    ◄────────────────────┤ imports
│   │   • KuloClient (async context mgr)  │
│   │   • Pod discovery                   │
│   │   • Log streaming with reconnection │
│   │                                     │
│   ├── manager.py   ◄────────────────────┤ imports
│   │   • LogManager (Producer-Consumer)  │
│   │   • asyncio.Queue coordination      │
│   │   • Signal handling (SIGINT)        │
│   │   • Pod rotation watching           │
│   │                                     │
│   ├── ui.py        ◄────────────────────┤ imports
│   │   • KuloUI (Rich console)           │
│   │   • JSON log detection              │
│   │   • ColorAssigner integration       │
│   │   • Prefix alignment (padding)      │
│   │   • Smart field omission            │
│   │                                     │
│   ├── utils.py     ◄────────────────────┘ imports
│   │   • Duration parsing (10s → 10)
│   │   • Regex compilation
│   │   • ColorAssigner (deterministic)
│   │   • Namespace regex detection
│   │   • Backoff calculation
│   │
│   └── models.py
│       • PodInfo, ContainerInfo
│       • LogEntry, StreamContext
│       • Immutable dataclasses
│
└── tests/
    ├── test_unit.py   (mock-based, no network)
    └── test_e2e.py    (real cluster, @pytest.mark.e2e)
```

## Architecture Context

### Why kubernetes_asyncio?

The standard `kubernetes` Python client uses synchronous blocking I/O. When streaming logs
from multiple containers simultaneously, this would require threads and complex synchronization.

`kubernetes_asyncio` provides:
- True async/await for all K8s API calls
- Non-blocking log streaming via `aiohttp`
- Native integration with `asyncio.Queue`

**Critical**: Never mix sync kubernetes client with async code. Always use `await`.

### Why Producer-Consumer Pattern?

```
┌──────────────┐
│  Producer 1  │──┐
│  (pod-a/c1)  │  │
└──────────────┘  │     ┌──────────────┐     ┌──────────────┐
                  ├────>│    Queue     │────>│   Consumer   │────> Terminal
┌──────────────┐  │     │ (LogEntry)   │     │   (UI)       │
│  Producer 2  │──┤     └──────────────┘     └──────────────┘
│  (pod-a/c2)  │  │
└──────────────┘  │
                  │
┌──────────────┐  │
│  Producer N  │──┘
│  (pod-b/c1)  │
└──────────────┘
```

**Problem solved**: If UI rendering and network I/O were in the same coroutine:
- Slow terminal writes would block receiving log lines
- Network delays would freeze the UI
- Exception in one stream would affect others

**Solution**: Producers push to queue, single consumer renders. They are fully decoupled.

### Concurrency Model

```python
# main.py orchestration flow
async def run_kulo(args):
    async with KuloClient.create() as client:  # Context manager for cleanup
        manager = LogManager(client)
        await manager.run(
            containers=containers,
            ui=ui,
            follow=args.follow,
            ...
        )

# manager.py internal structure
class LogManager:
    def __init__(self):
        self.queue = asyncio.Queue()      # Thread-safe async queue
        self.stop_event = asyncio.Event() # Shutdown signal
        self.producer_tasks = set()        # Track active tasks
        self._semaphore = None             # Throttling

    async def run(self, containers, ui, ...):
        # Start consumer FIRST (must be ready before producers)
        self._consumer_task = asyncio.create_task(self._consume_logs(ui))

        # Start producers with semaphore for throttling
        for container in containers:
            await self._start_producer(container, ...)

        # Wait for completion or stop signal
        await self._wait_for_completion(follow)
```

## Key Design Decisions

### 1. Immutable Data Models

```python
@dataclass(frozen=True, slots=True)
class ContainerInfo:
    namespace: str
    pod_name: str
    ...
```

- `frozen=True`: Prevents accidental mutation in async context
- `slots=True`: Memory optimization for many instances

### 2. Semaphore-based Throttling

```python
self._semaphore = asyncio.Semaphore(max_concurrent)

async def _produce_logs(self, context):
    async with self._semaphore:  # Limits concurrent streams
        async for line in client.stream_logs(context):
            await self.queue.put(entry)
```

This prevents API server overload when selecting many containers.

### 3. Exponential Backoff for Reconnection

```python
def calculate_backoff(retry_count: int, base=1.0, max_backoff=60.0) -> float:
    return min(base * (2 ** retry_count), max_backoff)

# Usage in stream_logs:
# Retry 0: 1s, Retry 1: 2s, Retry 2: 4s, ... capped at 60s
```

### 4. Context Manager for Client Lifecycle

```python
@asynccontextmanager
async def create(cls) -> AsyncIterator[Self]:
    await config.load_kube_config()
    api_client = client.ApiClient()
    try:
        yield cls(api_client)
    finally:
        await api_client.close()  # CRITICAL: Always close connections
```

**Warning**: Failing to close `api_client` causes resource leaks and socket exhaustion.

### 5. Deterministic Color Assignment (ColorAssigner)

```python
class ColorAssigner:
    def initialize(self, pod_names: list[str]) -> None:
        # Sort pods alphabetically for deterministic ordering
        sorted_pods = sorted(pod_names)
        for pod_name in sorted_pods:
            self._assign_next_color(pod_name)

    def get_color(self, pod_name: str) -> str:
        if pod_name not in self._assignments:
            self._assign_next_color(pod_name)  # Dynamic pods
        return self._assignments[pod_name]
```

**Why this design**:
- **Deterministic**: Same pods always get same colors across executions
- **No repetition**: Colors are assigned sequentially, avoiding collisions
- **Dynamic support**: New pods get the next available color

### 6. Prefix Alignment for Readable Output

```python
# In configure_output():
self._calculate_max_prefix_width(namespaces, pods)

# In _format_log_line():
prefix = "".join(prefix_parts)
if self._max_prefix_width > 0:
    prefix = prefix.ljust(self._max_prefix_width)  # Pad to align
```

This ensures all log lines align regardless of pod/container name lengths.

### 7. Namespace Regex Resolution

```python
# In main.py:
if any(is_regex_pattern(ns) for ns in namespace_args):
    namespaces = await resolve_namespace_patterns(client, namespace_args, ui)
else:
    # Validate exact names exist
    for ns in namespace_args:
        if not await client.check_namespace_exists(ns):
            ui.print_error(f"Namespace '{ns}' does not exist")

# Detection uses regex metacharacters: .*+?^${}()|[]\
def is_regex_pattern(pattern: str) -> bool:
    return bool(REGEX_METACHARACTERS.search(pattern))
```

**Important**: Regex resolution requires `list namespaces` permission. Falls back to error if denied.

## Maintenance Protocols

### Adding a New CLI Argument

Chain of thought:

1. **Add to `main.py:create_parser()`**
   - Define argument with type, default, help text
   - Consider short alias (-x) if commonly used

2. **Validate in `run_kulo()` if needed**
   - Add to validation block before K8s connection

3. **Pass through to relevant components**
   - Manager.run() for streaming behavior
   - UI methods for display behavior

4. **Update README.md CLI reference table**

### Modifying Log Streaming Behavior

Chain of thought:

1. **Identify the layer**:
   - Transport: `client.py` (API calls, reconnection)
   - Coordination: `manager.py` (queue, tasks, signals)
   - Display: `ui.py` (formatting, colors)

2. **For client.py changes**:
   - Test with mocked API responses first
   - Handle all ApiException status codes
   - Preserve exponential backoff logic

3. **For manager.py changes**:
   - Never block the event loop
   - Always check `stop_event` in loops
   - Use `create_task()` for new concurrent work

4. **For ui.py changes**:
   - Keep rendering fast (no I/O)
   - Test with both JSON and plain text logs

### Debugging Concurrency Issues

```python
# Enable asyncio debug mode
import asyncio
asyncio.get_event_loop().set_debug(True)

# Or via environment
PYTHONASYNCIODEBUG=1 python -m kulo.main ...
```

Common issues:

1. **Queue deadlock**: Consumer stopped but producers still pushing
   - Solution: Always send `None` sentinel to stop consumer

2. **Task leak**: Tasks created but not awaited
   - Solution: Use `add_done_callback` and track in `producer_tasks` set

3. **Signal handler not working**: On Windows
   - Solution: Use `stop_event.set()` polling instead of signal handlers

### Adding Support for New Log Formats

1. **Modify `ui.py:_try_parse_json()`** for detection
2. **Add field names to `utils.py:LOG_LEVEL_FIELDS` / `MESSAGE_FIELDS`**
3. **Add color mappings to `utils.py:LOG_LEVEL_COLORS`**
4. **Add unit tests to `test_unit.py:TestExtractLogLevel`**

## Testing Strategy

### Unit Tests (test_unit.py)

- **No network calls**: All K8s interactions mocked
- **Fast execution**: <5 seconds total
- **Coverage targets**:
  - `utils.py`: 100%
  - `models.py`: 100%
  - `ui.py` (formatting logic): 90%+

### E2E Tests (test_e2e.py)

- **Requires real cluster**: kind or minikube
- **Creates actual resources**: Namespace, Pods
- **Tests real streaming**: With actual log output
- **Chaos scenarios**: Pod deletion during stream

Run with: `pytest -m e2e`

## Common Pitfalls

### 1. Forgetting await

```python
# WRONG - coroutine not executed
pods = client.list_pods(namespace)

# CORRECT
pods = await client.list_pods(namespace)
```

### 2. Blocking the Event Loop

```python
# WRONG - blocks entire async loop
import time
time.sleep(5)

# CORRECT
await asyncio.sleep(5)
```

### 3. Not Handling Cancellation

```python
# WRONG - ignores cancellation
async def stream_forever():
    while True:
        line = await get_next_line()
        process(line)

# CORRECT - respects cancellation
async def stream_forever(stop_event):
    while not stop_event.is_set():
        try:
            line = await asyncio.wait_for(get_next_line(), timeout=1.0)
            process(line)
        except asyncio.TimeoutError:
            continue
```

### 4. Resource Leaks

```python
# WRONG - connection never closed on error
api_client = ApiClient()
result = await do_something(api_client)
await api_client.close()

# CORRECT - always closes via context manager
async with KuloClient.create() as client:
    result = await do_something(client)
```

## Extension Points

### Adding New Filter Types

1. Add argument in `main.py:create_parser()`
2. Add filter logic in `main.py:filter_pods()` or `main.py:get_containers()`
3. Consider if server-side (label selector) or client-side (regex)

### Supporting New Output Formats

1. Create new class in `ui.py` implementing same interface
2. Add format selection argument
3. Swap implementation in `run_kulo()`

### Adding Metrics/Observability

1. Add counters to `LogManager` (lines received, errors, reconnections)
2. Expose via optional metrics endpoint or periodic log summary
3. Consider prometheus_client for structured metrics

