import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.server import ctx


async def main():
    item_id = None
    keep = "--keep" in sys.argv
    prepared = False
    try:
        await ctx.ensure_started()
        assert await ctx.auth.is_logged_in()
        addresses = await ctx.order.get_saved_addresses()
        assert isinstance(addresses, list) and addresses
        await ctx.order.select_address(0)

        await ctx.order.search_product("milk")
        results = await ctx.order.get_search_results()
        item_id = results[-1]["id"]
        await ctx.order.add_to_cart(item_id, 2)
        print(await ctx.order.get_cart_items())
        await ctx.order.place_order()

        iframe = await ctx.auth.page.wait_for_selector("#payment_widget", timeout=30000)
        frame = await iframe.content_frame()
        await frame.wait_for_load_state("networkidle")
        titles = await frame.locator("[title]").evaluate_all(
            "elements => [...new Set(elements.map(element => element.title).filter(Boolean))]"
        )
        text = (await frame.locator("body").inner_text()).lower()
        print("payment_titles=", titles)
        print(
            "payment_methods=",
            {name: name in text for name in ("card", "credit", "debit", "upi", "cash")},
        )
        prepared = "add credit or debit cards" in text
    finally:
        if item_id and ctx.order and not (keep and prepared):
            await ctx.order.search_product("milk")
            await ctx.order.remove_from_cart(item_id, 2)
        await ctx.auth.close()


if __name__ == "__main__":
    asyncio.run(main())
