"""Playwright browser boshqaruvchi."""

from playwright.sync_api import sync_playwright, Page, Browser
import os


BASE_URL = "https://my.isft.uz"


class ISFTBrowser:
    def __init__(self, headless: bool = False):
        self.headless = headless
        self._playwright = None
        self._browser: Browser = None
        self.page: Page = None

    def __enter__(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            executable_path="/opt/pw-browsers/chromium",
        )
        self.page = self._browser.new_page()
        self.page.set_viewport_size({"width": 1280, "height": 800})
        return self

    def __exit__(self, *args):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def login(self, username: str, password: str) -> bool:
        self.page.goto(f"{BASE_URL}/login")
        self.page.wait_for_load_state("networkidle")

        self.page.fill('input[name="username"], input[type="text"]', username)
        self.page.fill('input[name="password"], input[type="password"]', password)
        self.page.click('button[type="submit"], input[type="submit"]')
        self.page.wait_for_load_state("networkidle")

        return "login" not in self.page.url

    def goto(self, path: str):
        self.page.goto(f"{BASE_URL}{path}")
        self.page.wait_for_load_state("networkidle")

    def screenshot(self, path: str):
        self.page.screenshot(path=path)
