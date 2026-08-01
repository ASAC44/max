import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.order.services.cart import CartService, is_discount, parse_rupees
from src.order.services.checkout import CheckoutService
from src.order.services.location import LocationService


class Items:
    async def count(self):
        return 2

    def nth(self, index):
        raise AssertionError(f"invalid address index {index} was selected")


class Page:
    def locator(self, selector):
        return Items()


async def main():
    assert parse_rupees("₹15 ₹30") == "15.00"
    assert parse_rupees("Saved ₹15 ₹30 ₹15", last=True) == "15.00"
    assert parse_rupees("FREE") == "0.00"
    assert is_discount("Coupon discount")
    assert not is_discount("Delivery charge")
    assert "disabled" in (await CheckoutService(None).click_pay_now()).lower()
    cart = CartService(None)
    for operation in (cart.add_to_cart, cart.remove_from_cart):
        try:
            await operation("product", 0)
        except ValueError as error:
            assert str(error) == "quantity must be at least 1"
        else:
            raise AssertionError("invalid quantity was accepted")

    await LocationService(Page()).select_address(-1)
    print("input validation OK")


if __name__ == "__main__":
    asyncio.run(main())
