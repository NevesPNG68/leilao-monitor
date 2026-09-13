"""Cliente HTTP do Apps Script, com retentativas e sem segredos na URL."""

from __future__ import annotations

import time
from typing import Any

import requests


class SheetsClient:
    def __init__(self, webapp_url: str, api_key: str, retries: int = 3) -> None:
        self.webapp_url = webapp_url.rstrip("/")
        self.api_key = api_key
        self.retries = retries

    def post(self, action: str, **payload: Any) -> dict[str, Any]:
        body = {"action": action, "key": self.api_key, **payload}
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = requests.post(self.webapp_url, json=body, timeout=(10, 60))
                response.raise_for_status()
                data = response.json()
                if data.get("error"):
                    raise RuntimeError(f"Apps Script recusou {action}: {data['error']}")
                return data
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"Falha ao executar {action} após {self.retries} tentativa(s): {last_error}")

    def load_config(self) -> dict[str, Any]:
        return self.post("config")

    def sync_results(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        return self.post("sync_results", resultados=results)

    def register_run(self, event: dict[str, Any]) -> None:
        self.post("run_log", evento=event)

    def daily_summary(self) -> dict[str, Any]:
        return self.post("daily_summary")
