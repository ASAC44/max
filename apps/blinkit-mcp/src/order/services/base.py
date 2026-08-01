from playwright.async_api import Page
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.order.blinkit_order import BlinkitOrder


class BaseService:
    def __init__(self, page: Page, manager: Optional["BlinkitOrder"] = None):
        self.page = page
        self.manager = manager

    async def _is_store_closed(self):
        """Checks if the store is closed or unavailable."""
        if await self.page.is_visible("text=Store is closed"):
            print("CRITICAL: Store is closed.")
            return True
        return False
