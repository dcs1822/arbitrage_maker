"""
arbmaker.sources.rad_collect — coleta TODOS os documentos publicos de uma empresa na CVM.

Fonte do indice: portal de dados abertos (IPE anual: todos os documentos eventuais com link para o
PDF no RAD). Fonte dos PDFs: www.rad.cvm.gov.br (link do indice). Fonte dos financeiros: DFP/ITR em
CSV (cvm_open_data), sem LLM.

Saida por empresa (mesmo layout que data/westwing/):
    data/<slug>/index.csv                       indice IPE (todas as categorias)
    data/<slug>/documents/<data>_<cat>_<hash>.pdf
    data/<slug>/texts/<mesmo nome>.txt          (se PyMuPDF instalado)
    data/<slug>/structured/financials_timeline.json   (DFP + ITR via CSV oficial)
    data/<slug>/collect_report.json

Uso:
    python -m arbmaker.sources.rad_collect --empresas westwing getninjas viveo energisa raizen
    python -m arbmaker.sources.rad_collect --empresas raizen --so-index         # so indice, sem PDFs
    python -m arbmaker.sources.rad_collect --empresas viveo --anos 2023 2026 --sem-financeiros

Hosts necessarios: dados.cvm.gov.br e www.rad.cvm.gov.br. Zips ficam em data/cvm_raw/ (gitignored),
entao uma segunda rodada e offline para o indice e os financeiros.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import cvm_open_data as cvm
from ..universe_cases import EMPRESAS, Empresa

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "cvm_raw"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


# ---------------------------------------------------------------------------
# Cadastro: nome -> CD_CVM
# ---------------------------------------------------------------------------

def resolve_cd_cvm(emp: Empresa, cadastro: pd.DataFrame) -> tuple[str, str]:
    """Devolve (cd_cvm, denominacao) pelo regex nome_busca. Prefere registro ATIVO."""
    if emp.cd_cvm:
        col_cd = cvm._find_col(cadastro, "cd_cvm", "codigo_cvm")
        col_nome = cvm._find_col(cadastro, "denom_social", "nome")
        hit = cadastro[cadastro[col_cd].map(cvm._norm_cd) == cvm._norm_cd(emp.cd_cvm)] if col_cd else cadastro.iloc[0:0]
        return emp.cd_cvm, (hit.iloc[0][col_nome] if (len(hit) and col_nome) else emp.nome)
    col_nome = cvm._find_col(cadastro, "denom_social", "nome")
    col_cd = cvm._find_col(cadastro, "cd_cvm", "codigo_cvm")
    col_sit = cvm._find_col(cadastro, "sit")
    if not (col_nome and col_cd):
        raise RuntimeError(f"cadastro sem colunas esperadas: {list(cadastro.columns)[:12]}")
    pat = re.compile(emp.nome_busca)
    nomes = cadastro[col_nome].map(_norm)
    hits = cadastro[nomes.map(lambda n: bool(pat.search(n)))]
    if col_sit is not None and len(hits) > 1:
        ativos = hits[hits[col_sit].map(_norm) == "ATIVO"]
        hits = ativos if len(ativos) else hits
    if len(hits) == 0:
        raise LookupError(f"{emp.slug}: nenhum registro no cadastro casa com /{emp.nome_busca}/")
    if len(hits) > 1:
        opts = "; ".join(f"{r[col_cd]}={r[col_nome]}" for _, r in hits.head(5).iterrows())
        raise LookupError(f"{emp.slug}: regex ambiguo no cadastro ({len(hits)} hits): {opts}. Fixe cd_cvm em universe_cases.py")
    r = hits.iloc[0]
    return cvm._norm_cd(r[col_cd]), str(r[col_nome])


# ---------------------------------------------------------------------------
# IPE: indice de documentos eventuais
# ---------------------------------------------------------------------------

def load_ipe_year(ano: int) -> pd.DataFrame:
    zp = cvm.fetch(cvm.url_ipe(ano), RAW_DIR)
    df = cvm.read_csv_from_zip(zp, "ipe_cia_aberta")
    df.columns = [c.strip().lstrip("﻿") for c in df.columns]
    return df


def build_index(cd_cvm: str, anos: tuple[int, int]) -> pd.DataFrame:
    frames = []
    for ano in range(anos[0], anos[1] + 1):
        try:
            df = load_ipe_year(ano)
        except Exception as e:  # ano futuro ainda sem arquivo, ou rede
            print(f"  [IPE {ano}] indisponivel: {e}")
            continue
        col_cd = cvm._find_col(df, "codigo_cvm", "cd_cvm")
        sel = df[df[col_cd].map(cvm._norm_cd) == cvm._norm_cd(cd_cvm)].copy()
        print(f"  [IPE {ano}] {len(sel)} documentos")
        frames.append(sel)
    if not frames:
        return pd.DataFrame()
    full = pd.concat(frames, ignore_index=True)
    col_dt = cvm._find_col(full, "data_entrega")
    if col_dt:
        full = full.sort_values(col_dt).reset_index(drop=True)
    return full


# ---------------------------------------------------------------------------
# PDFs e texto
# ---------------------------------------------------------------------------

def _pdf_name(row: pd.Series, link: str) -> str:
    h = hashlib.sha1(link.encode()).hexdigest()[:12]
    data = str(row.get("Data_Entrega", ""))[:10].replace("-", "")
    cat = re.sub(r"[^\w]", "_", str(row.get("Categoria", "")))[:20]
    return f"{data}_{cat}_{h}.pdf"


def download_pdf(url: str, dest: Path, timeout: int = 120) -> bool:
    import requests
    if dest.exists() and dest.stat().st_size > 100:
        return True
    try:
        r = requests.get(url, timeout=timeout, stream=True)
        if r.status_code != 200:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        return True
    except Exception as e:
        print(f"    [ERRO] {dest.name}: {e}")
        return False


def extract_text(pdf: Path) -> str | None:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None
    try:
        doc = fitz.open(str(pdf))
        txt = "\n".join(p.get_text() for p in doc)
        doc.close()
        return txt
    except Exception as e:
        return f"[ERRO_EXTRACAO: {e}]"


# ---------------------------------------------------------------------------
# Financeiros (DFP + ITR via CSV)
# ---------------------------------------------------------------------------

def build_financials(cd_cvm: str, anos: tuple[int, int]) -> list[dict]:
    out: list[dict] = []
    for ano in range(anos[0], anos[1] + 1):
        for tipo, url in (("DFP", cvm.url_dfp(ano)), ("ITR", cvm.url_itr(ano))):
            try:
                zp = cvm.fetch(url, RAW_DIR)
                recs = cvm.load_financials(zp, tipo, ano, cd_cvm)
                print(f"  [{tipo} {ano}] {len(recs)} periodos")
                out.extend(recs)
            except Exception as e:
                print(f"  [{tipo} {ano}] indisponivel: {e}")
    # dedup por (tipo, data_referencia), mantendo o ultimo (maior versao ja filtrada no conector)
    seen: dict[tuple, dict] = {}
    for r in out:
        seen[(r["tipo"], r["data_referencia"])] = r
    return [seen[k] for k in sorted(seen, key=lambda k: (k[1], k[0]))]


# ---------------------------------------------------------------------------
# Orquestracao
# ---------------------------------------------------------------------------

def collect(emp: Empresa, anos: tuple[int, int] | None = None, so_index: bool = False,
            sem_financeiros: bool = False, pausa: float = 0.2) -> dict:
    anos = anos or emp.anos
    base = DATA_DIR / emp.slug
    (base / "structured").mkdir(parents=True, exist_ok=True)
    report = {"empresa": emp.slug, "inicio": datetime.now().isoformat(timespec="seconds"), "anos": list(anos)}

    print(f"\n=== {emp.nome} ({emp.slug}) ===")
    cad = cvm.read_cad(cvm.fetch(cvm.url_cad(), RAW_DIR))
    cd_cvm, denom = resolve_cd_cvm(emp, cad)
    report.update({"cd_cvm": cd_cvm, "denominacao": denom})
    print(f"  CD_CVM {cd_cvm} | {denom}")

    idx = build_index(cd_cvm, anos)
    report["docs_indice"] = int(len(idx))
    if len(idx):
        idx.to_csv(base / "index.csv", index=False, sep=";", encoding="utf-8-sig")
        col_cat = cvm._find_col(idx, "categoria")
        report["por_categoria"] = idx[col_cat].value_counts().to_dict() if col_cat else {}

    if not so_index and len(idx):
        col_link = cvm._find_col(idx, "link_download")
        n_pdf = n_txt = 0
        for i, (_, row) in enumerate(idx.iterrows()):
            link = str(row.get(col_link, "") or "")
            if not link:
                continue
            pdf = base / "documents" / _pdf_name(row, link)
            if download_pdf(link, pdf):
                n_pdf += 1
                txt_path = base / "texts" / (pdf.stem + ".txt")
                if not txt_path.exists():
                    txt = extract_text(pdf)
                    if txt is not None:
                        txt_path.parent.mkdir(parents=True, exist_ok=True)
                        txt_path.write_text(txt, encoding="utf-8")
                        n_txt += 1
            if (i + 1) % 25 == 0:
                print(f"  ... {i + 1}/{len(idx)} ({n_pdf} PDFs, {n_txt} textos novos)")
                time.sleep(pausa)
        report.update({"pdfs": n_pdf, "textos_novos": n_txt})

    if not sem_financeiros:
        fin = build_financials(cd_cvm, anos)
        (base / "structured" / "financials_timeline.json").write_text(
            json.dumps(fin, ensure_ascii=False, indent=2), encoding="utf-8")
        report["periodos_financeiros"] = len(fin)

    report["fim"] = datetime.now().isoformat(timespec="seconds")
    (base / "collect_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  relatorio: {base / 'collect_report.json'}")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--empresas", nargs="+", default=list(EMPRESAS), choices=list(EMPRESAS))
    ap.add_argument("--anos", nargs=2, type=int, metavar=("INI", "FIM"))
    ap.add_argument("--so-index", action="store_true", help="nao baixa PDFs")
    ap.add_argument("--sem-financeiros", action="store_true", help="nao baixa DFP/ITR")
    a = ap.parse_args(argv)
    rc = 0
    for slug in a.empresas:
        try:
            collect(EMPRESAS[slug], tuple(a.anos) if a.anos else None, a.so_index, a.sem_financeiros)
        except Exception as e:
            print(f"  [FALHA] {slug}: {e}")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
