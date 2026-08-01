import re
from datetime import UTC, datetime
from decimal import Decimal

from .base import BaseService


def parse_rupees(text: str, *, last: bool = False) -> str:
    amounts = re.findall(r"₹\s*([0-9]+(?:\.[0-9]{1,2})?)", text.replace(",", ""))
    if not amounts:
        if "free" in text.lower():
            return "0.00"
        raise ValueError(f"price not found in {text!r}")
    value = Decimal(amounts[-1 if last else 0]).quantize(Decimal("0.01"))
    return f"{value:.2f}"


def is_discount(label: str) -> bool:
    return any(word in label.lower() for word in ("discount", "saving", "coupon"))


class CartService(BaseService):
    async def _dismiss_overlays(self):
        """Dismiss any popups, modals, or overlays that may block interaction."""
        try:
            for selector in [
                "button[aria-label='close']",
                "div[class*='Modal'] button",
                "div[class*='Overlay'] button",
                "button:has-text('✕')",
                "button:has-text('×')",
            ]:
                if await self.page.is_visible(selector):
                    await self.page.click(selector, timeout=2000)
                    await self.page.wait_for_timeout(300)
        except Exception:
            pass

    async def _safe_click(self, locator, description="element", timeout=10000):
        """Click an element with fallback strategies: scroll into view, force click, JS click."""
        try:
            # First, scroll the element into view
            await locator.scroll_into_view_if_needed(timeout=5000)
            await self.page.wait_for_timeout(300)
        except Exception:
            pass

        # Attempt 1: Normal click
        try:
            await locator.click(timeout=timeout)
            return True
        except Exception as e:
            print(f"Normal click failed on {description}: {e}")

        # Attempt 2: Force click (bypasses actionability checks)
        try:
            await locator.click(force=True, timeout=5000)
            print(f"Force click succeeded on {description}.")
            return True
        except Exception as e:
            print(f"Force click failed on {description}: {e}")

        # Attempt 3: JavaScript click (last resort)
        try:
            await locator.evaluate("el => el.click()")
            print(f"JS click succeeded on {description}.")
            return True
        except Exception as e:
            print(f"JS click failed on {description}: {e}")

        return False

    async def add_to_cart(self, product_id: str, quantity: int = 1):
        """Adds a product to the cart by its unique ID. Supports multiple quantities."""
        if quantity < 1:
            raise ValueError("quantity must be at least 1")
        print(f"Adding product with ID {product_id} to cart (Quantity: {quantity})...")
        try:
            # Dismiss any overlays that might block buttons
            await self._dismiss_overlays()

            # Target the specific card by ID
            card = self.page.locator(f"div[id='{product_id}']")

            if await card.count() == 0:
                print(f"Product ID {product_id} not found on current page.")

                # Check if we know this product from a previous search
                if self.manager and product_id in self.manager.known_products:
                    print("Product found in history.")
                    product_info = self.manager.known_products[product_id]
                    source_query = product_info.get("source_query")

                    if source_query:
                        print(
                            f"Navigating back to search results for '{source_query}'..."
                        )
                        # Delegate search back to manager/search service
                        if hasattr(self.manager, "search_product"):
                            await self.manager.search_product(source_query)

                        # Re-locate the card after search
                        card = self.page.locator(f"div[id='{product_id}']")
                        if await card.count() == 0:
                            print(
                                f"CRITICAL: Product {product_id} still not found after re-search."
                            )
                            return
                    else:
                        print("No source query found for this product.")
                        return
                else:
                    print("Product ID unknown and not on current page.")
                    return

            # Dismiss overlays again after potential re-search
            await self._dismiss_overlays()

            # Find the ADD button specifically inside the card
            add_btn = card.locator("div").filter(has_text="ADD").last

            items_to_add = quantity

            # If ADD button is visible, click it once to start
            if await add_btn.is_visible():
                clicked = await self._safe_click(
                    add_btn, f"ADD button for {product_id}"
                )
                if clicked:
                    print(f"Clicked ADD button for {product_id} (1/{quantity}).")
                    items_to_add -= 1
                    # Wait for the counter to appear
                    await self.page.wait_for_timeout(500)
                else:
                    print(f"Failed to click ADD button for {product_id}.")
                    return

            # Use increment button for remaining quantity
            if items_to_add > 0:
                # Wait for the counter to initialize
                await self.page.wait_for_timeout(1000)

                # Robust strategy to find the + button
                plus_btn = card.locator(".icon-plus").first
                if await plus_btn.count() > 0:
                    plus_btn = plus_btn.locator("..")
                else:
                    plus_btn = card.locator("text='+'").first

                if await plus_btn.is_visible():
                    for i in range(items_to_add):
                        await self._safe_click(plus_btn, f"+ button for {product_id}")
                        print(
                            f"Incrementing quantity for {product_id} ({quantity - items_to_add + i + 1}/{quantity})."
                        )
                        # Check for limit reached
                        try:
                            limit_msg = self.page.get_by_text(
                                "Sorry, you can't add more of this item"
                            )
                            if await limit_msg.is_visible(timeout=1000):
                                print(f"Quantity limit reached for {product_id}.")
                                break
                        except Exception:
                            pass

                        await self.page.wait_for_timeout(500)
                else:
                    print(
                        f"Could not find '+' button to add remaining quantity for {product_id}."
                    )

            await self.page.wait_for_timeout(1000)

            # Check for "Store Unavailable" modal
            if await self.page.is_visible(
                "div:has-text('Sorry, can\\'t take your order')"
            ):
                print("WARNING: Store is unavailable (Modal detected).")
                return

        except Exception as e:
            print(f"Error adding to cart: {e}")

    async def remove_from_cart(self, product_id: str, quantity: int = 1):
        """Removes a specific quantity of a product from the cart."""
        if quantity < 1:
            raise ValueError("quantity must be at least 1")
        print(f"Removing {quantity} of product ID {product_id} from cart...")
        try:
            drawer = self.page.locator(
                "div[class*='CartDrawer'], div[class*='CartSidebar'], div.cart-modal-rn, div[class*='CartWrapper__CartContainer']"
            ).first
            if await drawer.is_visible():
                await self.page.keyboard.press("Escape")
                await self.page.wait_for_timeout(300)

            # Dismiss any overlays
            await self._dismiss_overlays()

            # Target the specific card by ID
            card = self.page.locator(f"div[id='{product_id}']")

            if await card.count() == 0:
                # Attempt recovery via search if known
                if self.manager and product_id in self.manager.known_products:
                    product_info = self.manager.known_products[product_id]
                    source_query = product_info.get("source_query")
                    if source_query:
                        if hasattr(self.manager, "search_product"):
                            await self.manager.search_product(source_query)
                        card = self.page.locator(f"div[id='{product_id}']")
                        if await card.count() == 0:
                            print(
                                f"Product {product_id} not found after recovery search."
                            )
                            return
                else:
                    print(f"Product ID {product_id} not found and unknown.")
                    return

            # Check for decrement button
            minus_btn = card.locator(".icon-minus").first
            if await minus_btn.count() > 0:
                minus_btn = minus_btn.locator("..")
            else:
                minus_btn = card.locator("text='-'").first

            if await minus_btn.is_visible():
                for i in range(quantity):
                    await self._safe_click(minus_btn, f"- button for {product_id}")
                    print(
                        f"Decrementing quantity for {product_id} ({i + 1}/{quantity})."
                    )
                    add_btn = card.locator("div").filter(has_text="ADD").last
                    try:
                        await add_btn.wait_for(state="visible", timeout=5000)
                    except Exception:
                        pass

                    if await add_btn.is_visible():
                        print(f"Item {product_id} completely removed from cart.")
                        break
            else:
                print(f"Item {product_id} is not in cart (no '-' button found).")

        except Exception as e:
            print(f"Error removing from cart: {e}")

    async def get_cart_items(self):
        """Checks items in the cart and returns the text content."""
        try:
            # Dismiss any overlays before trying to open the cart
            await self._dismiss_overlays()

            drawer = self.page.locator(
                "div[class*='CartDrawer'], div[class*='CartSidebar'], div.cart-modal-rn, div[class*='CartWrapper__CartContainer']"
            ).first

            # If drawer isn't visible, try to click the cart button to open it
            if not await drawer.is_visible():
                cart_btn = (
                    self.page.locator(
                        "div[class*='CartButton__Button'], div[class*='CartButton__Container'], a[href='/cart'], div[class*='cart']"
                    )
                    .filter(has_text="Cart")
                    .last
                )

                if await cart_btn.count() == 0:
                    cart_btn = self.page.locator("div[class*='CartButton']").first

                if await cart_btn.count() > 0:
                    clicked = await self._safe_click(cart_btn, "cart button")
                    if not clicked:
                        return (
                            "Failed to click cart button (may be blocked by overlay)."
                        )
                    try:
                        await drawer.wait_for(state="visible", timeout=10000)
                    except Exception:
                        pass
                else:
                    # Look for anything with Cart or View Cart
                    alt_btn = (
                        self.page.locator("button, div").filter(has_text="Cart").last
                    )
                    if await alt_btn.count() > 0:
                        await self._safe_click(alt_btn, "alt cart button")
                        await self.page.wait_for_timeout(2000)
                    else:
                        return "Cart button not found."

            if not await drawer.is_visible():
                return "Cart drawer did not open."

            try:
                await drawer.locator(
                    "div[class*='CartProduct__Container']"
                ).first.wait_for(state="visible", timeout=10000)
            except Exception:
                pass

            # Verify availability
            if (
                await self.page.is_visible("text=Sorry, can't take your order")
                or await self.page.is_visible("text=Currently unavailable")
                or await self.page.is_visible("text=High Demand")
            ):
                return "CRITICAL: Store is unavailable. 'Sorry, can't take your order'. Please try again later."

            if await self._is_store_closed():
                return "CRITICAL: Store is closed."

            # Scrape content more cleanly using evaluate to extract meaningful parts
            content = await drawer.evaluate("""(drawer) => {
                let text = drawer.innerText;
                let results = ["--- CART DETAILS ---"];
                
                // Try to extract items
                let items = drawer.querySelectorAll("div[class*='CartProduct__Container']");
                items.forEach(item => {
                    let title = item.querySelector("div[class*='ProductTitle']")?.innerText || "";
                    let variant = item.querySelector("div[class*='ProductVariant']")?.innerText || "";
                    let price = item.querySelector("div[class*='Price-']")?.innerText || "";
                    let qtyElement = item.querySelector("div[class*='AddToCart__UpdatedButtonContainer']");
                    let qty = [...(qtyElement?.childNodes || [])]
                        .find(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim())
                        ?.textContent.trim() || "1";
                    if (title) {
                        results.push(`• ${title} | ${variant} | ${price} | Qty: ${qty}`);
                    }
                });
                
                if (items.length === 0) {
                    results.push("Raw text: " + text.substring(0, 300) + "...");
                }
                
                // Try to extract Bill Details
                let billItems = drawer.querySelectorAll("div[class*='BillCard__BillItemContainer']");
                if (billItems.length > 0) results.push("\\n--- BILL DETAILS ---");
                billItems.forEach(item => {
                    let textParts = item.innerText.split('\\n').map(t => t.trim()).filter(t => t);
                    if (textParts.length >= 2) {
                        results.push(`${textParts[0]}: ${textParts[textParts.length-1]}`);
                    }
                });
                
                // Get Delivery Address
                let addressHeading = drawer.querySelector("div[class*='ListStrip__Heading']")?.innerText || "";
                if (addressHeading) {
                    results.push("\\n--- DELIVERY TO ---");
                    results.push(addressHeading);
                }
                
                // Get Total
                let totalText = drawer.querySelector("div[class*='CheckoutStrip__TotalText']")?.innerText || "";
                let finalPrice = drawer.querySelector("div[class*='CheckoutStrip__NetPriceText']")?.innerText || "";
                if (finalPrice) {
                    results.push(`\\n--- TOTAL TO PAY: ${finalPrice} ---`);
                }
                
                return results.join('\\n');
            }""")

            if "Currently unavailable" in content or "can't take your order" in content:
                return (
                    "CRITICAL: Store is unavailable. Please try again later.\\n"
                    + content
                )

            return content

        except Exception as e:
            return f"Error getting cart items: {e}"

    async def share_cart(self):
        """Generate Blinkit's native share-cart link for the current cart."""
        try:
            cart = await self.get_cart_items()
            if "--- CART DETAILS ---" not in cart:
                return f"Could not open a shareable cart: {cart}"

            share = self.page.locator("div[class*='CartWrapper__ShareButton']")
            if await share.count() != 1:
                return "Blinkit Share Cart button was not found."

            await share.click()
            await self.page.wait_for_timeout(500)
            clipboard = await self.page.evaluate("navigator.clipboard.readText()")
            match = re.search(r"https://link\.blinkit\.com/\S+", clipboard)
            return match.group(0) if match else "Blinkit did not copy a share-cart link."
        except Exception as error:
            return f"Error sharing cart: {error}"

    async def get_cart_snapshot(self):
        """Return a structured, redacted snapshot for purchase parity checks."""
        cart = await self.get_cart_items()
        if "--- CART DETAILS ---" not in cart:
            return {"error": cart}

        drawer = self.page.locator(
            "div[class*='CartDrawer'], div[class*='CartSidebar'], div.cart-modal-rn, div[class*='CartWrapper__CartContainer']"
        ).first
        raw = await drawer.evaluate("""drawer => ({
            items: [...drawer.querySelectorAll("div[class*='CartProduct__Container']")].map(item => ({
                product_id: item.getAttribute('data-pf') || item.id || null,
                name: item.querySelector("div[class*='ProductTitle']")?.innerText?.trim() || '',
                variant: item.querySelector("div[class*='ProductVariant']")?.innerText?.trim() || '',
                price: item.querySelector("div[class*='Price-']")?.innerText?.trim() || '',
                quantity: [...(item.querySelector("div[class*='AddToCart__UpdatedButtonContainer']")?.childNodes || [])]
                    .find(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim())
                    ?.textContent.trim() || '1',
            })),
            bill: [...drawer.querySelectorAll("div[class*='BillCard__BillItemContainer']")]
                .map(item => item.innerText.split('\\n').map(value => value.trim()).filter(Boolean)),
            address_label: drawer.querySelector("div[class*='ListStrip__Heading']")?.innerText?.trim() || '',
            total: drawer.querySelector("div[class*='CheckoutStrip__NetPriceText']")?.innerText?.trim() || '',
        })""")

        try:
            items = [
                {
                    "product_id": item["product_id"],
                    "name": item["name"],
                    "variant": item["variant"],
                    "unit_price": parse_rupees(item["price"]),
                    "quantity": int(item["quantity"]),
                }
                for item in raw["items"]
            ]
            fees = []
            discounts = []
            for parts in raw["bill"]:
                label = parts[0]
                if label.lower() in {"items total", "grand total"}:
                    continue
                try:
                    amount = parse_rupees(" ".join(parts[1:]), last=True)
                except ValueError:
                    continue
                target = discounts if is_discount(label) else fees
                target.append({"name": label, "amount": amount})
            return {
                "merchant": "Blinkit",
                "merchant_url": "https://blinkit.com/",
                "address_label": raw["address_label"],
                "currency": "INR",
                "items": items,
                "fees": fees,
                "discounts": discounts,
                "total": parse_rupees(raw["total"], last=True),
                "observed_at": datetime.now(UTC).isoformat(),
            }
        except (KeyError, TypeError, ValueError) as error:
            return {"error": f"Could not parse Blinkit cart snapshot: {error}"}
