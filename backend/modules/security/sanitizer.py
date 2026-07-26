"""敏感数据脱敏：对手机号、身份证、邮箱、信用卡、API 密钥等进行掩码处理。"""

import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Detection patterns — compiled regex for performance
# ---------------------------------------------------------------------------

PHONE_CN = re.compile(r"1[3-9]\d{9}")                          # 中国手机号
PHONE_INTL = re.compile(r"\+?\d{1,3}[-\s]?\d{3}[-\s]?\d{3}[-\s]?\d{4}")  # 国际号码
EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
CREDIT_CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
ID_CARD_CN = re.compile(r"[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]")
API_KEY = re.compile(
    r"(?:sk-|api[_-]?key[=:]\s*|bearer\s+|token[=:]\s*)([a-zA-Z0-9+/=_\-]{20,})",
    re.IGNORECASE,
)
IP_ADDRESS = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def mask_phone_numbers(text: str) -> tuple[str, int]:
    """Mask phone numbers: 138****5678"""
    count = 0

    def _mask(m):
        nonlocal count
        count += 1
        num = m.group(0)
        if len(num) >= 7:
            return num[:3] + "****" + num[-4:]
        return "[MASKED_PHONE]"

    text = PHONE_CN.sub(_mask, text)
    text = PHONE_INTL.sub(_mask, text)
    return text, count


def mask_emails(text: str) -> tuple[str, int]:
    """Mask email addresses: u***@domain.com"""
    count = 0

    def _mask(m):
        nonlocal count
        count += 1
        addr = m.group(0)
        parts = addr.split("@")
        if len(parts) == 2:
            local = parts[0]
            masked_local = local[0] + "***" if len(local) > 1 else "***"
            return f"{masked_local}@{parts[1]}"
        return "[MASKED_EMAIL]"

    text = EMAIL.sub(_mask, text)
    return text, count


def mask_id_cards(text: str) -> tuple[str, int]:
    """Mask Chinese ID cards: 110101****1234"""
    count = 0

    def _mask(m):
        nonlocal count
        count += 1
        num = m.group(0)
        return num[:6] + "********" + num[-4:]

    text = ID_CARD_CN.sub(_mask, text)
    return text, count


def mask_credit_cards(text: str) -> tuple[str, int]:
    """Mask credit card numbers, keeping last 4 digits.

    使用 Luhn 算法校验以降低假阳性，避免将普通数字串误判为信用卡号。
    """
    count = 0

    def _mask(m):
        nonlocal count
        num_str = m.group(0)
        digits = re.sub(r"[^\d]", "", num_str)
        if 13 <= len(digits) <= 19 and _luhn_check(digits):
            count += 1
            return "[MASKED_CARD:" + digits[-4:] + "]"
        return num_str

    text = re.sub(CREDIT_CARD, _mask, text)
    return text, count


def mask_api_keys(text: str) -> tuple[str, int]:
    """Mask API keys and tokens."""
    count = 0

    def _mask(m):
        nonlocal count
        count += 1
        return "[MASKED_API_KEY]"

    text = API_KEY.sub(_mask, text)
    return text, count


def _luhn_check(card_num: str) -> bool:
    """Basic Luhn algorithm check for credit card number validity."""
    try:
        digits = [int(d) for d in card_num]
        for i in range(len(digits) - 2, -1, -2):
            digits[i] *= 2
            if digits[i] > 9:
                digits[i] -= 9
        return sum(digits) % 10 == 0
    except (ValueError, IndexError):
        return False


def sanitize(
    text: str,
    *,
    mask_phone: bool = True,
    mask_email: bool = True,
    mask_id: bool = True,
    mask_credit_card: bool = True,
    mask_api_key: bool = True,
    mask_ip: bool = False,
) -> tuple[str, dict]:
    """Sanitize text by masking sensitive data. Returns (sanitized_text, stats).

    各 mask_* 参数控制需要脱敏的数据类型。
    mask_ip 默认为 False，因为 IP 地址模式假阳性较高（如版本号、时间戳等）。
    """
    stats: dict = {}

    if mask_phone:
        text, stats["phones_masked"] = mask_phone_numbers(text)
    if mask_email:
        text, stats["emails_masked"] = mask_emails(text)
    if mask_id:
        text, stats["id_cards_masked"] = mask_id_cards(text)
    if mask_credit_card:
        text, stats["credit_cards_masked"] = mask_credit_cards(text)
    if mask_api_key:
        text, stats["api_keys_masked"] = mask_api_keys(text)
    if mask_ip:
        stats["ips_masked"] = len(IP_ADDRESS.findall(text))
        text = IP_ADDRESS.sub("[MASKED_IP]", text)

    total = sum(stats.values())
    if total > 0:
        logger.info("Sanitized %d sensitive data items in text", total)

    return text, stats


def has_sensitive_data(text: str) -> bool:
    """Quick check: does this text contain any sensitive data patterns?"""
    return bool(
        PHONE_CN.search(text)
        or PHONE_INTL.search(text)
        or EMAIL.search(text)
        or ID_CARD_CN.search(text)
        or API_KEY.search(text)
    )
