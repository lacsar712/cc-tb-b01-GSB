from decimal import ROUND_HALF_UP, Decimal


def weigh(aroma: float, taste: float, liquor: float) -> tuple[str, str, float]:
    score = round(aroma * 0.3 + taste * 0.5 + liquor * 0.2, 2)
    if score >= 7:
        return "通过", "加权分达到放行线", score
    return "不通过", "加权分低于放行线", score


def joint_mean(first: float, second: float) -> float:
    """两位审评员评分的均值，四舍五入保留一位小数。"""
    total = Decimal(str(first)) + Decimal(str(second))
    return float((total / 2).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
