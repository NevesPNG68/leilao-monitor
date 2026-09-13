"""Cálculo auditável de custo e classificação de oportunidades."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .config import is_active, normalize_text, parse_decimal, parse_int, parse_list

MONEY = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CostLine:
    name: str
    amount: Decimal | None
    source: str
    estimated: bool
    missing: bool = False


def cost_lines(bid: Decimal | None, costs: list[dict[str, Any]], search_id: str) -> list[CostLine]:
    lines: list[CostLine] = []
    for row in costs:
        if not is_active(row.get("ativo", 1)):
            continue
        owner = str(row.get("busca_id") or "").strip()
        if owner and owner != str(search_id):
            continue
        name = str(row.get("nome") or row.get("descricao") or "Custo sem nome")
        kind = normalize_text(row.get("tipo"))
        value = parse_decimal(row.get("valor"))
        source = str(row.get("origem") or "estimativa configurada")
        if value is None:
            lines.append(CostLine(name, None, source, True, True))
        elif kind == "percentual_sobre_lance":
            lines.append(
                CostLine(name, money(bid * value / Decimal("100")), source, True)
                if bid is not None else CostLine(name, None, source, True, True)
            )
        elif kind in {"fixo", "valor_observado"}:
            lines.append(CostLine(name, money(value), source, kind != "valor_observado"))
        else:
            lines.append(CostLine(name, None, f"tipo de custo inválido: {kind or 'vazio'}", True, True))
    return lines


def matches_search(vehicle: dict[str, Any], search: dict[str, Any], states: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    title, brand, model = (normalize_text(vehicle.get(k)) for k in ("titulo", "marca", "modelo"))
    for column, actual in (("marcas", brand), ("modelos", model)):
        allowed = [normalize_text(item) for item in parse_list(search.get(column))]
        if allowed and not any(item in actual or item in title for item in allowed):
            issues.append(f"{column} fora do filtro")
    for column, actual in (
        ("condicoes_fisicas", normalize_text(vehicle.get("condicao_fisica"))),
        ("procedencias", normalize_text(vehicle.get("procedencia"))),
    ):
        allowed = [normalize_text(item) for item in parse_list(search.get(column))]
        if allowed and actual not in allowed:
            issues.append(f"{column} fora do filtro ou ausente")
    year = parse_int(vehicle.get("ano"))
    minimum, maximum = parse_int(search.get("ano_minimo")), parse_int(search.get("ano_maximo"))
    if minimum is not None and (year is None or year < minimum):
        issues.append("ano mínimo não atendido")
    if maximum is not None and (year is None or year > maximum):
        issues.append("ano máximo não atendido")
    km, km_limit = parse_int(vehicle.get("km")), parse_int(search.get("km_maximo"))
    if km_limit is not None and (km is None or km > km_limit):
        issues.append("quilometragem fora do filtro ou ausente")
    active_states = {normalize_text(item.get("uf")) for item in states if is_active(item.get("ativo", 1))}
    if normalize_text(search.get("modo_estados") or "todos") == "selecionados":
        vehicle_state = normalize_text(vehicle.get("uf"))
        if vehicle_state not in active_states:
            issues.append("UF fora da seleção")
        else:
            state_row = next((row for row in states if normalize_text(row.get("uf")) == vehicle_state), {})
            for label, field, value in (
                ("cidade", "cidades_incluidas", normalize_text(vehicle.get("cidade"))),
                ("pátio", "patios_incluidos", normalize_text(vehicle.get("patio"))),
            ):
                included = [normalize_text(item) for item in parse_list(state_row.get(field))]
                if included and not any(item in value for item in included):
                    issues.append(f"{label} fora da seleção")
            for label, field, value in (
                ("cidade", "cidades_excluidas", normalize_text(vehicle.get("cidade"))),
                ("pátio", "patios_excluidos", normalize_text(vehicle.get("patio"))),
            ):
                excluded = [normalize_text(item) for item in parse_list(state_row.get(field))]
                if excluded and any(item in value for item in excluded):
                    issues.append(f"{label} excluído na configuração")
    return issues


def evaluate_opportunity(vehicle: dict[str, Any], search: dict[str, Any], costs: list[dict[str, Any]], states: list[dict[str, Any]], default_ceiling: Decimal) -> dict[str, Any]:
    bid = parse_decimal(vehicle.get("lance_atual"))
    reference_sale = parse_decimal(vehicle.get("preco_revenda_referencia") or search.get("preco_revenda_referencia"))
    ceiling = parse_decimal(search.get("teto_custo_total")) or default_ceiling
    lines = cost_lines(bid, costs, str(search.get("id") or ""))
    missing = [line.name for line in lines if line.missing]
    if bid is None:
        missing.insert(0, "lance/preço atual")
    if reference_sale is None:
        missing.append("preço de revenda de referência")
    required_physical_conditions = parse_list(search.get("condicoes_fisicas"))
    if required_physical_conditions and not normalize_text(vehicle.get("condicao_fisica")):
        missing.append("condição física verificável")
    total = money(bid + sum((line.amount or Decimal("0")) for line in lines)) if bid is not None and not missing else None
    margin = money(reference_sale - total) if total is not None and reference_sale is not None else None
    margin_pct = money(margin * Decimal("100") / reference_sale) if margin is not None and reference_sale else None
    issues = matches_search(vehicle, search, states)
    if required_physical_conditions and not normalize_text(vehicle.get("condicao_fisica")):
        issues = [issue for issue in issues if not issue.startswith("condicoes_fisicas")]
    target_margin = parse_decimal(search.get("margem_minima_percentual"))
    if total is not None and total > ceiling:
        issues.append("custo total acima do teto")
    if target_margin is not None and (margin_pct is None or margin_pct < target_margin):
        issues.append("margem abaixo da meta ou indisponível")
    score = Decimal("0")
    if total is not None and ceiling > 0 and total <= ceiling:
        score += min(Decimal("35"), money((ceiling - total) * Decimal("35") / ceiling))
    if margin_pct is not None:
        score += min(Decimal("35"), max(Decimal("0"), margin_pct))
    if not any("condicoes_fisicas" in issue for issue in issues):
        score += Decimal("15")
    if bid is not None and reference_sale is not None and not missing:
        score += Decimal("15")
    classification = (
        "PENDENTE DE DADOS" if missing else
        "FORA DOS CRITÉRIOS" if issues else
        "EM ANÁLISE" if margin_pct is None else
        "PRIORITÁRIA"
    )
    return {
        "custo_total_estimado": total, "margem_estimada": margin,
        "margem_estimada_percentual": margin_pct, "pontuacao": money(score),
        "classificacao": classification, "pendencias": "; ".join(missing + issues),
        "detalhe_custos": [line.__dict__ for line in lines],
    }
