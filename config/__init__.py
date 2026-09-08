import os


# PyMySQL exposes the DB-API interface expected by Django's MySQL backend.
# It is loaded only when MySQL is explicitly selected, so existing SQLite
# installations (including PythonAnywhere) remain independent of this driver.
if os.getenv("DB_ENGINE", "sqlite").strip().lower() == "mysql":
    try:
        import pymysql
    except ImportError as exc:
        raise RuntimeError(
            "MySQL is selected but PyMySQL is not installed. "
            "Run: pip install -r requirements.txt"
        ) from exc
    pymysql.install_as_MySQLdb()
