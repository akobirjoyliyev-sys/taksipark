"""
ISFT LMS Bot - my.isft.uz uchun avtomatik vazifa bajaruvchi.

Ishlatish:
  python main.py list          # barcha fanlar va vazifalarni ko'rish
  python main.py run           # barcha topshirilmagan vazifalarni bajarish
  python main.py run --subject "Fizika 1"   # faqat bitta fanning vazifalarini
"""

import os
import sys
import click
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

load_dotenv()

console = Console()


def check_env():
    username = os.getenv("ISFT_USERNAME")
    password = os.getenv("ISFT_PASSWORD")
    if not username or not password:
        console.print("[red]XATO:[/] .env faylida ISFT_USERNAME va ISFT_PASSWORD bo'lishi kerak!")
        console.print("  .env.example faylini nusxalab .env yarating va ma'lumotlaringizni kiriting.")
        sys.exit(1)
    return username, password


@click.group()
def cli():
    """ISFT LMS Bot — my.isft.uz uchun avtomatik vazifa bajaruvchi."""
    pass


@cli.command()
@click.option("--show-browser", is_flag=True, help="Brauzerni ko'rsatib ishlash (debug uchun)")
def list(show_browser):
    """Barcha fanlar va vazifalarni ekranda ko'rsatadi."""
    username, password = check_env()

    from browser import ISFTBrowser
    from scraper import get_subjects, get_distance_learning_tasks

    console.print(Panel("[bold cyan]ISFT LMS Bot[/] — Vazifalar ro'yxati", expand=False))

    with ISFTBrowser(headless=not show_browser) as b:
        console.print("  [yellow]Tizimga kirish...[/]")
        ok = b.login(username, password)
        if not ok:
            console.print("[red]Login muvaffaqiyatsiz! Username/password ni tekshiring.[/]")
            return

        console.print("  [yellow]Fanlar yuklanmoqda...[/]")
        subjects = get_subjects(b)

        table = Table(title="Fanlaringiz", show_lines=True)
        table.add_column("#", style="dim", width=4)
        table.add_column("Fan nomi", style="bold")
        table.add_column("URL")

        for i, s in enumerate(subjects, 1):
            table.add_row(str(i), s.name, s.url)

        console.print(table)

        console.print("\n  [yellow]Masofaviy ta'lim vazifalari yuklanmoqda...[/]")
        tasks = get_distance_learning_tasks(b)

        if tasks:
            t2 = Table(title="Vazifalar", show_lines=True)
            t2.add_column("#", width=4)
            t2.add_column("Fan", style="bold")
            t2.add_column("Vazifa nomi")
            t2.add_column("Holati")
            for i, task in enumerate(tasks, 1):
                status_color = "green" if task.status == "topshirilgan" else "red"
                t2.add_row(
                    str(i),
                    task.subject or "—",
                    task.title,
                    f"[{status_color}]{task.status}[/]",
                )
            console.print(t2)
        else:
            console.print("[yellow]Hozircha vazifalar topilmadi yoki sahifa strukturasi o'zgacha.[/]")
            console.print("  [dim]--show-browser bilan ishlab ko'ring va vazifa URL ini aniqlang.[/]")


@cli.command()
@click.option("--subject", default=None, help="Faqat shu fanning vazifalarini bajaring")
@click.option("--task-url", default=None, help="To'g'ridan-to'g'ri vazifa URL i")
@click.option("--show-browser", is_flag=True, help="Brauzerni ko'rsatib ishlash")
@click.option("--dry-run", is_flag=True, help="Faqat ko'rsin, topshirmasin")
def run(subject, task_url, show_browser, dry_run):
    """Topshirilmagan vazifalarni avtomatik bajaradi."""
    username, password = check_env()

    from browser import ISFTBrowser
    from scraper import get_distance_learning_tasks, get_task_detail
    from ai_solver import solve_test_questions, solve_text_task
    from submitter import submit_test, submit_text

    has_ai = bool(os.getenv("ANTHROPIC_API_KEY"))

    console.print(Panel(
        f"[bold cyan]ISFT Bot ishga tushdi[/]\n"
        f"  AI javob: {'[green]yoqilgan[/]' if has_ai else '[yellow]o\'chirilgan[/] (ANTHROPIC_API_KEY yo\'q)'}\n"
        f"  Dry-run:  {'[yellow]ha — topshirmaydi[/]' if dry_run else '[green]yo\'q — topshiradi[/]'}",
        expand=False
    ))

    with ISFTBrowser(headless=not show_browser) as b:
        console.print("  Tizimga kirish...")
        ok = b.login(username, password)
        if not ok:
            console.print("[red]Login muvaffaqiyatsiz![/]")
            return
        console.print("  [green]✓[/] Kirish muvaffaqiyatli\n")

        if task_url:
            tasks_to_do = [get_task_detail(b, task_url)]
        else:
            all_tasks = get_distance_learning_tasks(b)
            tasks_to_do = [
                t for t in all_tasks
                if t.status != "topshirilgan" and (not subject or subject.lower() in t.subject.lower())
            ]

        if not tasks_to_do:
            console.print("[green]Bajariladigan vazifalar yo'q yoki hammasi topshirilgan![/]")
            return

        console.print(f"[bold]{len(tasks_to_do)} ta vazifa topildi[/]\n")

        for i, task in enumerate(tasks_to_do, 1):
            console.print(f"[bold cyan][{i}/{len(tasks_to_do)}][/] {task.title or task.url}")

            if not task.title and not task.description:
                task = get_task_detail(b, task.url)

            if task.task_type == "test" and task.questions:
                console.print(f"  Tur: test ({len(task.questions)} ta savol)")
                if has_ai:
                    console.print("  AI javob bermoqda...")
                    solved = solve_test_questions(task.questions)
                    if not dry_run:
                        ok = submit_test(b, task.url, solved)
                        console.print(f"  [{'green' if ok else 'red'}]{'✓ Topshirildi' if ok else '✗ Topshirib bo\'lmadi'}[/]")
                    else:
                        for q in solved:
                            console.print(f"    Savol: {q['text'][:60]}... → {q.get('answer', '?')}")
                else:
                    console.print("  [yellow]AI kalit yo'q — bu vazifa qoldirildi[/]")

            elif task.task_type == "text":
                console.print("  Tur: matnli javob")
                if has_ai:
                    console.print("  AI javob yozmoqda...")
                    answer = solve_text_task(task.description, task.subject)
                    console.print(f"  Javob: {answer[:80]}...")
                    if not dry_run:
                        ok = submit_text(b, task.url, answer)
                        console.print(f"  [{'green' if ok else 'red'}]{'✓ Topshirildi' if ok else '✗ Topshirib bo\'lmadi'}[/]")
                else:
                    console.print("  [yellow]AI kalit yo'q — bu vazifa qoldirildi[/]")

            else:
                console.print(f"  [yellow]Noma'lum tur ({task.task_type}) — qo'lda bajaring[/]")

            console.print()

    console.print("[bold green]Bot ishi tugadi![/]")


@cli.command()
@click.argument("task_url")
def inspect(task_url):
    """Bitta vazifaning tuzilmasini ko'rsatadi (debug uchun)."""
    username, password = check_env()
    from browser import ISFTBrowser
    from scraper import get_task_detail

    with ISFTBrowser(headless=False) as b:
        b.login(username, password)
        task = get_task_detail(b, task_url)
        console.print(Panel(f"""
[bold]Sarlavha:[/] {task.title}
[bold]Tur:[/] {task.task_type}
[bold]Tavsif:[/] {task.description[:200] if task.description else '—'}
[bold]Savollar soni:[/] {len(task.questions)}
""", title="Vazifa tafsilotlari"))
        input("Enter bosing (brauzer yopiladi)...")


if __name__ == "__main__":
    cli()
