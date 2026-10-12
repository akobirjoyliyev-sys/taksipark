"""Claude AI yordamida test va vazifalarni hal qilish."""

import anthropic
import os


def solve_test_questions(questions: list[dict]) -> list[dict]:
    """
    Test savollarini Claude AI bilan javob beradi.
    Har bir savolga javob indeksini qaytaradi.
    """
    if not questions:
        return []

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    results = []
    for q in questions:
        prompt = _build_question_prompt(q)

        message = client.messages.create(
            model="claude-opus-5-5",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )

        answer_text = message.content[0].text.strip()
        answer_index = _parse_answer_index(answer_text, q["options"])

        results.append({
            **q,
            "answer": answer_text,
            "answer_index": answer_index,
        })

    return results


def solve_text_task(description: str, subject: str = "") -> str:
    """Matn ko'rinishidagi vazifaga javob yozadi."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    prompt = f"""Sen talaba yordamchisisan. Quyidagi universitetga topshiriq uchun javob yoz.

Fan: {subject or 'noma\'lum'}
Topshiriq: {description}

Iltimos, aniq va to'liq javob yoz. O'zbek tilida yozsan ham bo'ladi."""

    message = client.messages.create(
        model="claude-opus-5-5",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text.strip()


def _build_question_prompt(q: dict) -> str:
    opts_text = ""
    for i, opt in enumerate(q["options"]):
        opts_text += f"\n{chr(65+i)}) {opt}"

    return f"""Quyidagi test savoliga javob ber. Faqat to'g'ri javobning harfini yoz (A, B, C yoki D).

Savol: {q['text']}
{opts_text}

Javob (faqat harf):"""


def _parse_answer_index(answer_text: str, options: list) -> int:
    """Javob harfini indeksga aylantiradi."""
    answer_text = answer_text.strip().upper()
    if answer_text and answer_text[0] in "ABCD":
        return ord(answer_text[0]) - ord("A")
    return 0
