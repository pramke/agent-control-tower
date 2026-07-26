"""Core tracer: Span with nesting, ACTTracer with batched upload."""

import functools
import threading
import time
import uuid

import httpx


class Span:
    """A trace span with optional children (nested hierarchy)."""

    def __init__(self, name: str, input_data: dict | None = None):
        self.id = str(uuid.uuid4())[:8]
        self.name = name
        self.input = input_data or {}
        self.output: dict | None = None
        self.start_time = time.time()
        self.end_time: float | None = None
        self.children: list[Span] = []
        self.token_usage: dict | None = None
        self.model: str | None = None
        self.error: str | None = None

    def child(self, name: str, **kwargs) -> "Span":
        """Create a child span nested under this one."""
        child = Span(name, kwargs if kwargs else None)
        self.children.append(child)
        return child

    def add_llm_call(
        self,
        name: str,
        model: str,
        input_data: dict,
        output_data: dict,
        token_usage: dict,
    ) -> "Span":
        """Add an LLM call as a child span with token tracking."""
        llm_span = self.child(name)
        llm_span.input = input_data
        llm_span.output = output_data
        llm_span.model = model
        llm_span.token_usage = token_usage
        return llm_span

    def close(self, output: dict | None = None):
        self.end_time = time.time()
        self.output = output or {}

    @property
    def duration_ms(self) -> float:
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time) * 1000
        return 0

    def to_list(self) -> list[dict]:
        """Flatten self + descendants into a list for upload."""
        items = [{
            "span_id": self.id,
            "parent_span_id": None,
            "name": self.name,
            "input": self.input,
            "output": self.output,
            "duration_ms": round(self.duration_ms, 2),
            "token_usage": self.token_usage,
            "model": self.model,
            "error": self.error,
        }]
        for child in self.children:
            child_items = child.to_list()
            child_items[0]["parent_span_id"] = self.id
            items.extend(child_items)
        return items


class ACTTracer:
    """Trace collector with batched HTTP upload."""

    def __init__(self, project_id: int, api_key: str, base_url: str = "http://127.0.0.1:8001"):
        self.project_id = project_id
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.buffer: list[dict] = []
        self.lock = threading.Lock()
        self._max_batch = 50

    def start_span(self, name: str, **kwargs) -> Span:
        return Span(name, kwargs if kwargs else {})

    def end_trace(self, root: Span, output: dict | None = None):
        """Close root span and queue the full tree for upload."""
        root.close(output)
        flat = root.to_list()
        payload = {
            "trace_id": str(uuid.uuid4()),
            "name": root.name,
            "input": root.input,
            "output": root.output,
            "duration_ms": round(root.duration_ms, 2),
            "project_id": self.project_id,
            "spans": flat,
        }
        with self.lock:
            self.buffer.append(payload)
            # Auto-flush when batch reaches threshold to reduce HTTP roundtrips
            if len(self.buffer) >= self._max_batch:
                self.flush()

    def get_prompt(self, name: str, version: int | None = None) -> dict | None:
        """Fetch a prompt from the platform by name and optional version.

        Returns dict with keys: id, name, content, version.
        Returns None if the prompt is not found or the request fails.
        """
        params: dict = {"project_id": self.project_id}
        if version:
            params["version"] = version
        try:
            resp = httpx.get(
                f"{self.base_url}/api/prompts/{name}",
                params=params,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            # Prompt lookup is best-effort — never crash on network errors
            pass
        return None

    def flush(self):
        with self.lock:
            if not self.buffer:
                return
            batch = self.buffer[:]
            self.buffer = []
        try:
            httpx.post(
                f"{self.base_url}/api/traces/ingest",
                json={"traces": batch},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10,
            )
        except Exception:
            pass


# Module-level singleton — init() sets it, get_tracer() reads it
_tracer: ACTTracer | None = None


def init(project_id: int, api_key: str, base_url: str = "http://127.0.0.1:8001"):
    global _tracer
    _tracer = ACTTracer(project_id, api_key, base_url)


def observe(name: str | None = None):
    """Decorator: wrap a function call in a root trace span."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            span_name = name or func.__name__
            tracer = _tracer
            # Pass-through when SDK is not initialized — zero overhead
            if tracer is None:
                return func(*args, **kwargs)
            span = tracer.start_span(span_name, args=str(args), kwargs=str(kwargs))
            try:
                result = func(*args, **kwargs)
                tracer.end_trace(span, {"result": str(result)[:1000]})
                return result
            except Exception as e:
                span.error = str(e)
                tracer.end_trace(span, {"error": str(e)})
                raise

        return wrapper

    return decorator


def trace(name: str | None = None):
    """Context manager: create a root trace span."""

    class TraceContext:
        def __init__(self, span_name: str):
            self.name = span_name
            self.span: Span | None = None

        def __enter__(self):
            tracer = _tracer
            if tracer:
                self.span = tracer.start_span(self.name)
            return self.span

        def __exit__(self, exc_type, exc_val, exc_tb):
            tracer = _tracer
            if tracer and self.span:
                if exc_type:
                    self.span.error = str(exc_val)
                    tracer.end_trace(self.span, {"error": str(exc_val)})
                else:
                    tracer.end_trace(self.span)
            return False

    return TraceContext(name or "trace")


def get_tracer() -> ACTTracer | None:
    """Return the global tracer instance, or None if not initialized."""
    return _tracer


def get_prompt(name: str, version: int | None = None) -> dict | None:
    """Fetch a prompt from the platform. Requires prior init() call.

    Usage:
        from act_sdk import init, get_prompt
        init(project_id=1, api_key="tg_xxx")
        prompt = get_prompt("system-prompt")
        if prompt:
            print(prompt["content"])
    """
    tracer = _tracer
    if tracer is None:
        return None
    return tracer.get_prompt(name, version)
