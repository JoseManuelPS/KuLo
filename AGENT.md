# KuLo - Agent Documentation

> This document is optimized for AI reasoning models (Claude, GPT-5, Gemini) to understand,
> maintain, and extend the KuLo codebase without breaking concurrency or architecture patterns.

## Project Mind Map

```
kulo/
├── src/kulo/
│   ├── main.py      ─────────────────────┐
│   │   • CLI entry point (argparse)      │
│   │   • Argument validation             │
│   │   • Mode selection (TUI/Snapshot)   │
│   │   • Orchestration flow              │
│   │                                     │
│   ├── app.py       ◄────────────────────┤ imports (TUI)
│   │   • KuloApp (Textual Application)   │
│   │   • Vim-style keybindings           │
│   │   • Modal handling                  │
│   │   • Streaming integration           │
│   │                                     │
│   ├── state.py     ◄────────────────────┤ imports (TUI)
│   │   • AppState (reactive state)       │
│   │   • Filter management               │
│   │   • Pod activation tracking         │
│   │                                     │
│   ├── widgets/     ◄────────────────────┤ imports (TUI)
│   │   • LogPanel (RichLog-based)        │
│   │   • PodLegend (interactive list)    │
│   │   • HelpBar (keybinding hints)      │
│   │                                     │
│   ├── modals/      ◄────────────────────┤ imports (TUI)
│   │   • NamespaceModal                  │
│   │   • FilterModal (filter/exclude)    │
│   │   • ConfirmModal                    │
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
│   │   • LogRenderer protocol            │
│   │                                     │
│   ├── ui.py        ◄────────────────────┤ imports (CLI)
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
    ├── test_tui.py    (TUI component tests)
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

### TUI Architecture (Textual)

KuLo defaults to an interactive TUI mode using the Textual framework (use `--snap` for CLI mode):

```
┌─────────────────────────────────────────────────────────────────────┐
│                          KuloApp (Textual)                          │
│  ┌───────────────────────────────────┬───────────────────────────┐  │
│  │           LogPanel                │       PodLegend           │  │
│  │    (RichLog widget, scrollable)   │   (OptionList widget)     │  │
│  │                                   │   • ● pod-a (enabled)     │  │
│  │  [api][main] | Request received   │   • ○ pod-b (disabled)    │  │
│  │  [web][nginx] | GET /index 200    │   • ● pod-c (enabled)     │  │
│  │                                   │                           │  │
│  └───────────────────────────────────┴───────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  [n] Namespace  [f] Filter  [e] Exclude  [p] Pods  [q] Quit   │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              HelpBar                                │
└─────────────────────────────────────────────────────────────────────┘
```

**Key TUI Components:**

1. **AppState** (`state.py`): Centralized reactive state for filters and pod activation
2. **LogPanel** (`widgets/log_panel.py`): Virtual-scrolling log display with pod filtering
3. **PodLegend** (`widgets/pod_legend.py`): Interactive pod list with toggle functionality
4. **HelpBar** (`widgets/help_bar.py`): Keybinding hints and mode indicator
5. **Modals** (`modals/`): Input dialogs for filter editing

**Mode Selection Logic:**

```python
# In main.py
def is_snapshot_mode(args) -> bool:
    return args.snap  # --snap enables snapshot mode (CLI)
    # Default: TUI mode with real-time streaming
```

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
# Pass containers to calculate width only for displayed containers (respects max_containers)
self._calculate_max_prefix_width_from_containers(containers)

# In _format_log_line():
# Format: [namespace] pod_name (container_name) > message
prefix = "".join(prefix_parts)
if self._max_prefix_width > 0:
    prefix = prefix.ljust(self._max_prefix_width)  # Pad to align
```

This ensures all log lines align regardless of pod/container name lengths. The prefix width is calculated only from containers that will actually be displayed (after applying `--max-containers` limit).

### 7. LogRenderer Protocol for UI Abstraction

```python
# In manager.py
@runtime_checkable
class LogRenderer(Protocol):
    def print_log_entry(self, entry: LogEntry) -> None:
        ...

# LogManager accepts any UI implementing the protocol
async def run(self, ui: "KuloUI | LogRenderer", ...):
    ...
```

**Why this design**:
- **Decoupling**: Manager doesn't depend on specific UI implementation
- **TUI support**: KuloApp implements `print_log_entry()` for TUI rendering
- **CLI support**: KuloUI implements it for Rich console output
- **Testability**: Easy to mock for unit tests

### 8. Log Colorization Strategy

```python
# In ui.py and widgets/log_panel.py:

# Plain text logs: use pod color
message_style = "default" if self._no_color_logs else pod_color
text.append(entry.message, style=message_style)

# JSON logs: level tag keeps log level color, message uses pod color
if entry.log_level:
    level_style = "default" if self._no_color_logs else f"bold {level_color}"
    text.append(f"[{level_display}] ", style=level_style)

message_style = "default" if self._no_color_logs else pod_color
text.append(main_message, style=message_style)
```

**Colorization behavior**:
- **Plain text logs**: Message colored with pod's assigned color (from Kelly's palette)
- **JSON logs**: 
  - `[LEVEL]` tag uses log level colors (green/yellow/red based on severity)
  - Message uses pod's assigned color
  - Metadata fields remain dimmed
- **`--no-color-logs` flag**: Disables all log message colorization, uses default style

**Why this design**:
- **Pod identification**: Pod colors help visually distinguish logs from different pods
- **Level visibility**: JSON log level tags retain semantic colors for quick severity scanning
- **Consistency**: Same pod always gets same color across log lines
- **Accessibility**: `--no-color-logs` option for environments where colors aren't supported

### 9. Namespace Regex Resolution

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

### TUI Tests (test_tui.py)

- **Tests TUI components in isolation**: No terminal required
- **AppState tests**: State management, pod toggling, filtering
- **Widget tests**: LogPanel formatting, PodLegend display
- **Modal tests**: Input handling, validation
- **Mode selection tests**: TUI vs CLI flag logic

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

### Adding New TUI Keybindings

Chain of thought:

1. **Define binding in `app.py:BINDINGS`**:
   ```python
   BINDINGS = [
       ...
       Binding("x", "my_action", "Description", show=True),
   ]
   ```

2. **Implement action handler**:
   ```python
   def action_my_action(self) -> None:
       # Handle the action
       self.notify("Action triggered")
   ```

3. **Update HelpBar if needed**:
   - Add to `help_bar.py:KEYBINDINGS` for visibility
   - Update `ExpandedHelp.HELP_TEXT` for documentation

4. **Add tests to `test_tui.py`**

### Adding New TUI Modals

Chain of thought:

1. **Create modal class in `modals/`**:
   - Extend `ModalScreen[ReturnType]`
   - Define CSS for styling
   - Implement `compose()` for layout
   - Handle input validation

2. **Register in `modals/__init__.py`**

3. **Add keybinding to open modal in `app.py`**

4. **Handle modal result**:
   ```python
   async def action_my_filter(self) -> None:
       result = await self.push_screen_wait(MyModal(...))
       if result is not None:
           # Apply changes
           await self._restart_streaming()
   ```

### Modifying TUI Widgets

Chain of thought:

1. **For LogPanel changes**:
   - Preserve `_format_log_line()` signature for compatibility
   - Test with both active and inactive pods
   - Ensure filtering works with state changes

2. **For PodLegend changes**:
   - Update `_format_pod_option()` for visual changes
   - Emit `PodToggled` message for state sync
   - Call `refresh_pods()` after state updates

3. **For HelpBar changes**:
   - Keep keybindings list in sync with `app.py:BINDINGS`
   - Update both compact and expanded help

