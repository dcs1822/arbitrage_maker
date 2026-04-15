"""
backtest_westwing.py — Coleta completa + backtest do agente para WestWing (WEST3).

Etapas:
  1. Baixa todos os docs CVM (2020-2026) e extrai texto
  2. Extrai dados financeiros (ITR/DFP) via regex
  3. Extrai contexto de governança/acionário via LLM
  4. Constrói snapshot evolutivo trimestral
  5. Roda backtest cronológico

Uso:
    python backtest_westwing.py --step collect
    python backtest_westwing.py --step financials
    python backtest_westwing.py --step context
    python backtest_westwing.py --step snapshot
    python backtest_westwing.py --step backtest
    python backtest_westwing.py --step all
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
import zipfile
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CD_CVM = "25518"
COMPANY_NAME = "WESTWING"
TICKER = "WEST3"
YEARS = list(range(2020, 2027))

BASE_DIR = Path(r"C:\Agent\westwing")
PDF_DIR = BASE_DIR / "documents"
INDEX_PATH = BASE_DIR / "index.csv"
TEXTS_DIR = BASE_DIR / "texts"
FINANCIALS_PATH = BASE_DIR / "financials.json"
CONTEXT_DIR = BASE_DIR / "context"
SNAPSHOTS_PATH = BASE_DIR / "snapshots.json"
BACKTEST_DIR = BASE_DIR / "backtest"

# LLM
import os
sys.path.insert(0, str(Path(__file__).parent))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Categorias que queremos processar e como
CATEGORY_TIERS = {
    # Tier 1: LLM obrigatório — eventos materiais
    "Fato Relevante": "llm",
    "Comunicado ao Mercado": "llm",
    "Aviso aos Acionistas": "llm",
    "Documentos de Oferta de Distribuição Pública": "llm",
    "Acordo de Acionistas": "llm",
    # Tier 2: Processamento estruturado (regex/tabelas)
    "Dados Econômico-Financeiros": "structured",
    "Valores Mobiliários negociados e detidos (art. 11 da Instr. CVM nº 358)": "structured",
    # Tier 3: Lê 1x para contexto base
    "Estatuto Social": "llm",
    # Tier 4: Pula (muito ruído)
    "Assembleia": "skip_unless_keyword",
    "Reunião da Administração": "skip",
    "Calendário de Eventos Corporativos": "skip",
    "Código de Conduta": "skip",
    "Política de Gerenciamento de Riscos": "skip",
    "Regimento interno do Conselho de Administração": "skip",
    "Regimento interno de Comitês": "skip",
    "Regimento interno do Conselho Fiscal": "skip",
    "Política de Remuneração": "skip",
    "Política de Negociação de Valores Mobiliários": "skip",
    "Política de Divulgação de Ato ou Fato Relevante": "skip",
    "Política de Transações entre Partes Relacionadas": "skip",
    "Política de indicação": "skip",
}

# Keywords que fazem assembleias serem processadas
ASSEMBLY_KEYWORDS = [
    "redução de capital", "reducao de capital", "incorporação", "incorporacao",
    "cisão", "cisao", "OPA", "oferta pública", "fechamento de capital",
    "voto múltiplo", "voto multiplo", "poison pill", "tag along",
    "mudança de controle", "alienação de controle",
]


# ---------------------------------------------------------------------------
# Step 1: Coleta CVM
# ---------------------------------------------------------------------------

def _download_cvm_year(year: int) -> pd.DataFrame:
    """Baixa CSV do IPE CVM para um ano."""
    url = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{year}.zip"
    r = requests.get(url, timeout=180)
    if r.status_code != 200:
        print(f"  [WARN] {year}: HTTP {r.status_code}")
        return pd.DataFrame()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for csv_name in z.namelist():
            if csv_name.endswith(".csv"):
                for enc in ("utf-8-sig", "latin1", "cp1252"):
                    try:
                        df = pd.read_csv(z.open(csv_name), sep=";", dtype=str, encoding=enc, on_bad_lines="skip")
                        df.columns = [c.strip() for c in df.columns]
                        return df.fillna("")
                    except Exception:
                        continue
    return pd.DataFrame()


def _download_pdf(url: str, dest: Path) -> bool:
    """Baixa PDF se não existe no cache."""
    if dest.exists() and dest.stat().st_size > 100:
        return True
    try:
        r = requests.get(url, timeout=60, stream=True)
        if r.status_code == 200:
            dest.write_bytes(r.content)
            return True
    except Exception as e:
        print(f"    [ERRO] download: {e}")
    return False


def _extract_text(pdf_path: Path) -> str:
    """Extrai texto de PDF via PyMuPDF."""
    try:
        doc = fitz.open(str(pdf_path))
        pages = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(pages)
    except Exception as e:
        return f"[ERRO_EXTRACAO: {e}]"


def step_collect():
    """Baixa todos os docs CVM da WestWing, PDFs e textos."""
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    TEXTS_DIR.mkdir(parents=True, exist_ok=True)

    all_docs = []
    for year in YEARS:
        print(f"  [{year}] Baixando index CVM...", end=" ", flush=True)
        df = _download_cvm_year(year)
        if df.empty:
            print("vazio")
            continue
        west = df[df["Codigo_CVM"].astype(str).str.strip() == CD_CVM].copy()
        print(f"{len(west)} docs")
        all_docs.append(west)

    if not all_docs:
        print("[ERRO] Nenhum documento encontrado.")
        return

    full = pd.concat(all_docs, ignore_index=True)
    full.to_csv(INDEX_PATH, index=False, sep=";", encoding="utf-8-sig")
    print(f"\n  Index salvo: {len(full)} docs em {INDEX_PATH}")

    # Baixar PDFs e extrair texto
    downloaded = 0
    extracted = 0
    for i, (_, row) in enumerate(full.iterrows()):
        link = row.get("Link_Download", "") or row.get("Link_Download", "")
        if not link:
            continue

        # Nome determinístico
        url_hash = hashlib.sha1(link.encode()).hexdigest()[:12]
        data = row.get("Data_Entrega", "")[:10].replace("-", "")
        cat_short = re.sub(r'[^\w]', '_', row.get("Categoria", ""))[:20]
        pdf_name = f"{data}_{cat_short}_{url_hash}.pdf"
        pdf_path = PDF_DIR / pdf_name

        if _download_pdf(link, pdf_path):
            downloaded += 1

            # Extrair texto
            text_path = TEXTS_DIR / f"{pdf_path.stem}.txt"
            if not text_path.exists():
                text = _extract_text(pdf_path)
                text_path.write_text(text, encoding="utf-8")
                extracted += 1

        if (i + 1) % 50 == 0:
            print(f"  ... {i+1}/{len(full)} ({downloaded} PDFs, {extracted} textos novos)")
            time.sleep(0.1)

    print(f"\n  Concluído: {downloaded} PDFs, {extracted} textos extraídos")


# ---------------------------------------------------------------------------
# Step 2: Extrair dados financeiros (regex, sem LLM)
# ---------------------------------------------------------------------------

def step_financials():
    """Extrai dados financeiros dos docs de Dados Econômico-Financeiros."""
    if not INDEX_PATH.exists():
        print("[ERRO] Rode --step collect primeiro")
        return

    idx = pd.read_csv(INDEX_PATH, sep=";", dtype=str, encoding="utf-8-sig").fillna("")

    # Filtrar DFs
    fin_docs = idx[idx["Categoria"].str.contains("Econ.mico-Financeiro", case=False, na=False)]
    print(f"  {len(fin_docs)} documentos financeiros encontrados")

    financials = []
    for _, row in fin_docs.sort_values("Data_Entrega").iterrows():
        link = row.get("Link_Download", "")
        url_hash = hashlib.sha1(link.encode()).hexdigest()[:12]
        data = row.get("Data_Entrega", "")[:10].replace("-", "")
        text_path = TEXTS_DIR / f"{data}_Dados_Econ.mico-Fin_{url_hash}.txt"

        # Tentar encontrar o arquivo de texto correto
        if not text_path.exists():
            candidates = list(TEXTS_DIR.glob(f"{data}_Dados*{url_hash}*.txt"))
            if candidates:
                text_path = candidates[0]
            else:
                continue

        text = text_path.read_text(encoding="utf-8")

        # Extrair valores via regex
        data_ref = row.get("Data_Referencia", "")[:10]
        assunto = row.get("Assunto", "")
        especie = row.get("Especie", "")

        entry = {
            "data_entrega": row.get("Data_Entrega", "")[:10],
            "data_referencia": data_ref,
            "assunto": assunto,
            "especie": especie,
            "source_file": text_path.name,
        }

        # Buscar padrões financeiros comuns no texto
        patterns = {
            "receita_liquida": r"[Rr]eceita\s+[Ll]íquida.*?R\$\s*([\d.,]+)",
            "lucro_liquido": r"[Ll]ucro\s+[Ll]íquido.*?R\$\s*([\d.,]+)",
            "prejuizo": r"[Pp]reju[ií]zo.*?R\$\s*([\d.,]+)",
            "ebitda": r"EBITDA.*?R\$\s*([\d.,]+)",
            "caixa": r"[Cc]aixa.*?R\$\s*([\d.,]+)",
            "divida": r"[Dd][ií]vida.*?R\$\s*([\d.,]+)",
            "patrimonio_liquido": r"[Pp]atrim[oô]nio\s+[Ll]íquido.*?R\$\s*([\d.,]+)",
        }
        for key, pattern in patterns.items():
            m = re.search(pattern, text)
            if m:
                entry[key] = m.group(1)

        financials.append(entry)

    FINANCIALS_PATH.write_text(
        json.dumps(financials, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  {len(financials)} registros financeiros extraídos -> {FINANCIALS_PATH}")


# ---------------------------------------------------------------------------
# Step 3: Extrair contexto via LLM (fatos relevantes, comunicados, estatuto)
# ---------------------------------------------------------------------------

def _call_gemini(prompt: str, model: str = "gemini-2.5-flash") -> str:
    """Chama Gemini API."""
    from google import genai

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "temperature": 0.1,
            "max_output_tokens": 2000,
            "response_mime_type": "application/json",
        },
    )
    return response.text or ""


CONTEXT_EXTRACTION_PROMPT = """\
Voce recebe um documento corporativo da empresa WestWing (WEST3), listada na B3.
Extraia as informacoes relevantes em JSON com os campos abaixo.
Se a informacao nao estiver no texto, use null.

Campos:
{{
  "tipo": "fato_relevante|comunicado|aviso|estatuto|oferta|acordo_acionistas",
  "data": "YYYY-MM-DD",
  "resumo": "1-2 frases com o ponto principal",
  "impacto_financeiro": "se menciona valores, caixa, capital, etc",
  "impacto_governanca": "mudancas no CA, diretoria, controle, voto",
  "impacto_acionario": "compra/venda de acoes, participacao relevante, OPA",
  "flags": ["lista de flags: reducao_capital, opa, mudanca_controle, cash_gt_mc, ativismo, grupamento, cisao, incorporacao, deslistagem, reapresentacao_df, renunciadiretoria, aquisicao, alienacao_participacao"],
  "severidade": 1-10,
  "dados_extraidos": {{chave: valor}}
}}

Categoria CVM: {categoria}
Especie: {especie}
Assunto: {assunto}
Data entrega: {data_entrega}

TEXTO DO DOCUMENTO:
{texto}
"""


def _should_process(categoria: str, text: str) -> str:
    """Decide se/como processar baseado na categoria."""
    # Normalizar encoding
    for orig, repl in [("ã", "a"), ("ç", "c"), ("õ", "o"), ("é", "e"), ("í", "i"), ("ú", "u"), ("ô", "o"), ("â", "a")]:
        categoria = categoria.replace(orig, repl)

    for cat_key, tier in CATEGORY_TIERS.items():
        cat_normalized = cat_key
        for orig, repl in [("ã", "a"), ("ç", "c"), ("õ", "o"), ("é", "e"), ("í", "i"), ("ú", "u"), ("ô", "o"), ("â", "a")]:
            cat_normalized = cat_normalized.replace(orig, repl)
        if cat_normalized.lower() in categoria.lower() or categoria.lower() in cat_normalized.lower():
            if tier == "skip_unless_keyword":
                text_lower = text.lower()
                if any(kw in text_lower for kw in ASSEMBLY_KEYWORDS):
                    return "llm"
                return "skip"
            return tier
    return "skip"


def step_context():
    """Extrai contexto dos documentos relevantes via LLM."""
    if not INDEX_PATH.exists():
        print("[ERRO] Rode --step collect primeiro")
        return

    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)

    idx = pd.read_csv(INDEX_PATH, sep=";", dtype=str, encoding="utf-8-sig").fillna("")
    idx = idx.sort_values("Data_Entrega")

    processed = 0
    skipped = 0
    errors = 0

    for _, row in idx.iterrows():
        link = row.get("Link_Download", "")
        if not link:
            continue

        url_hash = hashlib.sha1(link.encode()).hexdigest()[:12]
        data = row.get("Data_Entrega", "")[:10].replace("-", "")
        categoria = row.get("Categoria", "")

        # Encontrar arquivo de texto
        candidates = list(TEXTS_DIR.glob(f"{data}_*{url_hash}*.txt"))
        if not candidates:
            continue
        text_path = candidates[0]

        # Já processado?
        context_path = CONTEXT_DIR / f"{text_path.stem}.json"
        if context_path.exists():
            processed += 1
            continue

        text = text_path.read_text(encoding="utf-8")
        tier = _should_process(categoria, text)

        if tier == "skip":
            skipped += 1
            continue

        if tier == "structured":
            # Valores mobiliários — extrair de forma estruturada
            entry = {
                "tipo": "movimentacao_acionaria" if "Valores" in categoria else "dados_financeiros",
                "data": row.get("Data_Entrega", "")[:10],
                "categoria": categoria,
                "assunto": row.get("Assunto", ""),
                "especie": row.get("Especie", ""),
                "texto_preview": text[:500],
                "source_file": text_path.name,
            }
            context_path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")
            processed += 1
            continue

        # tier == "llm"
        print(f"  [LLM] {row.get('Data_Entrega', '')[:10]} | {categoria[:30]} | {row.get('Assunto', '')[:50]}...", end=" ", flush=True)

        prompt = CONTEXT_EXTRACTION_PROMPT.format(
            categoria=categoria,
            especie=row.get("Especie", ""),
            assunto=row.get("Assunto", ""),
            data_entrega=row.get("Data_Entrega", "")[:10],
            texto=text[:25000],
        )

        try:
            response = _call_gemini(prompt)
            # Parse JSON
            try:
                parsed = json.loads(response)
            except json.JSONDecodeError:
                # Tentar extrair JSON do texto
                m = re.search(r"\{.*\}", response, re.DOTALL)
                if m:
                    parsed = json.loads(m.group())
                else:
                    parsed = {"raw_response": response}

            parsed["source_file"] = text_path.name
            parsed["categoria_cvm"] = categoria
            context_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"OK (sev={parsed.get('severidade', '?')})")
            processed += 1
            time.sleep(0.3)  # Rate limiting
        except Exception as e:
            print(f"ERRO: {e}")
            errors += 1
            time.sleep(2)

    print(f"\n  Concluído: {processed} processados, {skipped} pulados, {errors} erros")


# ---------------------------------------------------------------------------
# Step 4: Construir snapshot evolutivo
# ---------------------------------------------------------------------------

def step_snapshot():
    """Constrói snapshots trimestrais a partir dos contextos extraídos."""
    if not CONTEXT_DIR.exists():
        print("[ERRO] Rode --step context primeiro")
        return

    contexts = []
    for f in sorted(CONTEXT_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            contexts.append(data)
        except Exception:
            continue

    # Ordenar por data
    contexts.sort(key=lambda c: c.get("data", "") or c.get("data_entrega", "") or "")

    # Construir snapshots trimestrais
    snapshots = {}
    current_snapshot = {
        "empresa": COMPANY_NAME,
        "ticker": TICKER,
        "cd_cvm": CD_CVM,
        "financeiro": {},
        "governanca": {},
        "acionario": {},
        "flags_ativas": [],
        "eventos_recentes": [],
        "teses": [],
    }

    for ctx in contexts:
        data = ctx.get("data", "") or ctx.get("data_entrega", "")
        if not data or len(data) < 7:
            continue

        quarter = f"{data[:4]}Q{(int(data[5:7])-1)//3 + 1}"

        # Atualizar snapshot com informações do contexto
        if ctx.get("impacto_financeiro"):
            current_snapshot["financeiro"][data] = ctx["impacto_financeiro"]
        if ctx.get("impacto_governanca"):
            current_snapshot["governanca"][data] = ctx["impacto_governanca"]
        if ctx.get("impacto_acionario"):
            current_snapshot["acionario"][data] = ctx["impacto_acionario"]
        if ctx.get("dados_extraidos"):
            current_snapshot["financeiro"].update(ctx["dados_extraidos"])

        # Acumular flags
        for flag in ctx.get("flags", []):
            if flag and flag not in current_snapshot["flags_ativas"]:
                current_snapshot["flags_ativas"].append(flag)

        # Manter últimos 5 eventos no snapshot
        resumo = ctx.get("resumo", "")
        if resumo:
            current_snapshot["eventos_recentes"].append({
                "data": data,
                "resumo": resumo,
                "severidade": ctx.get("severidade", 1),
                "tipo": ctx.get("tipo", ""),
            })
            current_snapshot["eventos_recentes"] = current_snapshot["eventos_recentes"][-5:]

        # Salvar snapshot do trimestre
        import copy
        snapshots[quarter] = copy.deepcopy(current_snapshot)

    SNAPSHOTS_PATH.write_text(
        json.dumps(snapshots, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  {len(snapshots)} snapshots trimestrais gerados -> {SNAPSHOTS_PATH}")

    # Resumo
    for q, snap in sorted(snapshots.items()):
        flags = ", ".join(snap["flags_ativas"]) or "nenhuma"
        n_eventos = len(snap["eventos_recentes"])
        print(f"  {q}: {n_eventos} eventos recentes | flags: {flags}")


# ---------------------------------------------------------------------------
# Step 5: Backtest cronológico
# ---------------------------------------------------------------------------

BACKTEST_PROMPT = """\
Voce eh um analista de equity especializado em eventos corporativos e arbitragens.
Voce monitora documentos da CVM para identificar oportunidades de investimento.

## CONTEXTO DA EMPRESA (snapshot atualizado ate o momento):
{snapshot}

## NOVO DOCUMENTO PUBLICADO:
Data: {data}
Categoria: {categoria}
Assunto: {assunto}

{texto}

## INSTRUCOES:
Analise este documento considerando o contexto acumulado da empresa.
Responda em JSON:
{{
  "acao_recomendada": "investigar|monitorar|ignorar",
  "severidade": 1-10,
  "tipo_oportunidade": "arbitragem|evento_corporativo|governanca|nenhum",
  "resumo": "1-2 frases",
  "justificativa": "por que isso eh relevante dado o contexto (cite dados especificos)",
  "flags_detectadas": ["lista"],
  "proximo_passo": "o que o analista deveria fazer agora",
  "confianca": "alta|media|baixa"
}}
"""


def step_backtest():
    """Roda o agente cronologicamente sobre os eventos da WestWing."""
    if not SNAPSHOTS_PATH.exists():
        print("[ERRO] Rode --step snapshot primeiro")
        return

    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)

    snapshots = json.loads(SNAPSHOTS_PATH.read_text(encoding="utf-8"))
    idx = pd.read_csv(INDEX_PATH, sep=";", dtype=str, encoding="utf-8-sig").fillna("")
    idx = idx.sort_values("Data_Entrega")

    # Filtrar só documentos que passaram por LLM context (fatos relevantes, comunicados, etc.)
    results = []
    processed = 0

    for _, row in idx.iterrows():
        link = row.get("Link_Download", "")
        if not link:
            continue

        categoria = row.get("Categoria", "")
        url_hash = hashlib.sha1(link.encode()).hexdigest()[:12]
        data = row.get("Data_Entrega", "")[:10]
        data_compact = data.replace("-", "")

        # Encontrar contexto extraído
        candidates = list(CONTEXT_DIR.glob(f"{data_compact}_*{url_hash}*.json"))
        if not candidates:
            continue

        ctx = json.loads(candidates[0].read_text(encoding="utf-8"))

        # Pular documentos de baixa severidade
        sev = ctx.get("severidade", 0)
        if isinstance(sev, str):
            try:
                sev = int(sev)
            except ValueError:
                sev = 0
        if sev < 3 and ctx.get("tipo") not in ("estatuto", "acordo_acionistas"):
            continue

        # Encontrar snapshot mais recente
        quarter = f"{data[:4]}Q{(int(data[5:7])-1)//3 + 1}"
        # Pegar snapshot do trimestre anterior (o agente não teria o snapshot futuro)
        sorted_quarters = sorted(snapshots.keys())
        prev_quarter = ""
        for q in sorted_quarters:
            if q < quarter:
                prev_quarter = q
        snapshot_text = json.dumps(snapshots.get(prev_quarter, {}), indent=2, ensure_ascii=False) if prev_quarter else "{}"

        # Encontrar texto original
        text_candidates = list(TEXTS_DIR.glob(f"{data_compact}_*{url_hash}*.txt"))
        if not text_candidates:
            continue
        texto = text_candidates[0].read_text(encoding="utf-8")[:15000]

        print(f"  [BACKTEST] {data} | {categoria[:30]} | sev={sev}...", end=" ", flush=True)

        prompt = BACKTEST_PROMPT.format(
            snapshot=snapshot_text,
            data=data,
            categoria=categoria,
            assunto=row.get("Assunto", ""),
            texto=texto,
        )

        try:
            response = _call_gemini(prompt, model="gemini-2.5-pro")
            try:
                parsed = json.loads(response)
            except json.JSONDecodeError:
                m = re.search(r"\{.*\}", response, re.DOTALL)
                parsed = json.loads(m.group()) if m else {"raw": response}

            parsed["input_data"] = data
            parsed["input_categoria"] = categoria
            parsed["input_assunto"] = row.get("Assunto", "")
            parsed["input_severidade_triage"] = sev
            results.append(parsed)

            acao = parsed.get("acao_recomendada", "?")
            sev_bt = parsed.get("severidade", "?")
            print(f"{acao} (sev={sev_bt})")
            processed += 1

            time.sleep(1)  # Gemini Pro rate limit
        except Exception as e:
            print(f"ERRO: {e}")
            time.sleep(3)

    # Salvar resultados
    output = BACKTEST_DIR / "results.json"
    output.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  {processed} eventos analisados -> {output}")

    # Resumo
    print(f"\n{'='*60}")
    print(f"RESULTADO DO BACKTEST — {COMPANY_NAME} ({TICKER})")
    print(f"{'='*60}")
    investigar = [r for r in results if r.get("acao_recomendada") == "investigar"]
    monitorar = [r for r in results if r.get("acao_recomendada") == "monitorar"]
    print(f"  Investigar: {len(investigar)}")
    print(f"  Monitorar:  {len(monitorar)}")
    print(f"  Ignorar:    {len(results) - len(investigar) - len(monitorar)}")

    if investigar:
        print(f"\n  TOP ALERTAS (ação = investigar):")
        for r in sorted(investigar, key=lambda x: x.get("severidade", 0), reverse=True):
            print(f"    {r['input_data']} | sev={r.get('severidade')} | {r.get('resumo', '')[:80]}")
            print(f"      -> {r.get('justificativa', '')[:100]}")
            print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Backtest WestWing corporate events agent")
    parser.add_argument("--step", default="all",
                        choices=["collect", "financials", "context", "snapshot", "backtest", "all"])
    args = parser.parse_args()

    steps = {
        "collect": step_collect,
        "financials": step_financials,
        "context": step_context,
        "snapshot": step_snapshot,
        "backtest": step_backtest,
    }

    if args.step == "all":
        for name, fn in steps.items():
            print(f"\n{'='*60}")
            print(f"  STEP: {name.upper()}")
            print(f"{'='*60}")
            fn()
    else:
        steps[args.step]()


if __name__ == "__main__":
    main()
