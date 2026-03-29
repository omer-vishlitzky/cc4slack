# Code Guidelines

## 1. Type Safety

Every function signature must:
- Start with `*` (keyword-only arguments) or `self, *` for methods
- Have type hints on all parameters and return type
- Use parameterized containers: `dict[str, str]` not `dict`, `list[ThreadState]` not `list`
- Use concrete types, not `Any` (unless interfacing with an untyped external API)

```python
# Wrong
def process(data, options, verbose):
def fetch(url: str) -> dict:

# Right
def process(*, data: dict[str, str], options: Options, verbose: bool) -> Result:
def fetch(*, url: str) -> dict[str, str]:
```

## 2. Fail Fast — No Fallbacks

Delete every:
- `try`/`except` that swallows errors (except at system boundaries: HTTP handlers, WebSocket handlers)
- `.get()` with a default value that masks missing data
- `or []`, `or {}`, `or ""` fallback patterns
- `Optional` types that exist only to support a fallback
- `if x is not None` guards that hide missing data

```python
# Wrong
value = data.get("key", {})
items = result or []
try:
    do_thing()
except Exception:
    pass

# Right
value = data["key"]
items = result
do_thing()
```

## 3. Single Path of Execution

Every feature has exactly one code path. No optional backends, no feature flags, no "if available use X else fall back to Y."

```python
# Wrong — two paths
if redis_url:
    store = RedisStore(redis_url)
else:
    store = MemoryStore()

# Right — one path, crash if not configured
store = RedisStore(redis_url=settings.redis_url)
```

Any divergence from the happy path is a fail-fast scenario:
- Missing config → crash with clear error at startup
- Bad data → crash with traceback (not silently skip)
- External service down → propagate the error (don't swallow it)

## Exceptions to these rules

- **HTTP/WebSocket handlers** may catch exceptions at the boundary to return error responses
- **Slack API calls** (reactions, message posting) may catch exceptions for best-effort operations (adding a reaction failing shouldn't crash the bot)
- **Reconnection loops** may catch connection errors to retry
