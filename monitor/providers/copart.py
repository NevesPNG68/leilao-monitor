"""Adapter Copart validado contra a listagem pública de financiamento."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from playwright.sync_api import expect

class ProviderBlockedError(RuntimeError):
    """Login, CAPTCHA ou limitação que exige ação humana/documentação."""


class ProviderValidationError(RuntimeError):
    """A estrutura da página não foi validada para extração automática."""


def _location(value: str) -> tuple[str, str]:
    if "-" not in value:
        return value.strip(), ""
    city, state = value.strip().rsplit("-", 1)
    return city.strip(), state.strip().upper()


@dataclass
class CopartProvider:
    """Extrai a tabela cuja estrutura foi observada na URL pública de financiamento."""

    def inspect_access(self, page, url: str):
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2_000)
        content = page.locator("body").inner_text(timeout=15_000).casefold()
        if "captcha" in content or "recaptcha" in content or "verify you are human" in content:
            raise ProviderBlockedError(f"Copart exibiu CAPTCHA em {page.url}. Nenhuma tentativa de contorno foi feita.")
        if "resultado da busca" not in content and "resultados de busca" not in content:
            if "entrar" in content or "login" in content:
                raise ProviderBlockedError(f"Copart exige login para acessar {page.url}. Nenhuma tentativa de login foi feita.")
            raise ProviderValidationError(f"A URL não apresentou uma listagem Copart reconhecível: {page.url}.")
        listing = self._listing_table(page)
        try:
            listing.locator("tr").nth(1).wait_for(state="attached", timeout=15_000)
        except Exception as exc:
            raise ProviderValidationError("A tabela Copart foi exibida sem linhas de lote no tempo esperado.") from exc
        return listing

    def _listing_table(self, page):
        tables = page.locator("table")
        for index in range(tables.count()):
            table = tables.nth(index)
            headers = " ".join(table.locator("th").all_inner_texts()).casefold()
            if "código" in headers and "lance atual" in headers and "lote" in headers:
                return table
        raise ProviderValidationError("A tabela de lotes Copart mudou: cabeçalhos Código/Lote/Lance Atual não foram encontrados.")

    def _row_to_result(self, row, base_url: str) -> dict | None:
        cells = row.locator("td").all_inner_texts()
        if len(cells) != 16:
            return None
        code = re.search(r"\d+", cells[2])
        if not code:
            return None
        city, state = _location(cells[10])
        lot_link = row.locator("a[href*='/lot/']").first.get_attribute("href")
        if lot_link and not lot_link.startswith(("http://", "https://", "/")):
            lot_link = f"/{lot_link}"
        bid = re.search(r"R\$\s*([\d.,]+)", cells[14])
        return {
            "site": "copart", "lote": code.group(0), "status_lote": "ATIVO",
            "ano": cells[3].strip(), "marca": cells[4].strip(), "modelo": cells[5].strip(),
            "titulo": f"{cells[3].strip()} {cells[4].strip()} {cells[5].strip()}".strip(),
            "documento": cells[6].strip(), "categoria": cells[7].strip(),
            "procedencia": cells[8].strip(), "condicao_fisica": "",
            "cidade": city, "uf": state, "data_leilao": " ".join(cells[11].split()),
            "patio": cells[12].strip(), "lance_atual": f"R$ {bid.group(1)}" if bid else "",
            "tipo_preco": "lance_atual", "link": urljoin(base_url, lot_link or ""),
        }

    def scrape(self, page, search: dict) -> list[dict]:
        configured_limit = str(search.get("paginas_maximas") or "").strip()
        page_limit = int(configured_limit) if configured_limit.isdigit() else 100
        results, seen = [], set()
        table = self.inspect_access(page, str(search["search_url"]))
        for page_number in range(page_limit):
            rows = table.locator("tr")
            for index in range(1, rows.count()):
                result = self._row_to_result(rows.nth(index), page.url)
                if result and result["lote"] not in seen:
                    seen.add(result["lote"])
                    results.append(result)
            if page_number + 1 >= page_limit:
                break
            next_button = page.locator("a[aria-controls='serverSideDataTable'][data-dt-idx='9']").first
            parent_class = next_button.locator("xpath=..").get_attribute("class") if next_button.count() else ""
            if not next_button.count() or "disabled" in (parent_class or "").casefold():
                break
            first_lot = rows.nth(1).locator("td").nth(2).inner_text().strip()
            next_button.click()
            try:
                first_code_cell = rows.nth(1).locator("td").nth(2)
                expect(first_code_cell).not_to_contain_text(first_lot, timeout=15_000)
                expect(first_code_cell).to_contain_text(re.compile(r"\d+"), timeout=15_000)
                page.wait_for_timeout(1_000)
            except Exception as exc:
                raise ProviderValidationError("A paginação Copart não atualizou a primeira linha no tempo esperado.") from exc
            table = self._listing_table(page)
        if not results:
            raise ProviderValidationError("A tabela Copart foi encontrada, mas nenhuma linha válida foi extraída.")
        return results
