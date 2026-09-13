"""Orquestra a coleta autorizada e registra falhas sem ocultá-las."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

from playwright.sync_api import sync_playwright

from monitor.config import is_active, parse_decimal
from monitor.evaluation import evaluate_opportunity
from monitor.providers import CopartProvider, ProviderBlockedError, ProviderValidationError
from monitor.sheets_client import SheetsClient

PROVIDERS = {"copart": CopartProvider}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def enrich(raw: dict, search: dict, config: dict) -> dict:
    evaluation = evaluate_opportunity(
        raw, search, config.get("custos", []), config.get("estados", []),
        parse_decimal(config.get("configuracoes", {}).get("teto_custo_total_padrao")) or Decimal("70000"),
    )
    return {
        **raw, "busca_ids": str(search.get("id")),
        "custo_total_estimado": str(evaluation["custo_total_estimado"] or ""),
        "margem_estimada": str(evaluation["margem_estimada"] or ""),
        "margem_estimada_percentual": str(evaluation["margem_estimada_percentual"] or ""),
        "pontuacao": str(evaluation["pontuacao"]), "classificacao": evaluation["classificacao"],
        "pendencias": evaluation["pendencias"], "detalhe_custos": evaluation["detalhe_custos"],
        "capturado_em": utc_now(),
    }


def main() -> int:
    webapp_url, api_key = os.environ.get("SHEETS_WEBAPP_URL"), os.environ.get("SHEETS_API_KEY")
    if not webapp_url or not api_key:
        print("[erro] Defina SHEETS_WEBAPP_URL e SHEETS_API_KEY nos secrets/ambiente.", file=sys.stderr)
        return 1
    client, started_at = SheetsClient(webapp_url, api_key), utc_now()
    try:
        config = client.load_config()
        searches = [row for row in config.get("buscas", []) if is_active(row.get("ativo", 1))]
        if not searches:
            print("[info] Nenhuma busca ativa.")
            return 0
        results, errors = [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1200})
            for search in searches:
                provider_cls = PROVIDERS.get(str(search.get("site", "")).casefold())
                if provider_cls is None:
                    errors.append(f"{search.get('nome')}: leiloeiro não implementado")
                    continue
                try:
                    raw_results = provider_cls().scrape(page, search)
                    results.extend(enrich(raw, search, config) for raw in raw_results)
                except (ProviderBlockedError, ProviderValidationError) as exc:
                    errors.append(f"{search.get('nome')}: {exc}")
                except Exception as exc:
                    errors.append(f"{search.get('nome')}: erro inesperado: {type(exc).__name__}: {exc}")
            browser.close()
        if results:
            response = client.sync_results(results)
            print(f"[ok] recebidos={response.get('recebidos')} novos={response.get('novos')} atualizados={response.get('atualizados')}")
        if os.environ.get("DAILY_SUMMARY") == "1":
            summary = client.daily_summary()
            print(f"[ok] resumo diário: {summary.get('oportunidades')} oportunidade(s), {summary.get('enviados')} entrega(s)")
        for error in errors:
            print(f"[aviso] {error}", file=sys.stderr)
        client.register_run({
            "iniciado_em": started_at, "finalizado_em": utc_now(), "buscas": len(searches),
            "resultados": len(results), "erros": " | ".join(errors), "status": "com_alertas" if errors else "ok",
        })
        return 0 if not errors else 2
    except Exception as exc:
        print(f"[erro] Execução interrompida: {type(exc).__name__}: {exc}", file=sys.stderr)
        try:
            client.register_run({"iniciado_em": started_at, "finalizado_em": utc_now(), "status": "erro", "erros": str(exc)})
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
