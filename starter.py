"""Учебный фрагмент для тестового задания ТОЛЬКООПТ.

Python 3.10+, только стандартная библиотека. Запуск примера: python starter.py
В функции recommend_price исправлены ошибки согласно правилам ТЗ.
"""

import asyncio
from decimal import Decimal, ROUND_FLOOR
import unittest


async def recommend_price(
    fetch_offers,
    current_price: Decimal,
    min_price: Decimal,
    timeout_s: float = 2.0,
) -> dict:
    """Рассчитывает рекомендованную цену на основе предложений конкурентов.

    ПРАВИЛА:
    1. Ограничение ожидания fetch_offers значением timeout_s. При ошибке,
       тайм-ауте или status != success -> текущая цена и HOLD.
    2. Учитывать предложения с известной доставкой <= 6 дней.
       Исключать магазин MYSHOP (case-insensitive).
    3. Если подходящих предложений нет -> текущая цена и HOLD.
    4. Мин. цена подходящего конкурента - 1.5%, округление вниз до копейки.
       Рекомендация = max(скинутая_цена, min_price).
    5. Если отличие от current_price > 30% -> REVIEW, иначе APPLY (ровно 30% допускается).
    """
    # 1. Запрос к источнику с таймаутом и обработкой ошибок
    try:
        result = await asyncio.wait_for(fetch_offers(), timeout=timeout_s)
    except (asyncio.TimeoutError, TimeoutError):
        return {
            "price": current_price,
            "decision": "HOLD",
            "reason": "Превышено время ожидания ответа от источника (тайм-аут)",
        }
    except Exception as exc:
        return {
            "price": current_price,
            "decision": "HOLD",
            "reason": f"Ошибка при получении предложений: {exc}",
        }

    if not isinstance(result, dict) or result.get("status") != "success":
        status = result.get("status") if isinstance(result, dict) else "invalid_format"
        return {
            "price": current_price,
            "decision": "HOLD",
            "reason": f"Источник вернул статус '{status}' вместо 'success'",
        }

    # 2. Фильтрация предложений (доставка <= 6 дней, без MYSHOP)
    offers = result.get("offers", [])
    valid_offers = [
        offer
        for offer in offers
        if offer.get("delivery_days") is not None
        and offer["delivery_days"] <= 6
        and offer.get("seller", "").strip().lower() != "myshop"
    ]

    # 3. Если нет подходящих предложений -> HOLD
    if not valid_offers:
        return {
            "price": current_price,
            "decision": "HOLD",
            "reason": "Нет подходящих предложений конкурентов с доставкой до 6 дней",
        }

    # 4. Расчет минимальной цены со скидкой 1.5% и округлением вниз до копейки
    min_competitor_price = min(offer["price"] for offer in valid_offers)
    discounted_price = (min_competitor_price * Decimal("0.985")).quantize(
        Decimal("0.01"), rounding=ROUND_FLOOR
    )
    rec_price = max(discounted_price, min_price)

    # 5. Проверка отклонения от текущей цены (порог 30%, ровно 30% допустимо)
    diff = abs(rec_price - current_price)
    max_allowed_diff = current_price * Decimal("0.30")

    if diff > max_allowed_diff:
        decision = "REVIEW"
        reason = f"Отклонение цены ({diff}) превышает 30% от текущей ({max_allowed_diff})"
    else:
        decision = "APPLY"
        reason = "Цена успешно рассчитана со скидкой 1.5% относительно конкурента"

    return {
        "price": rec_price,
        "decision": decision,
        "reason": reason,
    }


async def sample_fetch_offers():
    return {
        "status": "success",
        "offers": [
            {"seller": "myshop", "price": Decimal("4300.00"), "delivery_days": 2},
            {"seller": "PARTS", "price": Decimal("4800.00"), "delivery_days": 3},
            {"seller": "SLOW", "price": Decimal("4700.00"), "delivery_days": 8},
        ],
    }


# =====================================================================
# Автоматические тесты
# =====================================================================
class TestRecommendPrice(unittest.IsolatedAsyncioTestCase):
    async def test_standard_apply(self):
        """Базовый сценарий из ТЗ: игнорируем myshop и медленную доставку, применяем цену."""
        res = await recommend_price(
            sample_fetch_offers,
            current_price=Decimal("4900.00"),
            min_price=Decimal("4500.00"),
        )
        self.assertEqual(res["price"], Decimal("4728.00"))
        self.assertEqual(res["decision"], "APPLY")

    async def test_timeout_returns_hold(self):
        """Сбой: таймаут внешнего источника -> HOLD и текущая цена."""
        async def slow_fetch():
            await asyncio.sleep(0.1)
            return {"status": "success", "offers": []}

        res = await recommend_price(
            slow_fetch,
            current_price=Decimal("5000.00"),
            min_price=Decimal("4000.00"),
            timeout_s=0.01,
        )
        self.assertEqual(res["price"], Decimal("5000.00"))
        self.assertEqual(res["decision"], "HOLD")

    async def test_error_status_returns_hold(self):
        """Сбой источника (status != success) -> HOLD и текущая цена."""
        async def error_fetch():
            return {"status": "error", "offers": []}

        res = await recommend_price(
            error_fetch,
            current_price=Decimal("5000.00"),
            min_price=Decimal("4000.00"),
        )
        self.assertEqual(res["price"], Decimal("5000.00"))
        self.assertEqual(res["decision"], "HOLD")

    async def test_boundary_30_percent_difference(self):
        """Граничный случай: ровно 30% отклонения -> APPLY, а чуть более 30% -> REVIEW."""
        # 1000 - 30% = 700. Для скидки 1.5% цена конкурента: 700 / 0.985 ~= 710.66
        # Проверим прямое попадание в границу 30%:
        # current = 1000.00, если рекомендация = 700.00 -> diff = 300.00 (ровно 30%) -> APPLY
        # Если рекомендация = 699.99 -> diff = 300.01 (> 30%) -> REVIEW
        async def fetch_target_price(target_price):
            return {
                "status": "success",
                "offers": [{"seller": "OTHER", "price": target_price, "delivery_days": 1}],
            }

        # Конкурент с ценой 710.66: 710.66 * 0.985 = 700.0001 -> quantize ROUND_FLOOR = 700.00
        res_exact = await recommend_price(
            lambda: fetch_target_price(Decimal("710.66")),
            current_price=Decimal("1000.00"),
            min_price=Decimal("500.00"),
        )
        self.assertEqual(res_exact["price"], Decimal("700.00"))
        self.assertEqual(res_exact["decision"], "APPLY")

        # Конкурент с ценой 710.64: 710.64 * 0.985 = 699.9804 -> ROUND_FLOOR = 699.98 (отклонение > 30%)
        res_review = await recommend_price(
            lambda: fetch_target_price(Decimal("710.64")),
            current_price=Decimal("1000.00"),
            min_price=Decimal("500.00"),
        )
        self.assertEqual(res_review["price"], Decimal("699.98"))
        self.assertEqual(res_review["decision"], "REVIEW")

    async def test_min_price_floor(self):
        """Ограничение снизу: скинутая цена ниже min_price, возвращается min_price."""
        async def low_fetch():
            return {
                "status": "success",
                "offers": [{"seller": "CHEAP", "price": Decimal("3000.00"), "delivery_days": 1}],
            }

        res = await recommend_price(
            low_fetch,
            current_price=Decimal("4500.00"),
            min_price=Decimal("4000.00"),
        )
        self.assertEqual(res["price"], Decimal("4000.00"))
        # Отклонение: |4000 - 4500| = 500, 500 / 4500 = 11.1% <= 30% -> APPLY
        self.assertEqual(res["decision"], "APPLY")


if __name__ == "__main__":
    # Запуск одиночного примера
    sample_result = asyncio.run(
        recommend_price(
            sample_fetch_offers,
            current_price=Decimal("4900.00"),
            min_price=Decimal("4500.00"),
        )
    )
    print("Пример из ТЗ:")
    print(sample_result)
