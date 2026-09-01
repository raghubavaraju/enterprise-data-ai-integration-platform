"""Structured logging with correlation-id propagation.

Every log line carries ``correlationId``, ``service``, ``layer`` and, where the
request touched them, ``customerId`` (hashed) and ``downstream``.  This is the
same field contract the Mule applications emit (see
``mule/common/global-logging.xml``) so that a single correlation id can be
searched across Mule, the data API and the AI service.
"""
from __future__ import annotations

import logging
import sys
from contextvars import ContextVar

from pythonjsonlogger import json as jsonlogger

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")
service_name_var: ContextVar[str] = ContextVar("service_name", default="unknown")


class CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.correlationId = correlation_id_var.get()
        record.service = service_name_var.get()
        return True


def configure_logging(service: str, level: str = "INFO", fmt: str = "json") -> logging.Logger:
    service_name_var.set(service)
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(service)s %(correlationId)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
        ))
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-5s [%(correlationId)s] %(name)s - %(message)s"))
    handler.addFilter(CorrelationFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    logging.getLogger("uvicorn.access").handlers = [handler]
    return logging.getLogger(service)
