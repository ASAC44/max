from .base import BaseService


class LocationService(BaseService):
    async def set_location(self, location_name: str):
        """Sets the location manually."""
        print(f"Setting location to: {location_name}...")
        try:
            # Check if the modal is open, if not try to open it
            if not await self.page.is_visible(
                "input[name='select-locality']"
            ) and not await self.page.is_visible(
                "button:has-text('Detect my location')"
            ):
                # Click location bar
                if await self.page.is_visible("div[class*='LocationBar__Container']"):
                    await self.page.click("div[class*='LocationBar__Container']")

            if location_name.lower() == "detect":
                detect_btn = self.page.locator(
                    "button:has-text('Detect my location')"
                ).first
                if await detect_btn.is_visible():
                    await detect_btn.click()
                    await self.page.wait_for_timeout(2000)
                    print("Clicked 'Detect my location'.")
                    return
                else:
                    print("Could not find 'Detect my location' button.")
                    return

            # Wait for input
            location_input = await self.page.wait_for_selector(
                "input[name='select-locality'], input[placeholder*='search delivery location']",
                state="visible",
                timeout=30000,
            )

            await location_input.fill(location_name)
            await self.page.wait_for_timeout(1000)

            # Select first result
            first_result = self.page.locator(
                "div[class*='LocationSearchBox__LocationItemContainer']"
            ).first
            if await first_result.is_visible():
                await first_result.click()
                print("Selected first location result.")

                # Wait for location update
                await self.page.wait_for_timeout(2000)

                # Check if this new location is unavailable
                if await self.page.is_visible("text=Currently unavailable"):
                    print(
                        "WARNING: Store is marked as 'Currently unavailable' at this new location."
                    )
            else:
                print("No location results found.")

        except Exception as e:
            print(f"Error setting location: {e}")

    async def get_saved_addresses(self):
        """Scrapes saved addresses from the selection modal."""
        print("Checking for address selection modal...")
        try:
            if (
                not await self.page.is_visible("text='Select delivery address'")
                and not await self.page.is_visible("text='Change Location'")
                and not await self.page.is_visible("text='Your saved addresses'")
            ):
                print(
                    "Address selection modal not visible. Checking for top Location Bar..."
                )

                location_bar = self.page.locator(
                    "div[class*='LocationBar__Container']"
                ).first
                if await location_bar.is_visible():
                    print("Found top Location Bar. Clicking it to open address modal.")
                    await location_bar.click()
                    await self.page.wait_for_timeout(2000)
                else:
                    print(
                        "Location Bar not found. Attempting to open Cart to find address change option..."
                    )

                    drawer = self.page.locator(
                        "div[class*='CartDrawer'], div[class*='CartSidebar'], div.cart-modal-rn, div[class*='CartWrapper__CartContainer']"
                    ).first

                    # If drawer isn't visible, try to open it
                    if not await drawer.is_visible():
                        cart_btn = self.page.locator(
                            "div[class*='CartButton__Button'], div[class*='CartButton__Container']"
                        ).first
                        if await cart_btn.count() > 0:
                            await cart_btn.click()
                            await self.page.wait_for_timeout(2000)

                    # Check for "Change" button in cart
                    change_btn = (
                        self.page.locator("div[class*='ListStrip__ActionContainer']")
                        .filter(has_text="Change")
                        .last
                    )
                    if not await change_btn.is_visible():
                        # Fallback
                        change_btn = (
                            self.page.locator("div, button")
                            .filter(has_text="Change")
                            .last
                        )

                    if await change_btn.is_visible():
                        await change_btn.click()
                        await self.page.wait_for_timeout(2000)

            address_items = self.page.locator(
                "div[class*='AddressList__AddressItemWrapper'], div[class*='AddressListItem__AddressItemWrapper']"
            )
            try:
                await address_items.first.wait_for(state="visible", timeout=10000)
            except Exception:
                pass

            if await address_items.count() == 0:
                print(
                    "Address selection modal still not visible after trying to open it."
                )
                return []

            if await self._is_store_closed():
                return "CRITICAL: Store is closed."

            print("Address modal detected. Parsing addresses...")
            count = await address_items.count()

            addresses = []
            for i in range(count):
                item = address_items.nth(i)
                # Parse label
                label_el = item.locator(
                    "div[class*='AddressList__AddressLabel'], div[class*='AddressListItem__AddressLabel']"
                )
                if await label_el.count() > 0:
                    label = await label_el.first.inner_text()
                else:
                    label = "Unknown"

                # Parse details
                details_el = item.locator(
                    "div[class*='AddressList__AddressDetails'], div[class*='AddressListItem__AddressDetails']"
                ).last
                if await details_el.count() > 0:
                    details = await details_el.inner_text()
                else:
                    details = ""

                addresses.append({"index": i, "label": label, "details": details})
            return addresses

        except Exception as e:
            print(f"Error getting addresses: {e}")
            return []

    async def select_address(self, index: int):
        """Selects an address by index."""
        try:
            items = self.page.locator(
                "div[class*='AddressList__AddressItemWrapper'], div[class*='AddressListItem__AddressItemWrapper']"
            )
            if 0 <= index < await items.count():
                print(f"Selecting address at index {index}...")

                if await self._is_store_closed():
                    return "CRITICAL: Store is closed."

                await items.nth(index).click()
                # Wait for modal to close or location to update
                await self.page.wait_for_timeout(2000)
            else:
                print(f"Invalid address index: {index}")
        except Exception as e:
            print(f"Error selecting address: {e}")
