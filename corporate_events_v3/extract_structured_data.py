"""
extract_structured_data.py — Extrai dados estruturados dos docs CVM da WestWing.

3 extrações:
  1. Financeiros (ITR/DFP) -> DRE, Balanço, FCF trimestral
  2. Composição acionária (Valores Mobiliários + Declarações)
  3. Estatuto Social (tag along, poison pill, quórum)

Uso:
    python extract_structured_data.py --step financials
    python extract_structured_data.py --step acionario
    python extract_structured_data.py --step estatuto
    python extract_structured_data.py --step all
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(r"C:\Agent\westwing")
INDEX_PATH = BASE_DIR / "index.csv"
TEXTS_DIR = BASE_DIR / "texts"
STRUCTURED_DIR = BASE_DIR / "structured"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


def _call_gemini(prompt: str, model: str = "gemini-2.5-flash") -> str:
    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "temperature": 0.0,
            "max_output_tokens": 4000,
            "response_mime_type": "application/json",
        },
    )
    return response.text or ""


def _parse_json(text: str) -> dict | list:
    text = text.strip()
    if "```" in text:
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```\s*$', '', text)
    # Fix common Gemini JSON issues
    text = re.sub(r':\s*true/false', ': null', text)
    text = re.sub(r':\s*True\b', ': true', text)
    text = re.sub(r':\s*False\b', ': false', text)
    text = re.sub(r':\s*None\b', ': null', text)
    # Remove trailing commas before } or ]
    text = re.sub(r',\s*([}\]])', r'\1', text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'[\[{].*[}\]]', text, re.DOTALL)
        if m:
            try:
                cleaned = re.sub(r',\s*([}\]])', r'\1', m.group())
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass
        return {"raw": text}


def _find_texts_by_category(category_pattern: str) -> list[tuple[str, Path]]:
    """Retorna (data_entrega, text_path) dos docs que casam com o padrão de categoria."""
    import pandas as pd
    import hashlib

    idx = pd.read_csv(INDEX_PATH, sep=";", dtype=str, encoding="utf-8-sig").fillna("")
    matches = idx[idx["Categoria"].str.contains(category_pattern, case=False, na=False)]
    matches = matches.sort_values("Data_Entrega")

    results = []
    for _, row in matches.iterrows():
        link = row.get("Link_Download", "")
        if not link:
            continue
        url_hash = hashlib.sha1(link.encode()).hexdigest()[:12]
        data = row.get("Data_Entrega", "")[:10].replace("-", "")
        candidates = list(TEXTS_DIR.glob(f"{data}_*{url_hash}*.txt"))
        if candidates:
            results.append((row.get("Data_Entrega", "")[:10], candidates[0], row))
    return results


# ---------------------------------------------------------------------------
# Step 1: Financeiros (ITR/DFP)
# ---------------------------------------------------------------------------

FINANCIAL_PROMPT = """\
Voce recebe o texto de um documento financeiro (ITR ou DFP) da empresa WestWing (WEST3).
Extraia os dados financeiros em JSON estruturado.

IMPORTANTE:
- Valores em R$ milhares (como publicado) ou R$ milhoes (indique a unidade)
- Se o dado nao estiver claro, use null
- Extraia tanto o trimestre quanto o acumulado do ano se disponiveis
- Identifique se eh ITR (trimestral) ou DFP (anual)

Retorne JSON:
{{
  "tipo": "ITR|DFP",
  "data_referencia": "YYYY-MM-DD",
  "periodo": "1T21|2T21|3T21|4T21|2021 etc",
  "unidade": "R$ mil|R$ milhoes",
  "dre": {{
    "receita_liquida": null,
    "custo_produtos_vendidos": null,
    "lucro_bruto": null,
    "margem_bruta_pct": null,
    "despesas_operacionais": null,
    "ebitda": null,
    "margem_ebitda_pct": null,
    "resultado_financeiro": null,
    "lucro_liquido": null,
    "margem_liquida_pct": null
  }},
  "balanco": {{
    "caixa_equivalentes": null,
    "aplicacoes_financeiras": null,
    "caixa_total": null,
    "contas_a_receber": null,
    "estoques": null,
    "ativo_total": null,
    "emprestimos_cp": null,
    "emprestimos_lp": null,
    "divida_bruta": null,
    "patrimonio_liquido": null,
    "divida_liquida": null
  }},
  "fluxo_caixa": {{
    "caixa_operacional": null,
    "capex": null,
    "fcf": null
  }},
  "indicadores": {{
    "acoes_circulacao": null,
    "lpa": null,
    "vpa": null
  }}
}}

CATEGORIA CVM: {categoria}
ESPECIE: {especie}
ASSUNTO: {assunto}
DATA ENTREGA: {data_entrega}
DATA REFERENCIA: {data_referencia}

TEXTO:
{texto}
"""


def step_financials():
    """Extrai dados financeiros estruturados dos ITR/DFP."""
    out_dir = STRUCTURED_DIR / "financials"
    out_dir.mkdir(parents=True, exist_ok=True)

    docs = _find_texts_by_category("Econ.mico-Financeiro")
    print(f"  {len(docs)} documentos financeiros encontrados")

    results = []
    for data_entrega, text_path, row in docs:
        out_file = out_dir / f"{text_path.stem}.json"
        if out_file.exists():
            results.append(json.loads(out_file.read_text(encoding="utf-8")))
            continue

        text = text_path.read_text(encoding="utf-8")
        if len(text) < 200:
            continue

        print(f"  [LLM] {data_entrega} | {row.get('Especie', '')[:40]} | {row.get('Assunto', '')[:40]}...", end=" ", flush=True)

        prompt = FINANCIAL_PROMPT.format(
            categoria=row.get("Categoria", ""),
            especie=row.get("Especie", ""),
            assunto=row.get("Assunto", ""),
            data_entrega=data_entrega,
            data_referencia=row.get("Data_Referencia", ""),
            texto=text[:25000],
        )

        try:
            response = _call_gemini(prompt)
            parsed = _parse_json(response)
            parsed["source_file"] = text_path.name
            parsed["data_entrega"] = data_entrega
            out_file.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")
            results.append(parsed)

            periodo = parsed.get("periodo", "?")
            caixa = parsed.get("balanco", {}).get("caixa_total", "?")
            ll = parsed.get("dre", {}).get("lucro_liquido", "?")
            print(f"OK ({periodo} | caixa={caixa} | LL={ll})")
            time.sleep(0.3)
        except Exception as e:
            print(f"ERRO: {e}")
            time.sleep(2)

    # Consolidar timeline
    timeline = sorted(results, key=lambda x: x.get("data_referencia", "") or x.get("data_entrega", ""))
    consolidated = STRUCTURED_DIR / "financials_timeline.json"
    consolidated.write_text(json.dumps(timeline, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  {len(timeline)} periodos extraidos -> {consolidated}")


# ---------------------------------------------------------------------------
# Step 2: Composição Acionária
# ---------------------------------------------------------------------------

ACIONARIO_PROMPT = """\
Voce recebe um documento da CVM sobre movimentacao acionaria da WestWing (WEST3).
Pode ser uma Declaracao de Aquisicao/Alienacao de Participacao ou um documento de Valores Mobiliarios.

Extraia em JSON:
{{
  "data": "YYYY-MM-DD",
  "tipo_movimentacao": "aquisicao|alienacao|posicao",
  "acionista": "nome do acionista/fundo/gestora",
  "cnpj_cpf": "se disponivel",
  "acoes_antes": null,
  "percentual_antes": null,
  "acoes_depois": null,
  "percentual_depois": null,
  "acoes_movimentadas": null,
  "objetivo": "investimento|controle|hedge|outro",
  "intencao_declarada": "texto da intencao se houver (ex: nao pretende alterar controle)",
  "preco_medio": null,
  "observacoes": "qualquer detalhe relevante"
}}

Se o documento contiver multiplos acionistas ou movimentacoes, retorne uma lista [].

CATEGORIA: {categoria}
ESPECIE: {especie}
DATA ENTREGA: {data_entrega}

TEXTO:
{texto}
"""


def step_acionario():
    """Extrai composição acionária dos docs de valores mobiliários e declarações."""
    out_dir = STRUCTURED_DIR / "acionario"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Valores mobiliários + Comunicados com declaração de aquisição/alienação
    docs_vm = _find_texts_by_category("Valores Mobili")
    docs_decl = _find_texts_by_category("Comunica")

    # Filtrar comunicados que são declarações de aquisição/alienação
    docs_decl_filtered = []
    for data, path, row in docs_decl:
        especie = row.get("Especie", "").lower()
        if "aquisi" in especie or "aliena" in especie or "participa" in especie:
            docs_decl_filtered.append((data, path, row))

    all_docs = docs_vm + docs_decl_filtered
    all_docs.sort(key=lambda x: x[0])
    print(f"  {len(all_docs)} documentos acionarios ({len(docs_vm)} VM + {len(docs_decl_filtered)} declaracoes)")

    results = []
    for data_entrega, text_path, row in all_docs:
        out_file = out_dir / f"{text_path.stem}.json"
        if out_file.exists():
            try:
                data = json.loads(out_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    results.extend(data)
                else:
                    results.append(data)
            except:
                pass
            continue

        text = text_path.read_text(encoding="utf-8")
        if len(text) < 100:
            continue

        print(f"  [LLM] {data_entrega} | {row.get('Especie', '')[:40]}...", end=" ", flush=True)

        prompt = ACIONARIO_PROMPT.format(
            categoria=row.get("Categoria", ""),
            especie=row.get("Especie", ""),
            data_entrega=data_entrega,
            texto=text[:20000],
        )

        try:
            response = _call_gemini(prompt)
            parsed = _parse_json(response)
            out_file.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")

            if isinstance(parsed, list):
                results.extend(parsed)
                names = [p.get("acionista", "?")[:20] for p in parsed[:3]]
                print(f"OK ({len(parsed)} movs: {', '.join(names)})")
            else:
                results.append(parsed)
                print(f"OK ({parsed.get('acionista', '?')[:30]} {parsed.get('percentual_depois', '?')}%)")
            time.sleep(0.3)
        except Exception as e:
            print(f"ERRO: {e}")
            time.sleep(2)

    # Consolidar
    timeline = sorted(results, key=lambda x: x.get("data", "") if isinstance(x, dict) else "")
    consolidated = STRUCTURED_DIR / "acionario_timeline.json"
    consolidated.write_text(json.dumps(timeline, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  {len(timeline)} movimentacoes extraidas -> {consolidated}")


# ---------------------------------------------------------------------------
# Step 3: Estatuto Social
# ---------------------------------------------------------------------------

ESTATUTO_PROMPT = """\
Voce recebe o texto do Estatuto Social da WestWing (WEST3).
Extraia as clausulas relevantes para analise de governanca e eventos corporativos.

Retorne JSON:
{{
  "data_versao": "YYYY-MM-DD",
  "capital_social": {{
    "valor": null,
    "moeda": "BRL",
    "acoes_ordinarias": null,
    "acoes_preferenciais": null,
    "total_acoes": null,
    "capital_autorizado": null
  }},
  "governanca": {{
    "tag_along_on_pct": null,
    "tag_along_pn_pct": null,
    "poison_pill": {{
      "existe": null,
      "trigger_pct": null,
      "descricao": "resumo da clausula ou null"
    }},
    "quorum_assembleia_ordinaria": null,
    "quorum_mudanca_estatuto": null,
    "quorum_reducao_capital": null,
    "voto_multiplo": null,
    "conselho_min_membros": null,
    "conselho_max_membros": null,
    "mandato_conselho_anos": null
  }},
  "direitos_acionistas": {{
    "dividendo_minimo_pct": null,
    "direito_retirada": "descricao se houver",
    "clausula_arbitragem": null
  }},
  "clausulas_especiais": [
    "qualquer clausula relevante para M&A, OPA, fechamento de capital"
  ],
  "observacoes": "pontos relevantes nao cobertos acima"
}}

DATA ENTREGA: {data_entrega}

TEXTO:
{texto}
"""


def step_estatuto():
    """Extrai regras de governança dos estatutos sociais."""
    out_dir = STRUCTURED_DIR / "estatuto"
    out_dir.mkdir(parents=True, exist_ok=True)

    docs = _find_texts_by_category("Estatuto Social")
    print(f"  {len(docs)} estatutos encontrados")

    results = []
    for data_entrega, text_path, row in docs:
        out_file = out_dir / f"{text_path.stem}.json"
        if out_file.exists():
            results.append(json.loads(out_file.read_text(encoding="utf-8")))
            continue

        text = text_path.read_text(encoding="utf-8")
        if len(text) < 200:
            continue

        print(f"  [LLM] {data_entrega} | Estatuto Social...", end=" ", flush=True)

        prompt = ESTATUTO_PROMPT.format(
            data_entrega=data_entrega,
            texto=text[:30000],
        )

        try:
            response = _call_gemini(prompt)
            parsed = _parse_json(response)
            parsed["source_file"] = text_path.name
            parsed["data_entrega"] = data_entrega
            out_file.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")
            results.append(parsed)

            pp = parsed.get("governanca", {}).get("poison_pill", {})
            ta = parsed.get("governanca", {}).get("tag_along_on_pct", "?")
            print(f"OK (tag_along={ta}% | poison_pill={pp.get('existe', '?')})")
            time.sleep(0.5)
        except Exception as e:
            print(f"ERRO: {e}")
            time.sleep(2)

    # Salvar o estatuto mais recente como "vigente"
    if results:
        vigente = STRUCTURED_DIR / "estatuto_vigente.json"
        vigente.write_text(json.dumps(results[-1], indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n  Estatuto vigente salvo -> {vigente}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", default="all", choices=["financials", "acionario", "estatuto", "all"])
    args = parser.parse_args()

    STRUCTURED_DIR.mkdir(parents=True, exist_ok=True)

    steps = {
        "financials": step_financials,
        "acionario": step_acionario,
        "estatuto": step_estatuto,
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
