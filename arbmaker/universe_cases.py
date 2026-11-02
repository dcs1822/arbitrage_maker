"""
arbmaker.universe_cases — as empresas dos casos em foco (ROADMAP §5: responder bem esses antes de escalar).

cd_cvm None = resolver pelo cadastro (cad_cia_aberta.csv) na primeira coleta online.
`nome_busca` e um regex aplicado ao nome normalizado (sem acento, maiusculo) do cadastro/IPE.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Empresa:
    slug: str
    nome: str
    nome_busca: str
    tickers: list[str]
    cd_cvm: str | None = None
    anos: tuple[int, int] = (2020, 2026)
    casos: list[str] = field(default_factory=list)


EMPRESAS: dict[str, Empresa] = {
    "westwing": Empresa("westwing", "Westwing Comércio Varejista S.A.", r"WESTWING", ["WEST3"], cd_cvm="25518",
                        anos=(2020, 2026), casos=["westwing_2022_2026"]),
    "getninjas": Empresa("getninjas", "GetNinjas S.A.", r"GETNINJAS|GET ?NINJAS", ["NINJ3"], anos=(2021, 2026),
                         casos=["getninjas_2023"]),
    "viveo": Empresa("viveo", "Viveo (CM Hospitalar S.A.)", r"CM HOSPITALAR|VIVEO", ["VVEO3"], anos=(2021, 2026),
                     casos=["viveo_2025"]),
    "energisa": Empresa("energisa", "Energisa S.A.", r"^ENERGISA S\.?A\.?$|^ENERGISA SA$", ["ENGI3", "ENGI4", "ENGI11"],
                        cd_cvm="15253", anos=(2020, 2026), casos=["energisa_on_pn"]),
    "raizen": Empresa("raizen", "Raízen S.A.", r"^RAIZEN S\.?A\.?$|^RAIZEN SA$", ["RAIZ4"], anos=(2021, 2026),
                      casos=["raizen_spx_2026"]),
}
