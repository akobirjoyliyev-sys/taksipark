"""Vazifalarni my.isft.uz ga topshirish."""

from browser import ISFTBrowser
from playwright.sync_api import Page
import time


def submit_test(browser: ISFTBrowser, task_url: str, solved_questions: list[dict]) -> bool:
    """Test javoblarini belgilab topshiradi."""
    browser.goto(task_url)
    page = browser.page

    for q in solved_questions:
        idx = q.get("answer_index", 0)
        options = page.query_selector_all(
            f".question:nth-child({q['index']+1}) input[type='radio'], "
            f".question:nth-child({q['index']+1}) input[type='checkbox']"
        )
        if options and idx < len(options):
            options[idx].click()
            time.sleep(0.3)

    submit_btn = page.query_selector(
        "button[type='submit'], input[type='submit'], .submit-btn, button:has-text('Topshirish')"
    )
    if submit_btn:
        submit_btn.click()
        page.wait_for_load_state("networkidle")
        return True
    return False


def submit_text(browser: ISFTBrowser, task_url: str, answer_text: str) -> bool:
    """Matn javobini yozib topshiradi."""
    browser.goto(task_url)
    page = browser.page

    textarea = page.query_selector("textarea, [contenteditable='true'], .text-editor")
    if not textarea:
        return False

    textarea.fill(answer_text)
    time.sleep(0.5)

    submit_btn = page.query_selector(
        "button[type='submit'], input[type='submit'], .submit-btn, "
        "button:has-text('Topshirish'), button:has-text('Saqlash')"
    )
    if submit_btn:
        submit_btn.click()
        page.wait_for_load_state("networkidle")
        return True
    return False


def submit_file(browser: ISFTBrowser, task_url: str, file_path: str) -> bool:
    """Fayl yuklash orqali vazifani topshiradi."""
    browser.goto(task_url)
    page = browser.page

    file_input = page.query_selector("input[type='file']")
    if not file_input:
        return False

    file_input.set_input_files(file_path)
    time.sleep(1)

    submit_btn = page.query_selector(
        "button[type='submit'], input[type='submit'], .submit-btn, "
        "button:has-text('Yuklash'), button:has-text('Topshirish')"
    )
    if submit_btn:
        submit_btn.click()
        page.wait_for_load_state("networkidle")
        return True
    return False
