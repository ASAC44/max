import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.server import ctx


async def main():
    try:
        await ctx.ensure_started()
        addresses = await ctx.order.get_saved_addresses()
        assert isinstance(addresses, list) and addresses, addresses
        await ctx.order.select_address(0)
        await ctx.order.search_product("biscuit")
        results = await ctx.order.get_search_results()
        item = next(result for result in results if "Dark Fantasy Bourbon" in result["name"])
        await ctx.order.add_to_cart(item["id"])
        await ctx.order.search_product("chips")
        results = await ctx.order.get_search_results()
        item = next(result for result in results if "Sizzling Hot" in result["name"])
        await ctx.order.add_to_cart(item["id"])
        snapshot = await ctx.order.get_cart_snapshot()
        assert "error" not in snapshot, snapshot
        assert snapshot["merchant"] == "Blinkit"
        assert snapshot["currency"] == "INR"
        assert len(snapshot["items"]) == 2
        print(json.dumps({
            "address_label": snapshot["address_label"],
            "item_count": len(snapshot["items"]),
            "fees": snapshot["fees"],
            "total": snapshot["total"],
        }, ensure_ascii=False))
        link = await ctx.order.share_cart()
        assert link.startswith("https://link.blinkit.com/"), link
        print(link)
    finally:
        await ctx.auth.close()


if __name__ == "__main__":
    asyncio.run(main())
