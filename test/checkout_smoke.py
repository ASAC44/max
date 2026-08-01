import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.server import ctx


async def main():
    address_index = int(sys.argv[1])
    item_id = None
    try:
        await ctx.ensure_started()
        assert await ctx.auth.is_logged_in(), "session is not logged in"

        addresses = await ctx.order.get_saved_addresses()
        assert isinstance(addresses, list) and address_index < len(addresses)
        await ctx.order.select_address(address_index)

        await ctx.order.search_product("milk")
        results = await ctx.order.get_search_results()
        assert results, "search returned no products"
        item_id = results[-1]["id"]
        await ctx.order.add_to_cart(item_id)

        cart = await ctx.order.get_cart_items()
        print(cart)
        if "CRITICAL" in cart:
            return

        await ctx.order.place_order()
        await ctx.order.place_order()
        payment = await ctx.order.select_payment_method()
        print(payment.get("status") if isinstance(payment, dict) else payment)
    finally:
        if item_id and ctx.order:
            await ctx.order.search_product("milk")
            await ctx.order.remove_from_cart(item_id)
        await ctx.auth.close()


if __name__ == "__main__":
    asyncio.run(main())
