"""
arbmaker.calc — motor determinístico de finanças corporativas.

Princípios (ROADMAP.md):
    1. Nenhuma função estima um input que falta: levanta MissingInput listando o que falta.
    2. Todo cálculo devolve um Result com inputs, outputs, checks de reconciliação e notas.
    3. Zero LLM aqui dentro. O LLM extrai inputs e escreve narrativa; a conta é daqui.
"""
from .core import Check, MissingInput, Result, annualize, days_between
from . import capital_structure, conversion, parity, tender, capital_ops, merger

__all__ = [
    "Check", "MissingInput", "Result", "annualize", "days_between",
    "capital_structure", "conversion", "parity", "tender", "capital_ops", "merger",
]
