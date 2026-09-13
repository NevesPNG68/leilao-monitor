import unittest
from decimal import Decimal

from monitor.evaluation import evaluate_opportunity


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.vehicle = {
            "titulo": "CHEVROLET ONIX", "marca": "CHEVROLET", "modelo": "ONIX", "ano": "2020",
            "km": "40000", "uf": "PR", "condicao_fisica": "NORMAL", "procedencia": "FINANCIAMENTO",
            "lance_atual": "40000", "preco_revenda_referencia": "70000",
        }
        self.search = {
            "id": "a", "marcas": '["CHEVROLET"]', "modelos": '["ONIX"]', "ano_minimo": "2018",
            "ano_maximo": "2023", "km_maximo": "80000", "condicoes_fisicas": '["NORMAL"]',
            "procedencias": '["FINANCIAMENTO"]', "modo_estados": "selecionados", "teto_custo_total": "70000",
            "margem_minima_percentual": "15",
        }
        self.costs = [
            {"nome": "Comissão", "tipo": "percentual_sobre_lance", "valor": "5", "ativo": 1},
            {"nome": "Frete", "tipo": "fixo", "valor": "2500", "ativo": 1},
            {"nome": "Reparos", "tipo": "fixo", "valor": "5000", "ativo": 1},
        ]

    def test_total_cost_is_bid_plus_all_configured_costs(self):
        result = evaluate_opportunity(self.vehicle, self.search, self.costs, [{"uf": "PR", "ativo": 1}], Decimal("70000"))
        self.assertEqual(result["custo_total_estimado"], Decimal("49500.00"))
        self.assertEqual(result["margem_estimada"], Decimal("20500.00"))
        self.assertEqual(result["classificacao"], "PRIORITÁRIA")

    def test_missing_bid_never_becomes_zero_cost(self):
        vehicle = dict(self.vehicle, lance_atual="")
        result = evaluate_opportunity(vehicle, self.search, self.costs, [{"uf": "PR", "ativo": 1}], Decimal("70000"))
        self.assertIsNone(result["custo_total_estimado"])
        self.assertEqual(result["classificacao"], "PENDENTE DE DADOS")
        self.assertIn("lance/preço atual", result["pendencias"])

    def test_missing_physical_condition_is_pending_not_a_false_positive(self):
        vehicle = dict(self.vehicle, condicao_fisica="")
        result = evaluate_opportunity(vehicle, self.search, self.costs, [{"uf": "PR", "ativo": 1}], Decimal("70000"))
        self.assertEqual(result["classificacao"], "PENDENTE DE DADOS")
        self.assertIn("condição física verificável", result["pendencias"])

    def test_inactive_state_is_excluded_when_selection_is_enabled(self):
        result = evaluate_opportunity(self.vehicle, self.search, self.costs, [{"uf": "PR", "ativo": 0}], Decimal("70000"))
        self.assertEqual(result["classificacao"], "FORA DOS CRITÉRIOS")
        self.assertIn("UF fora", result["pendencias"])
