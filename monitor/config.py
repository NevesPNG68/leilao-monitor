"""Normalização defensiva da configuração recebida da planilha."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any


def is_active(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "sim", "yes", "ativo"}


def parse_decimal(value: Any) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace("R$", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_int(value: Any) -> int | None:
    number = parse_decimal(value)
    return int(number) if number is not None else None


def parse_list(value: Any) -> list[str]:
    """Aceita JSON de listas ou valores separados por vírgula."""
    if value is None or str(value).strip() == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raw = str(value).strip()
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Lista inválida na planilha: {raw}") from exc
        if not isinstance(parsed, list):
            raise ValueError(f"Esperada uma lista JSON: {raw}")
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [item.strip() for item in raw.split(",") if item.strip()]


def normalize_text(value: Any) -> str:
    return str(value or "").strip().casefold()
