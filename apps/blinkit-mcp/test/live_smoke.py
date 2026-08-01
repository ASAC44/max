import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.server import add_to_cart, check_cart, check_login, ctx, remove_from_cart, search


async def main():
    item_id = None
    try:
        print("LOGIN:", await check_login())
        print("SEARCH:\n", await search("milk"))
        assert ctx.order.known_products, "search returned no usable product IDs"

        item_id = next(iter(ctx.order.known_products))
        print("ADD:\n", await add_to_cart(item_id))
        print("CART AFTER ADD:\n", await check_cart())
    finally:
        if item_id and ctx.order:
            print("REMOVE:\n", await remove_from_cart(item_id))
            print("CART AFTER REMOVE:\n", await check_cart())
        await ctx.auth.close()


if __name__ == "__main__":
    asyncio.run(main())
