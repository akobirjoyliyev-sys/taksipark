"""my.isft.uz dan vazifalarni o'qib olish."""

from browser import ISFTBrowser
from dataclasses import dataclass, field


@dataclass
class Subject:
    name: str
    url: str
    credit: str = ""


@dataclass
class Task:
    subject: str
    title: str
    description: str
    deadline: str = ""
    status: str = "topshirilmagan"
    url: str = ""
    task_type: str = "unknown"  # "test", "file_upload", "text"
    questions: list = field(default_factory=list)


def get_subjects(browser: ISFTBrowser) -> list[Subject]:
    """Barcha fanlar ro'yxatini oladi."""
    browser.goto("/subjects")
    page = browser.page

    subjects = []
    rows = page.query_selector_all("a[href*='/subjects/']")
    for row in rows:
        href = row.get_attribute("href") or ""
        name = row.inner_text().strip()
        if name and "/subjects/" in href:
            subjects.append(Subject(name=name, url=href))
    return subjects


def get_distance_learning_tasks(browser: ISFTBrowser) -> list[Task]:
    """Masofaviy ta'lim bo'limidan barcha vazifalarni oladi."""
    browser.goto("/distance-learning")
    page = browser.page

    tasks = []
    task_links = page.query_selector_all("a[href*='task'], a[href*='assignment'], a[href*='homework']")

    for link in task_links:
        href = link.get_attribute("href") or ""
        title = link.inner_text().strip()
        if title:
            tasks.append(Task(
                subject="",
                title=title,
                description="",
                url=href,
            ))

    # Agar topilmasa — umumiy sahifani skan qilamiz
    if not tasks:
        tasks = _scan_page_for_tasks(browser)

    return tasks


def get_task_detail(browser: ISFTBrowser, task_url: str) -> Task:
    """Bitta vazifaning tafsilotlarini o'qib oladi."""
    browser.goto(task_url)
    page = browser.page

    title = ""
    title_el = page.query_selector("h1, h2, .task-title, .assignment-title")
    if title_el:
        title = title_el.inner_text().strip()

    description = ""
    desc_el = page.query_selector(".task-description, .assignment-body, .content, main p")
    if desc_el:
        description = desc_el.inner_text().strip()

    # Test savollari bormi?
    questions = _extract_test_questions(page)
    task_type = "test" if questions else _detect_task_type(page)

    return Task(
        subject="",
        title=title,
        description=description,
        url=task_url,
        task_type=task_type,
        questions=questions,
    )


def _extract_test_questions(page) -> list[dict]:
    """Sahifadan test savollarini ajratib oladi."""
    questions = []

    # Turli LMS larning test strukturalari
    q_containers = page.query_selector_all(
        ".question, .quiz-question, [class*='question'], .test-item"
    )

    for i, container in enumerate(q_containers):
        text = container.inner_text().strip()
        options = []
        option_els = container.query_selector_all(
            "input[type='radio'], input[type='checkbox'], .option, .answer-choice"
        )
        for opt in option_els:
            label = opt.get_attribute("value") or opt.inner_text().strip()
            if label:
                options.append(label)

        questions.append({
            "index": i,
            "text": text,
            "options": options,
            "element_selector": f".question:nth-child({i+1})",
        })

    return questions


def _detect_task_type(page) -> str:
    """Vazifa turini aniqlaydi."""
    if page.query_selector("input[type='file']"):
        return "file_upload"
    if page.query_selector("textarea, .text-editor, [contenteditable]"):
        return "text"
    return "unknown"


def _scan_page_for_tasks(browser: ISFTBrowser) -> list[Task]:
    """Sahifani to'liq skanlab vazifalarni qidiradi."""
    page = browser.page
    content = page.inner_text("body")
    tasks = []

    # Har bir fanga kirish
    subject_links = page.query_selector_all("a[href*='/subjects/']")
    for link in subject_links[:10]:  # maksimal 10 ta fan
        href = link.get_attribute("href") or ""
        subject_name = link.inner_text().strip()

        if not href:
            continue

        browser.goto(href)
        task_els = page.query_selector_all(
            "a[href*='task'], a[href*='assignment'], a[href*='homework'], "
            "a[href*='vazifa'], .task-link, .assignment-link"
        )
        for el in task_els:
            task_href = el.get_attribute("href") or ""
            task_title = el.inner_text().strip()
            if task_title:
                tasks.append(Task(
                    subject=subject_name,
                    title=task_title,
                    description="",
                    url=task_href,
                ))

    return tasks
