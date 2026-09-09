import hashlib

from django.conf import settings
from django.core.cache import cache


def _keys(request, username):
    address = request.META.get("REMOTE_ADDR", "unknown")
    username = (username or "").strip().casefold()
    identities = (f"address:{address}", f"account:{username}")
    return tuple(
        "login-failures:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        for identity in identities
    )


def login_is_blocked(request, username):
    return any(
        int(cache.get(key, 0)) >= settings.LOGIN_THROTTLE_ATTEMPTS
        for key in _keys(request, username)
    )


def record_login_failure(request, username):
    for key in _keys(request, username):
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=settings.LOGIN_THROTTLE_WINDOW_SECONDS)


def clear_login_failures(request, username):
    cache.delete_many(_keys(request, username))
