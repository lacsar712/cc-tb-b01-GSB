from decimal import Decimal, ROUND_HALF_UP


def weigh(aroma: float, taste: float, liquor: float) -> tuple[str, str, float]:
    score = round(aroma * 0.3 + taste * 0.5 + liquor * 0.2, 2)
    if score >= 7:
        return "通过", "加权分达到放行线", score
    return "不通过", "加权分低于放行线", score


def joint_mean(a: float, b: float) -> float:
    """两名审评员同项打分的均值，四舍五入保留一位小数。"""
    avg = (Decimal(str(a)) + Decimal(str(b))) / Decimal("2")
    return float(avg.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
