"""
backtest_integrated.py — Backtest integrado: Eventos CVM + Tese do Agente de Avaliacao.

Cada evento CVM eh avaliado contra a tese de investimento vigente no trimestre,
produzindo alertas ricos com contexto de valuation, governanca e proximos passos.

Uso:
    python backtest_integrated.py                    # roda tudo
    python backtest_integrated.py --only-high        # so eventos sev >= 5
    python backtest_integrated.py --quarter 2023Q3   # so um trimestre
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(r"C:\Agent\westwing")
INDEX_PATH = BASE_DIR / "index.csv"
TEXTS_DIR = BASE_DIR / "texts"
CONTEXT_DIR = BASE_DIR / "context"
THESIS_DIR = BASE_DIR / "thesis"
OUTPUT_DIR = BASE_DIR / "backtest_integrated"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Datas das teses disponiveis (geradas pelo agente_avaliacao.py)
THESIS_DATES = [
    "2021-06-30", "2021-12-31",
    "2022-06-30", "2022-12-31",
    "2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31",
    "2024-06-30", "2024-12-31",
    "2025-06-30", "2025-12-31",
    "2026-03-31",
]


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

def _call_gemini(prompt: str, model: str = "gemini-2.5-flash") -> str:
    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY)

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "temperature": 0.1,
                    "max_output_tokens": 4000,
                    "response_mime_type": "application/json",
                },
            )
            return response.text or ""
        except Exception as e:
            if "503" in str(e) or "429" in str(e):
                wait = (attempt + 1) * 8
                print(f"  [RETRY] {e} -- aguardando {wait}s...", flush=True)
                time.sleep(wait)
            else:
                raise
    return ""


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```\s*$', '', text)
    text = re.sub(r',\s*([}\]])', r'\1', text)
    text = re.sub(r':\s*True\b', ': true', text)
    text = re.sub(r':\s*False\b', ': false', text)
    text = re.sub(r':\s*None\b', ': null', text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try:
                return json.loads(re.sub(r',\s*([}\]])', r'\1', m.group()))
            except:
                pass
        return {"raw": text}


# ---------------------------------------------------------------------------
# Thesis loading
# ---------------------------------------------------------------------------

def _load_thesis(as_of_date: str) -> dict | None:
    """Carrega a tese vigente para uma data.
    Usa a tese mais recente anterior ou igual a data do evento."""
    best = None
    for td in THESIS_DATES:
        if td <= as_of_date:
            best = td
    if best is None:
        return None
    path = THESIS_DIR / f"thesis_{best}.json"
    if not path.exists():
        return None
    thesis = json.loads(path.read_text(encoding="utf-8"))
    thesis["_thesis_date"] = best
    return thesis


def _format_thesis_context(thesis: dict) -> str:
    """Formata a tese vigente como contexto textual para o prompt."""
    lines = []
    lines.append(f"Data da tese: {thesis.get('data_avaliacao', thesis.get('_thesis_date', '?'))}")
    lines.append(f"Recomendacao vigente: {thesis.get('recomendacao', '?').upper()}")
    lines.append(f"Confianca: {thesis.get('confianca', '?')}")
    lines.append(f"Tese resumo: {thesis.get('tese_resumo', '')}")
    lines.append("")

    # Valuation
    val = thesis.get("valuation", {})
    if val:
        lines.append("VALUATION:")
        lines.append(f"  Market Cap: R${val.get('market_cap_mm', '?')}M")
        lines.append(f"  Caixa liquido: R${val.get('caixa_liquido_mm', '?')}M")
        desconto = val.get("desconto_sobre_caixa_pct")
        if desconto:
            lines.append(f"  Desconto sobre caixa: {desconto}%")
        lines.append(f"  P/PL: {val.get('preco_sobre_pl', '?')}x")
        if val.get("ev_ebitda"):
            lines.append(f"  EV/EBITDA: {val['ev_ebitda']}x")
        if val.get("observacao_valuation"):
            lines.append(f"  Obs: {val['observacao_valuation']}")
        lines.append("")

    # Bull/Bear
    bull = thesis.get("tese_bull", {})
    if bull:
        lines.append(f"BULL CASE (prob {bull.get('probabilidade_estimada', '?')}%):")
        lines.append(f"  {bull.get('resumo', '')}")
        lines.append(f"  Target: R${bull.get('target_price', '?')} (upside {bull.get('upside_pct', '?')}%)")
        for c in (bull.get("catalalisadores") or []):
            lines.append(f"    - {c}")
        lines.append("")

    bear = thesis.get("tese_bear", {})
    if bear:
        lines.append(f"BEAR CASE (prob {bear.get('probabilidade_estimada', '?')}%):")
        lines.append(f"  {bear.get('resumo', '')}")
        for r in (bear.get("riscos") or []):
            lines.append(f"    - {r}")
        lines.append("")

    # Governanca
    gov = thesis.get("governanca", {})
    if gov:
        lines.append(f"GOVERNANCA (score {gov.get('score', '?')}/10):")
        lines.append(f"  Rotatividade mgmt: {gov.get('rotatividade_management', '?')}")
        lines.append(f"  Risco ativismo: {gov.get('risco_ativismo', '?')}")
        for rf in (gov.get("red_flags") or []):
            lines.append(f"    ! {rf}")
        lines.append("")

    # Triggers
    triggers = thesis.get("triggers", [])
    if triggers:
        lines.append("TRIGGERS MAPEADOS:")
        for t in triggers:
            dir_sym = "+" if t.get("direcao") == "positivo" else "-"
            lines.append(f"  [{dir_sym}] {t.get('trigger', '')} (impacto: {t.get('impacto_estimado', '?')}, prazo: {t.get('prazo', '?')})")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Integrated Alert Prompt
# ---------------------------------------------------------------------------

INTEGRATED_PROMPT = """\
Voce eh um analista senior de equity research com foco em eventos corporativos e special situations no mercado brasileiro.

## SUA TESE VIGENTE SOBRE A EMPRESA:
{thesis_context}

## NOVO DOCUMENTO PUBLICADO NA CVM:
Data: {data}
Categoria: {categoria}
Especie: {especie}
Assunto: {assunto}

## TEXTO DO DOCUMENTO:
{texto}

## INSTRUCOES:

Analise este documento CONTRA a tese vigente. Voce deve responder:
1. Este evento CONFIRMA, CONTRADIZ ou eh NEUTRO em relacao a tese?
2. Algum dos TRIGGERS mapeados na tese foi ativado?
3. A recomendacao deveria mudar? Se sim, para qual e por que?
4. Qual seria o ALERTA que voce enviaria ao portfolio manager?

Responda em JSON:
{{
  "evento_vs_tese": "confirma|contradiz|neutro|novo_fator",
  "triggers_ativados": ["lista dos triggers da tese que este evento ativa, se nenhum = []"],
  "severidade": 1-10,
  "acao_recomendada": "comprar|monitorar|investigar|manter|reduzir|ignorar",
  "muda_recomendacao": {{
    "deve_mudar": true|false,
    "de": "recomendacao anterior",
    "para": "nova recomendacao",
    "motivo": "explicacao"
  }},
  "alerta": {{
    "titulo": "titulo curto e direto do alerta (max 80 chars)",
    "corpo": "2-4 frases explicando o que aconteceu, por que importa, e o que fazer",
    "impacto_valuation": "como isso afeta o valuation (ex: caixa, divida, MC, EV/EBITDA)",
    "impacto_governanca": "como isso afeta a governanca (score, red flags, management)",
    "urgencia": "imediata|24h|semanal|informativo"
  }},
  "contexto_adicional": "informacao relevante do documento que nao estava na tese",
  "proximo_passo": "acao concreta que o analista deve tomar agora"
}}
"""


# ---------------------------------------------------------------------------
# Main backtest
# ---------------------------------------------------------------------------

def run_integrated_backtest(
    only_high: bool = False,
    quarter_filter: str | None = None,
) -> list[dict]:
    """Roda backtest integrado: evento + tese vigente -> alerta rico."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not INDEX_PATH.exists():
        print("[ERRO] index.csv nao encontrado. Rode backtest_westwing.py --step collect primeiro.")
        return []

    idx = pd.read_csv(INDEX_PATH, sep=";", dtype=str, encoding="utf-8-sig").fillna("")
    idx = idx.sort_values("Data_Entrega")

    results = []
    processed = 0
    skipped = 0
    no_thesis = 0

    for _, row in idx.iterrows():
        link = row.get("Link_Download", "")
        if not link:
            continue

        data = row.get("Data_Entrega", "")[:10]
        if not data or len(data) < 10:
            continue

        categoria = row.get("Categoria", "")
        url_hash = hashlib.sha1(link.encode()).hexdigest()[:12]
        data_compact = data.replace("-", "")

        # Quarter filter
        if quarter_filter:
            q = f"{data[:4]}Q{(int(data[5:7])-1)//3 + 1}"
            if q != quarter_filter:
                continue

        # Carregar contexto extraido previamente
        ctx_candidates = list(CONTEXT_DIR.glob(f"{data_compact}_*{url_hash}*.json"))
        if not ctx_candidates:
            continue

        ctx = json.loads(ctx_candidates[0].read_text(encoding="utf-8"))

        # Filtrar por severidade
        sev = ctx.get("severidade", 0)
        if isinstance(sev, str):
            try:
                sev = int(sev)
            except ValueError:
                sev = 0

        min_sev = 5 if only_high else 4
        if sev < min_sev:
            skipped += 1
            continue

        # Carregar tese vigente
        thesis = _load_thesis(data)
        if thesis is None:
            no_thesis += 1
            continue

        # Carregar texto original
        text_candidates = list(TEXTS_DIR.glob(f"{data_compact}_*{url_hash}*.txt"))
        if not text_candidates:
            continue
        texto = text_candidates[0].read_text(encoding="utf-8")[:20000]

        # Formatar contexto da tese
        thesis_context = _format_thesis_context(thesis)
        thesis_date = thesis.get("_thesis_date", "?")
        thesis_rec = thesis.get("recomendacao", "?")

        print(
            f"  [{data}] {categoria[:25]:25s} | sev={sev} | tese={thesis_date} ({thesis_rec})...",
            end=" ", flush=True,
        )

        # Cache check
        cache_file = OUTPUT_DIR / f"{data_compact}_{url_hash}.json"
        if cache_file.exists():
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            results.append(cached)
            processed += 1
            titulo = cached.get("alerta", {}).get("titulo", "?")[:50]
            print(f"[CACHE] {titulo}")
            continue

        prompt = INTEGRATED_PROMPT.format(
            thesis_context=thesis_context,
            data=data,
            categoria=categoria,
            especie=row.get("Especie", ""),
            assunto=row.get("Assunto", ""),
            texto=texto,
        )

        try:
            response = _call_gemini(prompt)
            parsed = _parse_json(response)

            # Enriquecer com metadata
            parsed["_meta"] = {
                "event_date": data,
                "event_categoria": categoria,
                "event_assunto": row.get("Assunto", ""),
                "event_especie": row.get("Especie", ""),
                "event_severidade_triage": sev,
                "thesis_date": thesis_date,
                "thesis_recomendacao": thesis_rec,
                "source_file": ctx_candidates[0].name,
            }

            # Salvar individual
            cache_file.write_text(
                json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            results.append(parsed)
            processed += 1

            titulo = parsed.get("alerta", {}).get("titulo", "?")[:50]
            acao = parsed.get("acao_recomendada", "?")
            evt = parsed.get("evento_vs_tese", "?")
            print(f"{acao} | {evt} | {titulo}")

            time.sleep(0.4)
        except Exception as e:
            print(f"ERRO: {e}")
            time.sleep(3)

    # Salvar consolidado
    consolidated = OUTPUT_DIR / "results_integrated.json"
    consolidated.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\n{'='*70}")
    print(f"  BACKTEST INTEGRADO COMPLETO")
    print(f"  {processed} eventos analisados | {skipped} pulados (sev baixa) | {no_thesis} sem tese")
    print(f"  Salvo em: {consolidated}")
    print(f"{'='*70}")

    # Sumario
    _print_summary(results)

    # Gerar timeline legivel
    _generate_readable_timeline(results)

    return results


# ---------------------------------------------------------------------------
# Sumario e timeline legivel
# ---------------------------------------------------------------------------

def _print_summary(results: list[dict]):
    """Imprime sumario do backtest."""
    if not results:
        return

    print(f"\n--- SUMARIO ---")

    # Por acao recomendada
    acoes = {}
    for r in results:
        a = r.get("acao_recomendada", "?")
        acoes[a] = acoes.get(a, 0) + 1
    print(f"\nAcoes recomendadas:")
    for a, n in sorted(acoes.items(), key=lambda x: -x[1]):
        print(f"  {a:15s} {n}")

    # Por relacao com tese
    rel = {}
    for r in results:
        e = r.get("evento_vs_tese", "?")
        rel[e] = rel.get(e, 0) + 1
    print(f"\nRelacao com tese:")
    for e, n in sorted(rel.items(), key=lambda x: -x[1]):
        print(f"  {e:15s} {n}")

    # Triggers ativados
    all_triggers = []
    for r in results:
        all_triggers.extend(r.get("triggers_ativados", []))
    if all_triggers:
        from collections import Counter
        tc = Counter(all_triggers)
        print(f"\nTriggers mais ativados:")
        for t, n in tc.most_common(10):
            print(f"  [{n}x] {t}")

    # Mudancas de recomendacao
    mudancas = [r for r in results if r.get("muda_recomendacao", {}).get("deve_mudar")]
    if mudancas:
        print(f"\nMudancas de recomendacao sugeridas ({len(mudancas)}):")
        for m in mudancas:
            meta = m.get("_meta", {})
            mr = m["muda_recomendacao"]
            print(f"  {meta.get('event_date', '?')} | {mr.get('de', '?')} -> {mr.get('para', '?')}")
            print(f"    Motivo: {mr.get('motivo', '')[:100]}")

    # TOP alertas por severidade
    top = sorted(results, key=lambda x: x.get("severidade", 0), reverse=True)[:10]
    print(f"\nTOP 10 alertas por severidade:")
    for r in top:
        meta = r.get("_meta", {})
        alerta = r.get("alerta", {})
        print(f"  [{r.get('severidade', '?')}] {meta.get('event_date', '?')} | {alerta.get('titulo', '?')[:60]}")
        print(f"      Urgencia: {alerta.get('urgencia', '?')} | Acao: {r.get('acao_recomendada', '?')}")


def _generate_readable_timeline(results: list[dict]):
    """Gera timeline legivel em formato texto."""
    if not results:
        return

    # Ordenar por data
    sorted_results = sorted(
        results,
        key=lambda x: x.get("_meta", {}).get("event_date", ""),
    )

    lines = [
        "=" * 80,
        "  TIMELINE DE ALERTAS — WESTWING (WEST3)",
        "  Backtest Integrado: Evento + Tese do Agente de Avaliacao",
        "=" * 80,
        "",
    ]

    current_quarter = ""
    for r in sorted_results:
        meta = r.get("_meta", {})
        event_date = meta.get("event_date", "")
        if not event_date:
            continue

        # Header de trimestre
        q = f"{event_date[:4]}Q{(int(event_date[5:7])-1)//3 + 1}"
        if q != current_quarter:
            current_quarter = q
            thesis_date = meta.get("thesis_date", "?")
            thesis_rec = meta.get("thesis_recomendacao", "?")
            lines.append(f"\n{'─'*80}")
            lines.append(f"  {q} | Tese vigente: {thesis_date} | Rec: {thesis_rec.upper()}")
            lines.append(f"{'─'*80}")

        # Alerta
        alerta = r.get("alerta", {})
        sev = r.get("severidade", "?")
        acao = r.get("acao_recomendada", "?")
        evt = r.get("evento_vs_tese", "?")
        urgencia = alerta.get("urgencia", "?")

        # Icone de urgencia
        icon = {
            "imediata": "!!!",
            "24h": "!! ",
            "semanal": "!  ",
            "informativo": "   ",
        }.get(urgencia, "   ")

        lines.append(f"\n  {icon} [{sev:>2}] {event_date} | {meta.get('event_categoria', '')[:25]}")
        lines.append(f"       {alerta.get('titulo', '(sem titulo)')}")
        lines.append(f"       Acao: {acao} | Relacao: {evt}")

        corpo = alerta.get("corpo", "")
        if corpo:
            # Wrap corpo
            for line in _wrap_text(corpo, 70):
                lines.append(f"       {line}")

        # Triggers ativados
        triggers = r.get("triggers_ativados", [])
        if triggers:
            lines.append(f"       Triggers: {', '.join(str(t) for t in triggers[:5])}")

        # Impacto valuation
        imp_val = alerta.get("impacto_valuation", "")
        if imp_val:
            lines.append(f"       Valuation: {imp_val[:100]}")

        # Impacto governanca
        imp_gov = alerta.get("impacto_governanca", "")
        if imp_gov:
            lines.append(f"       Governanca: {imp_gov[:100]}")

        # Mudanca de recomendacao
        muda = r.get("muda_recomendacao", {})
        if muda.get("deve_mudar"):
            lines.append(f"       >>> MUDAR REC: {muda.get('de', '?')} -> {muda.get('para', '?')}")
            lines.append(f"       >>> Motivo: {muda.get('motivo', '')[:100]}")

        # Proximo passo
        prox = r.get("proximo_passo", "")
        if prox:
            lines.append(f"       Proximo passo: {prox[:120]}")

    # Footer
    lines.append(f"\n{'='*80}")
    lines.append(f"  Total: {len(sorted_results)} alertas")
    lines.append(f"{'='*80}")

    timeline_path = OUTPUT_DIR / "timeline_alertas.txt"
    timeline_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Timeline legivel salva em: {timeline_path}")


def _wrap_text(text: str, width: int) -> list[str]:
    """Quebra texto em linhas de tamanho maximo."""
    words = text.split()
    lines = []
    current = ""
    for w in words:
        if len(current) + len(w) + 1 > width:
            lines.append(current)
            current = w
        else:
            current = f"{current} {w}" if current else w
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Backtest Integrado: Eventos + Tese")
    parser.add_argument("--only-high", action="store_true", help="So eventos sev >= 5")
    parser.add_argument("--quarter", default=None, help="Filtrar por trimestre (ex: 2023Q3)")
    args = parser.parse_args()

    run_integrated_backtest(
        only_high=args.only_high,
        quarter_filter=args.quarter,
    )


if __name__ == "__main__":
    main()
