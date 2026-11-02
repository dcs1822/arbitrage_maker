"""
arbmaker.sources.cvm_open_data — Portal de Dados Abertos da CVM (dados.cvm.gov.br).

Substitui a extracao de DFP/ITR por LLM a partir de PDF (que falhou em 25 de 36 periodos
no backtest WestWing) por leitura deterministica dos CSVs oficiais.

Conjuntos usados:
    DFP  /dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{ano}.zip
    ITR  /dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{ano}.zip
    IPE  /dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{ano}.zip   (todos os docs eventuais, com link)
    FRE  /dados/CIA_ABERTA/DOC/FRE/DADOS/fre_cia_aberta_{ano}.zip
    CAD  /dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv           (cadastro: nome <-> CD_CVM <-> CNPJ)

Formato dos CSVs de DFP/ITR (sep ';', latin-1):
    CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;ORDEM_EXERC;
    [DT_INI_EXERC;]DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA

ATENCAO: o mapeamento de contas abaixo segue o plano de contas padrao da CVM (contas fixas).
Foi escrito sem acesso a rede nesta sessao; validar contra um arquivo real na primeira rodada
online (ver ROADMAP.md, Fase 1).  Empresas podem alocar debentures/arrendamento em subcontas
diferentes; a funcao devolve as subcontas de divida para auditoria.

Modo offline: todas as funcoes de leitura aceitam o caminho de um zip/csv ja baixado
(ex: os arquivos em P:\\Analise\\CVM).
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pandas as pd

BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA"


# ---------------------------------------------------------------------------
# URLs e download
# ---------------------------------------------------------------------------

def url_dfp(ano: int) -> str:
    return f"{BASE}/DOC/DFP/DADOS/dfp_cia_aberta_{ano}.zip"


def url_itr(ano: int) -> str:
    return f"{BASE}/DOC/ITR/DADOS/itr_cia_aberta_{ano}.zip"


def url_ipe(ano: int) -> str:
    return f"{BASE}/DOC/IPE/DADOS/ipe_cia_aberta_{ano}.zip"


def url_fre(ano: int) -> str:
    return f"{BASE}/DOC/FRE/DADOS/fre_cia_aberta_{ano}.zip"


def url_cad() -> str:
    return f"{BASE}/CAD/DADOS/cad_cia_aberta.csv"


def fetch(url: str, cache_dir: Path, force: bool = False, timeout: int = 300) -> Path:
    """Baixa `url` para cache_dir (nome = basename da URL). Reusa o cache se existir."""
    import requests

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / url.rsplit("/", 1)[-1]
    if dest.exists() and not force:
        return dest
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        tmp.replace(dest)
    return dest


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------

_READ_KW = dict(sep=";", encoding="latin-1", dtype=str, keep_default_na=False)


def read_csv_from_zip(zip_path: Path, name_contains: str) -> pd.DataFrame:
    """Le o primeiro CSV dentro do zip cujo nome contem `name_contains`."""
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if name_contains in n]
        if not names:
            raise FileNotFoundError(f"nenhum arquivo com '{name_contains}' em {zip_path}: {z.namelist()[:10]}")
        with z.open(names[0]) as f:
            return pd.read_csv(io.TextIOWrapper(f, encoding="latin-1"), sep=";", dtype=str, keep_default_na=False)


def read_statement(zip_path: Path, doc: str, demonstracao: str, ano: int, consolidado: bool = True) -> pd.DataFrame:
    """
    doc: 'dfp' | 'itr'; demonstracao: 'BPA' | 'BPP' | 'DRE' | 'DFC_MI' | 'DFC_MD' | 'DVA' | 'DMPL'
    """
    suf = "con" if consolidado else "ind"
    return read_csv_from_zip(zip_path, f"{doc}_cia_aberta_{demonstracao}_{suf}_{ano}.csv")


def read_cad(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, **_READ_KW)


# ---------------------------------------------------------------------------
# Plano de contas padrao -> schema interno (financials_timeline)
# ---------------------------------------------------------------------------

CONTAS = {
    # balanco (BPA/BPP)
    "ativo_total":            ("BPA", "1"),
    "caixa_equivalentes":     ("BPA", "1.01.01"),
    "aplicacoes_financeiras": ("BPA", "1.01.02"),
    "divida_cp":              ("BPP", "2.01.04"),       # Emprestimos e Financiamentos (circulante)
    "divida_cp_arrendamento": ("BPP", "2.01.04.03"),
    "divida_lp":              ("BPP", "2.02.01"),       # Emprestimos e Financiamentos (nao circulante)
    "divida_lp_arrendamento": ("BPP", "2.02.01.03"),
    "patrimonio_liquido":     ("BPP", "2.03"),
    "minoritarios":           ("BPP", "2.03.09"),
    # DRE
    "receita_liquida":        ("DRE", "3.01"),
    "lucro_bruto":            ("DRE", "3.03"),
    "ebit":                   ("DRE", "3.05"),          # Resultado antes do resultado financeiro e tributos
    "resultado_financeiro":   ("DRE", "3.06"),
    "lucro_liquido":          ("DRE", "3.11"),          # Lucro/Prejuizo Consolidado do Periodo
    "lucro_liquido_continuadas": ("DRE", "3.09"),
    # DFC (metodo indireto)
    "fco":                    ("DFC_MI", "6.01"),
    "fci":                    ("DFC_MI", "6.02"),
    "fcf":                    ("DFC_MI", "6.03"),
    # DVA
    "depreciacao_amortizacao": ("DVA", "7.04.01"),
}


def _to_float(s: str) -> float | None:
    if s is None or s == "":
        return None
    try:
        return float(str(s).replace(",", "."))
    except ValueError:
        return None


def _escala_para_mil(valor: float | None, escala: str) -> float | None:
    if valor is None:
        return None
    e = (escala or "").strip().upper()
    if e == "MIL":
        return valor
    if e == "UNIDADE":
        return valor / 1000.0
    if e == "MILHAO" or e == "MILHÃO":
        return valor * 1000.0
    return valor


def _latest_version(df: pd.DataFrame) -> pd.DataFrame:
    """Mantem apenas a maior VERSAO por (CD_CVM, DT_REFER) — reapresentacoes substituem."""
    if "VERSAO" not in df.columns:
        return df
    v = pd.to_numeric(df["VERSAO"], errors="coerce").fillna(0)
    df = df.assign(_v=v)
    idx = df.groupby(["CD_CVM", "DT_REFER"])["_v"].transform("max") == df["_v"]
    return df[idx].drop(columns="_v")


def _periodo_label(tipo: str, dt_refer: str) -> str:
    y, m = dt_refer[:4], int(dt_refer[5:7])
    if tipo == "DFP":
        return y
    return {3: "1T", 6: "2T", 9: "3T", 12: "4T"}.get(m, f"M{m}") + y[2:]


def _norm_cd(cd) -> str:
    try:
        return str(int(str(cd).strip()))
    except ValueError:
        return str(cd).strip()


def extract_financials(statements: dict[str, pd.DataFrame], cd_cvm: str | int, tipo: str) -> list[dict]:
    """
    statements: {"BPA": df, "BPP": df, "DRE": df, "DFC_MI": df, "DVA": df} (consolidado).
    tipo: "DFP" | "ITR".
    Devolve lista ordenada por data_referencia no schema de data/<empresa>/structured/financials_timeline.json.
    Para ITR, a DRE do trimestre isolado usa DT_INI_EXERC = inicio do trimestre; o acumulado vai em dre_acumulado.
    """
    cd = _norm_cd(cd_cvm)
    out: dict[str, dict] = {}
    for campo, (dem, conta) in CONTAS.items():
        df = statements.get(dem)
        if df is None or df.empty:
            continue
        d = df[(df["CD_CVM"].map(_norm_cd) == cd) & (df["CD_CONTA"].str.strip() == conta)]
        if "ORDEM_EXERC" in d.columns:
            d = d[d["ORDEM_EXERC"].str.strip().str.upper().isin(["ÚLTIMO", "ULTIMO"])]
        d = _latest_version(d)
        for _, row in d.iterrows():
            ref = row["DT_REFER"][:10]
            rec = out.setdefault(ref, {
                "tipo": tipo, "data_referencia": ref, "periodo": _periodo_label(tipo, ref),
                "unidade": "R$ mil", "fonte": "CVM dados abertos", "versao": row.get("VERSAO"),
                "balanco": {}, "dre": {}, "dre_acumulado": {}, "fluxo": {}, "fluxo_acumulado": {},
            })
            val = _escala_para_mil(_to_float(row["VL_CONTA"]), row.get("ESCALA_MOEDA", "MIL"))
            if dem in ("BPA", "BPP"):
                rec["balanco"][campo] = val
            else:
                ini = (row.get("DT_INI_EXERC") or "")[:10]
                bucket_fluxo = dem in ("DFC_MI", "DFC_MD")
                acumulado = tipo == "ITR" and ini and ini[5:7] == "01" and ref[5:7] != "03"
                if dem == "DVA":
                    # DVA em ITR e acumulada no ano; guardamos no acumulado e tambem no trimestre se 1T
                    if tipo == "DFP" or ref[5:7] == "03":
                        rec["dre"][campo] = val
                    rec["dre_acumulado"][campo] = val
                    continue
                target = ("fluxo_acumulado" if acumulado else "fluxo") if bucket_fluxo else ("dre_acumulado" if acumulado else "dre")
                rec[target][campo] = val
                if tipo == "DFP" or ref[5:7] == "03":
                    other = "fluxo_acumulado" if bucket_fluxo else "dre_acumulado"
                    rec[other][campo] = val

    # derivados
    for rec in out.values():
        b = rec["balanco"]
        cx = b.get("caixa_equivalentes")
        ap = b.get("aplicacoes_financeiras")
        if cx is not None or ap is not None:
            b["caixa_total"] = (cx or 0.0) + (ap or 0.0)
        dcp, dlp = b.get("divida_cp"), b.get("divida_lp")
        if dcp is not None or dlp is not None:
            b["divida_bruta"] = (dcp or 0.0) + (dlp or 0.0)
            arr = (b.get("divida_cp_arrendamento") or 0.0) + (b.get("divida_lp_arrendamento") or 0.0)
            b["divida_bruta_ex_arrendamento"] = b["divida_bruta"] - arr
        for bucket in ("dre", "dre_acumulado"):
            dre = rec[bucket]
            if dre.get("lucro_liquido") is None and dre.get("lucro_liquido_continuadas") is not None:
                dre["lucro_liquido"] = dre["lucro_liquido_continuadas"]
            if dre.get("ebit") is not None and dre.get("depreciacao_amortizacao") is not None:
                dre["ebitda"] = dre["ebit"] + abs(dre["depreciacao_amortizacao"])
    return [out[k] for k in sorted(out)]


def load_financials(zip_path: Path, tipo: str, ano: int, cd_cvm: str | int, consolidado: bool = True) -> list[dict]:
    """Atalho: le as 5 demonstracoes do zip anual e extrai para uma empresa."""
    doc = tipo.lower()
    st = {}
    for dem in ("BPA", "BPP", "DRE", "DFC_MI", "DVA"):
        try:
            st[dem] = read_statement(zip_path, doc, dem, ano, consolidado)
        except FileNotFoundError:
            st[dem] = None
    return extract_financials(st, cd_cvm, tipo.upper())


# ---------------------------------------------------------------------------
# IPE — documentos eventuais (Fato Relevante, Comunicado ao Mercado, participacao relevante...)
# ---------------------------------------------------------------------------

IPE_PADROES = {
    "participacao_relevante": re.compile(r"particip\w*\s+(?:acion\w*\s+)?relevante|art\.?\s*12", re.I),
    "insiders_art11":         re.compile(r"art\.?\s*11|valores mobili\w+ negociados", re.I),
    "fato_relevante":         re.compile(r"fato relevante", re.I),
    "assembleia":             re.compile(r"assembl|AGE|AGO|AGOE|boletim de voto|mapa", re.I),
    "debenturistas":          re.compile(r"debentur", re.I),
    "recuperacao":            re.compile(r"recupera\w+ (?:judicial|extrajudicial)|RJ\b|REJ\b", re.I),
    "reducao_capital":        re.compile(r"redu\w+ de capital", re.I),
    "opa":                    re.compile(r"\bOPA\b|oferta p\w+blica", re.I),
}


def _find_col(df: pd.DataFrame, *candidates: str) -> str | None:
    cols = {c.lower(): c for c in df.columns}
    for cand in candidates:
        for low, orig in cols.items():
            if cand.lower() in low:
                return orig
    return None


def ipe_filter(df: pd.DataFrame, cd_cvm: str | int | None = None, padroes: list[str] | None = None) -> pd.DataFrame:
    """
    Filtra a tabela IPE por empresa e por padroes (chaves de IPE_PADROES) casados contra
    Categoria + Tipo + Especie + Assunto. Nomes de coluna sao localizados por substring para
    tolerar mudancas de rotulo entre anos.
    """
    col_cd = _find_col(df, "codigo_cvm", "cd_cvm")
    col_txt = [c for c in (_find_col(df, "categoria"), _find_col(df, "tipo"), _find_col(df, "especie"), _find_col(df, "assunto")) if c]
    d = df
    if cd_cvm is not None and col_cd:
        d = d[d[col_cd].map(_norm_cd) == _norm_cd(cd_cvm)]
    if padroes:
        texto = d[col_txt].astype(str).agg(" | ".join, axis=1) if col_txt else pd.Series("", index=d.index)
        mask = pd.Series(False, index=d.index)
        for p in padroes:
            mask |= texto.str.contains(IPE_PADROES[p], regex=True)
        d = d[mask]
    return d
