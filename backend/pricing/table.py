"""
模块: 后端 - 定价表
功能: 各 LLM 模型的 Token 单价表，用于计算每次调用的费用
"""

# 各模型每 1K Token 的价格（单位：美元）
# input: 输入 Token 单价 / output: 输出 Token 单价
# cache_read: 缓存命中读取单价 / cache_write: 缓存写入单价
PRICING: dict[str, dict[str, float]] = {
    "deepseek-v4-pro": {
        "input": 0.00014,
        "output": 0.00028,
        "cache_read": 0.000014,
        "cache_write": 0.00014,
    },
    "deepseek-chat": {
        "input": 0.00014,
        "output": 0.00028,
        "cache_read": 0.000014,
        "cache_write": 0.00014,
    },
    "deepseek-reasoner": {
        "input": 0.00055,
        "output": 0.00219,
        "cache_read": 0.000055,
        "cache_write": 0.00055,
    },
}


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read: int = 0,
    cache_create: int = 0,
) -> float:
    """
    计算单次 API 调用的总费用
    :param model:         模型名称
    :param input_tokens:  输入 Token 数
    :param output_tokens: 输出 Token 数
    :param cache_read:    缓存命中的 Token 数（按折扣价计费）
    :param cache_create:  缓存写入的 Token 数
    :return:              总费用（美元），四舍五入到 8 位小数
    """
    # 如果模型未在定价表中，默认按 deepseek-chat 计费
    p = PRICING.get(model, PRICING["deepseek-chat"])
    cost = (
        (input_tokens / 1000) * p["input"]
        + (output_tokens / 1000) * p["output"]
        + (cache_read / 1000) * p["cache_read"]
        + (cache_create / 1000) * p["cache_write"]
    )
    return round(cost, 8)  # 保留 8 位小数精度，匹配微量计费（单次调用可能 <$0.0001）
