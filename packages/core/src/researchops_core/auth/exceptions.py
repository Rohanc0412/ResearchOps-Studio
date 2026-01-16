from __future__ import annotations


class AuthError(Exception):
    pass


class AuthMissingError(AuthError):
    pass


class AuthInvalidTokenError(AuthError):
    pass


class AuthExpiredError(AuthError):
    pass


class AuthIssuerError(AuthError):
    pass


class AuthAudienceError(AuthError):
    pass

