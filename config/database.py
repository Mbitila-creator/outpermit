import os

from django.core.exceptions import ImproperlyConfigured


SUPPORTED_DATABASE_ENGINES = {"sqlite", "mysql"}


def database_config(environ=None, base_dir=None):
    """Build the default database configuration from environment variables."""
    environ = os.environ if environ is None else environ
    engine = environ.get("DB_ENGINE", "sqlite").strip().lower()

    if engine not in SUPPORTED_DATABASE_ENGINES:
        raise ImproperlyConfigured(
            "DB_ENGINE must be either 'sqlite' or 'mysql'."
        )

    if engine == "sqlite":
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": base_dir / "db.sqlite3",
        }

    required = ("DB_NAME", "DB_USER", "DB_PASSWORD")
    missing = [name for name in required if not environ.get(name)]
    if missing:
        raise ImproperlyConfigured(
            "MySQL is selected, but these environment variables are missing: "
            + ", ".join(missing)
        )

    return {
        "ENGINE": "django.db.backends.mysql",
        "NAME": environ["DB_NAME"],
        "USER": environ["DB_USER"],
        "PASSWORD": environ["DB_PASSWORD"],
        "HOST": environ.get("DB_HOST", "127.0.0.1"),
        "PORT": environ.get("DB_PORT", "3306"),
        "CONN_MAX_AGE": int(environ.get("DB_CONN_MAX_AGE", "60")),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            "isolation_level": "read committed",
        },
    }
