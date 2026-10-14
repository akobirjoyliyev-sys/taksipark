from __future__ import annotations


class DomainError(Exception):
    """Biznes qoidasi buzilishi. `message` foydalanuvchiga ko‘rsatish uchun xavfsiz."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InsufficientFundsError(DomainError):
    pass


class ProviderUnavailableError(DomainError):
    pass


class NotFoundError(DomainError):
    pass


class PermissionDeniedError(DomainError):
    pass
