"""Centralised logging configuration for the backend."""
import logging
import os


def configure_logging() -> None:
    """
    Configure the root logger.

    Log level is read from the LOG_LEVEL environment variable (default: INFO).
    Call this once from the entry point of any long-running process (worker).
    FastAPI / uvicorn configure their own handlers, so this is intentionally
    not called from main.py.
    """
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
