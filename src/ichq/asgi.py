"""ASGI-Einstiegspunkt für uvicorn/gunicorn: ``ichq.asgi:app``."""
from ichq.app import create_app

app = create_app()
