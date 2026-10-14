"""Userbot sessiyalarini shifrlash (Fernet / AES-128-CBC + HMAC).

Telethon StringSession akkauntga to‘liq kirish beradi, shuning uchun bazada faqat
shifrlangan holda saqlanadi. Kalit admin panelda saqlanadi («🛰 Userbot → 🔐 Kalit
yaratish» — avtomatik yaratiladi) va kerak bo‘lsa o‘zgartiriladi. `.env` dagi
`USERBOT_SESSION_KEY` faqat boshlang‘ich standart qiymat sifatida ishlatiladi.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class SessionCipherError(Exception):
    pass


def is_valid_fernet_key(key: str) -> bool:
    if not key:
        return False
    try:
        Fernet(key.encode())
    except (ValueError, TypeError):
        return False
    return True


class SessionCipher:
    def __init__(self, key: str) -> None:
        if not key:
            raise SessionCipherError(
                "Shifrlash kaliti yaratilmagan — admin panelda «🛰 Userbot → 🔐 Kalit yaratish» "
                "ni bosing."
            )
        try:
            self._fernet = Fernet(key.encode())
        except (ValueError, TypeError) as exc:
            raise SessionCipherError(
                "Shifrlash kaliti noto‘g‘ri formatda — panelda «🔐 Kalit yaratish» orqali "
                "qayta yarating."
            ) from exc

    def encrypt(self, session: str) -> str:
        return self._fernet.encrypt(session.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise SessionCipherError(
                "Sessiyani ochib bo‘lmadi: shifrlash kaliti almashgan bo‘lishi mumkin. "
                "Userbotni panel orqali qaytadan qo‘shing."
            ) from exc
