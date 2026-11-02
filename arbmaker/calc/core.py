"""
arbmaker.calc.core — tipos base e utilitários do motor de cálculo.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime


class MissingInput(ValueError):
    """Input obrigatório ausente. A mensagem lista exatamente o que falta."""

    def __init__(self, calculo: str, faltando: list[str]):
        self.calculo = calculo
        self.faltando = faltando
        super().__init__(
            f"[{calculo}] inputs ausentes: {', '.join(faltando)}. "
            "O motor nao estima valores; forneca-os com fonte e data."
        )


@dataclass
class Check:
    nome: str
    ok: bool
    detalhe: str = ""


@dataclass
class Result:
    calculo: str
    inputs: dict
    outputs: dict
    checks: list[Check] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)
    fontes: dict = field(default_factory=dict)   # input -> {"origem": ..., "data": ...}

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ok"] = self.ok
        return d

    def to_json(self, **kw) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str, **kw)

    def with_sources(self, **fontes) -> "Result":
        """Anexa proveniencia: with_sources(caixa={'origem': 'ITR 4T25', 'data': '2026-02-20'})."""
        self.fontes.update(fontes)
        return self

    def render(self) -> str:
        """Texto legivel para colar em e-mail / chat."""
        lines = [f"== {self.calculo} ==", "inputs:"]
        for k, v in self.inputs.items():
            src = self.fontes.get(k)
            tag = f"   [{src.get('origem', '?')} {src.get('data', '')}]".rstrip() if src else ""
            lines.append(f"  {k}: {_fmt(v)}{tag}")
        lines.append("outputs:")
        for k, v in self.outputs.items():
            lines.append(f"  {k}: {_fmt(v)}")
        if self.checks:
            lines.append("checks:")
            for c in self.checks:
                lines.append(f"  [{'OK' if c.ok else 'FALHA'}] {c.nome}" + (f" - {c.detalhe}" if c.detalhe else ""))
        for n in self.notas:
            lines.append(f"nota: {n}")
        return "\n".join(lines)


def _fmt(v) -> str:
    if isinstance(v, float):
        if abs(v) >= 1000:
            return f"{v:,.0f}"
        return f"{v:,.4f}".rstrip("0").rstrip(".")
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v:,}"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {_fmt(x)}" for k, x in v.items()) + "}"
    if isinstance(v, list):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    return str(v)


# ---------------------------------------------------------------------------
# Validacao
# ---------------------------------------------------------------------------

def require(calculo: str, **inputs) -> None:
    """Levanta MissingInput se qualquer input for None."""
    faltando = [k for k, v in inputs.items() if v is None]
    if faltando:
        raise MissingInput(calculo, faltando)


def positive(calculo: str, **inputs) -> None:
    """Levanta ValueError se qualquer input nao for estritamente positivo."""
    for k, v in inputs.items():
        if v is None:
            raise MissingInput(calculo, [k])
        if v <= 0:
            raise ValueError(f"[{calculo}] {k} deve ser > 0, recebido {v}")


def non_negative(calculo: str, **inputs) -> None:
    for k, v in inputs.items():
        if v is None:
            raise MissingInput(calculo, [k])
        if v < 0:
            raise ValueError(f"[{calculo}] {k} deve ser >= 0, recebido {v}")


# ---------------------------------------------------------------------------
# Datas e retornos
# ---------------------------------------------------------------------------

def to_date(d) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    if isinstance(d, str):
        return datetime.strptime(d[:10], "%Y-%m-%d").date()
    raise TypeError(f"data invalida: {d!r}")


def days_between(d0, d1) -> int:
    """Dias corridos de d0 ate d1 (positivo se d1 > d0)."""
    return (to_date(d1) - to_date(d0)).days


def annualize(retorno: float, dias: int, base: int = 365) -> float:
    """Anualiza um retorno simples observado em `dias` corridos (composto)."""
    if dias <= 0:
        raise ValueError(f"dias deve ser > 0 para anualizar, recebido {dias}")
    if retorno <= -1:
        return -1.0
    return (1.0 + retorno) ** (base / dias) - 1.0


def pct(x: float, nd: int = 2) -> float:
    """Fracao -> percentual arredondado (0.1234 -> 12.34)."""
    return round(x * 100.0, nd)


def close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))
