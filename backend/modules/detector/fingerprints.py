"""维护各 LLM 模型的 TPS 指纹库，用于模型掺水检测中判断异常速度对应的真实模型。"""

# MODEL_FINGERPRINTS: 键为模型名称，值为 tps 范围
# 数据来源：各模型在中等负载下的实测吞吐量
MODEL_FINGERPRINTS: dict[str, dict[str, tuple[float, float]]] = {
    "claude-sonnet-4-20250514": {
        "tokens_per_second": (30.0, 80.0),
    },
    "claude-3-5-sonnet-20241022": {
        "tokens_per_second": (28.0, 70.0),
    },
    "claude-haiku-3-5-20241022": {
        "tokens_per_second": (50.0, 120.0),
    },
    "claude-opus-4-20250514": {
        "tokens_per_second": (16.0, 40.0),
    },
    "deepseek-v4-pro": {
        "tokens_per_second": (15.0, 40.0),
    },
    "deepseek-v4-flash": {
        "tokens_per_second": (30.0, 70.0),
    },
    "deepseek-chat": {
        "tokens_per_second": (30.0, 80.0),
    },
    "deepseek-reasoner": {
        "tokens_per_second": (10.0, 30.0),
    },
    "gpt-4o": {
        "tokens_per_second": (25.0, 65.0),
    },
    "gpt-4o-mini": {
        "tokens_per_second": (45.0, 110.0),
    },
    "gpt-3.5-turbo": {
        "tokens_per_second": (50.0, 130.0),
    },
}


def get_fingerprint(model_name: str) -> dict[str, tuple[float, float]] | None:
    """按模型名称查找指纹，支持前缀匹配（如 'gpt-4o' 匹配 'gpt-4o-2024-08-06'）。"""
    if model_name in MODEL_FINGERPRINTS:
        return MODEL_FINGERPRINTS[model_name]
    # 前缀匹配：API 返回的完整模型名可能带日期后缀，需要回退到基础名
    for known_name, fp in MODEL_FINGERPRINTS.items():
        if model_name.startswith(known_name):
            return fp
    return None
