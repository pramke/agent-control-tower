"""LangChain callback handler: auto-record LLM calls as trace spans."""
from .tracer import _tracer


class ACTCallbackHandler:
    """LangChain callback that creates trace spans for every LLM interaction."""
    def __init__(self):
        # Map LangChain run_id -> Span to correlate start/end/error callbacks
        self._spans: dict = {}

    def on_llm_start(self, serialized: dict, prompts: list[str], **kwargs):
        if _tracer is None:
            return
        run_id = str(kwargs.get("run_id", ""))
        span = _tracer.start_span("llm_call", model=serialized.get("name", "unknown"), prompt=prompts[0][:500])
        self._spans[run_id] = span

    def on_llm_end(self, response, **kwargs):
        if _tracer is None:
            return
        run_id = str(kwargs.get("run_id", ""))
        span = self._spans.pop(run_id, None)
        if span:
            try:
                # Truncate response text to avoid bloating trace payloads
                text = str(response.generations[0][0].text)[:1000]
                token_usage = response.llm_output.get("token_usage", {})
            except Exception:
                text = "n/a"
                token_usage = {}
            _tracer.end_span(span, {"response": text, "token_usage": token_usage})

    def on_llm_error(self, error, **kwargs):
        if _tracer is None:
            return
        run_id = str(kwargs.get("run_id", ""))
        span = self._spans.pop(run_id, None)
        if span:
            _tracer.end_span(span, {"error": str(error)})
