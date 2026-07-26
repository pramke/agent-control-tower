"""模块: 后端 - LLM 工具 / 功能: ChatOpenAI 工厂函数，统一创建 LLM 实例"""

from langchain_core.language_models import BaseChatModel

from backend.config import settings


def create_chat_model(
    model_name: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    key = api_key or settings.agent_api_key or "missing-api-key"  # 占位值避免 None 导致 ChatOpenAI 初始化失败
    base = (base_url or settings.agent_base_url).rstrip("/")
    if base.endswith("/anthropic"):
        base = base[: -len("/anthropic")]  # ChatOpenAI 需要标准 OpenAI 格式地址，去除 Anthropic 兼容路径后缀
    return ChatOpenAI(model=model_name, api_key=key, base_url=base, temperature=0)
