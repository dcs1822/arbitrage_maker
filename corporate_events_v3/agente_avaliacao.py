"""
agente_avaliacao.py — Agente de Avaliacao de Equity Research para WestWing.

Persona: Analista Senior de Equity Research com background de M&A/IB.
Consome dados estruturados (financeiros, acionario, governanca, precos)
e produz uma tese de investimento + valuation + triggers.

Uso:
    python agente_avaliacao.py --date 2023-06-01    # tese como se fosse junho/2023
    python agente_avaliacao.py --date 2026-03-20    # tese atual
    python agente_avaliacao.py --backtest           # gera tese a cada trimestre
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(r"C:\Agent\westwing")
STRUCTURED_DIR = BASE_DIR / "structured"
CONTEXT_DIR = BASE_DIR / "context"
THESIS_DIR = BASE_DIR / "thesis"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ---------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------

ANALYST_PERSONA = """\
Voce e um Analista Senior de Equity Research com mais de 20 anos de experiencia \
no mercado de capitais brasileiro. Sua base foi forjada em Investment Banking (IB) \
e M&A em bancos bulge bracket, o que lhe confere uma visao profunda de estrutura \
de capital, modelagem financeira complexa e dinamicas de transacao.

Mindset Analitico:
- Ceticismo de M&A: Voce nao aceita projecoes de sinergia ou "growth" sem evidencias claras. \
  Voce sabe onde as empresas escondem passivos e como o "window dressing" funciona.
- Foco em Valor Real: Sua analise e centrada em geracao de caixa livre e retorno sobre \
  capital investido (ROIC). Voce ignora o ruido de curto prazo e foca na tese estrutural.
- Gestao e Governanca: Voce avalia o historico do management com rigor. Promessas nao \
  cumpridas no passado pesam muito na sua avaliacao atual.
- Macro vs. Micro: Voce entende como o custo de capital (WACC) no Brasil e volatil e como \
  a dinamica politica afeta o premio de risco, mas sua tese sempre comeca no bottom-up.
"""

# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def load_financials(as_of: str) -> list[dict]:
    """Carrega dados financeiros ate a data especificada."""
    path = STRUCTURED_DIR / "financials_timeline.json"
    if not path.exists():
        return []
    all_data = json.loads(path.read_text(encoding="utf-8"))
    # Filtrar periodos com dados e antes da data
    filtered = []
    for t in all_data:
        periodo = t.get("periodo", "")
        data_ref = t.get("data_referencia", "") or t.get("data_entrega", "")
        if not periodo or periodo == "?":
            continue
        if data_ref and data_ref > as_of:
            continue
        # Verificar se tem dados reais
        caixa = t.get("balanco", {}).get("caixa_total") or t.get("balanco", {}).get("caixa_equivalentes")
        if caixa is None:
            continue
        filtered.append(t)
    # Dedup por periodo
    seen = set()
    unique = []
    for t in filtered:
        p = t["periodo"]
        if p not in seen:
            seen.add(p)
            unique.append(t)
    return unique


def load_acionario(as_of: str) -> list[dict]:
    """Carrega movimentacoes acionarias ate a data."""
    path = STRUCTURED_DIR / "acionario_timeline.json"
    if not path.exists():
        return []
    all_data = json.loads(path.read_text(encoding="utf-8"))
    filtered = []
    for mov in all_data:
        if not isinstance(mov, dict):
            continue
        data = mov.get("data", "")
        if data and data <= as_of:
            filtered.append(mov)
    return filtered


def load_estatuto() -> dict:
    """Carrega estatuto vigente."""
    path = STRUCTURED_DIR / "estatuto_vigente.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_prices(as_of: str) -> dict:
    """Carrega precos e calcula metricas de mercado."""
    path = STRUCTURED_DIR / "prices.json"
    if not path.exists():
        return {}
    all_prices = json.loads(path.read_text(encoding="utf-8"))
    # Filtrar ate a data
    filtered = [p for p in all_prices if p["date"] <= as_of]
    if not filtered:
        return {}

    latest = filtered[-1]
    # Calcular metricas
    prices_30d = [p for p in filtered if p["date"] >= _date_minus_days(as_of, 30)]
    prices_90d = [p for p in filtered if p["date"] >= _date_minus_days(as_of, 90)]
    prices_1y = [p for p in filtered if p["date"] >= _date_minus_days(as_of, 365)]

    avg_vol_30d = sum(p["volume"] for p in prices_30d) / max(len(prices_30d), 1)

    result = {
        "data": latest["date"],
        "preco_atual": latest["close"],
        "volume_medio_30d": int(avg_vol_30d),
    }

    if prices_30d:
        result["variacao_30d_pct"] = round((latest["close"] / prices_30d[0]["close"] - 1) * 100, 1)
    if prices_90d:
        result["variacao_90d_pct"] = round((latest["close"] / prices_90d[0]["close"] - 1) * 100, 1)
    if prices_1y:
        result["variacao_1y_pct"] = round((latest["close"] / prices_1y[0]["close"] - 1) * 100, 1)
        result["minima_1y"] = min(p["close"] for p in prices_1y)
        result["maxima_1y"] = max(p["close"] for p in prices_1y)

    return result


def load_events(as_of: str) -> list[dict]:
    """Carrega eventos relevantes (do context dir) ate a data."""
    if not CONTEXT_DIR.exists():
        return []
    events = []
    for f in sorted(CONTEXT_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            event_date = data.get("data", "") or ""
            if event_date and event_date <= as_of:
                sev = data.get("severidade", 0)
                if isinstance(sev, str):
                    try:
                        sev = int(sev)
                    except:
                        sev = 0
                if sev >= 4:  # So eventos relevantes
                    events.append(data)
        except:
            continue
    # Ultimos 10
    return events[-10:]


def _date_minus_days(date_str: str, days: int) -> str:
    from datetime import timedelta
    d = datetime.strptime(date_str[:10], "%Y-%m-%d")
    return (d - timedelta(days=days)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Construir snapshot para o agente
# ---------------------------------------------------------------------------

def build_company_snapshot(as_of: str) -> str:
    """Constroi snapshot completo da empresa para o agente avaliar."""
    financials = load_financials(as_of)
    acionario = load_acionario(as_of)
    estatuto = load_estatuto()
    prices = load_prices(as_of)
    events = load_events(as_of)

    # Montar snapshot textual
    lines = [
        "=" * 60,
        f"SNAPSHOT: WESTWING (WEST3) — Data: {as_of}",
        "=" * 60,
        "",
        "## DADOS DE MERCADO",
    ]

    if prices:
        lines.append(f"Preco: R${prices.get('preco_atual', '?')}")
        lines.append(f"Volume medio 30d: {prices.get('volume_medio_30d', '?')}")
        if "variacao_30d_pct" in prices:
            lines.append(f"Variacao 30d: {prices['variacao_30d_pct']}%")
        if "variacao_1y_pct" in prices:
            lines.append(f"Variacao 1 ano: {prices['variacao_1y_pct']}%")
            lines.append(f"Min/Max 1 ano: R${prices.get('minima_1y', '?')} / R${prices.get('maxima_1y', '?')}")

        # Market cap estimado
        total_acoes = estatuto.get("capital_social", {}).get("total_acoes")
        if total_acoes and prices.get("preco_atual"):
            mc = total_acoes * prices["preco_atual"]
            lines.append(f"Market Cap estimado: R${mc/1e6:.1f} milhoes ({total_acoes:,} acoes)")

    lines.append("")
    lines.append("## DADOS FINANCEIROS (R$ mil)")

    if financials:
        latest = financials[-1]
        lines.append(f"Periodo mais recente: {latest.get('periodo', '?')}")

        bal = latest.get("balanco", {})
        dre = latest.get("dre", {})

        lines.append(f"Caixa total: R${bal.get('caixa_total', '?')} mil")
        lines.append(f"Divida bruta: R${bal.get('divida_bruta', '?')} mil")
        lines.append(f"PL: R${bal.get('patrimonio_liquido', '?')} mil")
        lines.append(f"Receita liquida: R${dre.get('receita_liquida', '?')} mil")
        lines.append(f"Lucro liquido: R${dre.get('lucro_liquido', '?')} mil")
        lines.append(f"EBITDA: R${dre.get('ebitda', '?')} mil")

        lines.append("")
        lines.append("Evolucao historica:")
        for f_data in financials:
            p = f_data.get("periodo", "?")
            c = f_data.get("balanco", {}).get("caixa_total") or f_data.get("balanco", {}).get("caixa_equivalentes", "?")
            ll = f_data.get("dre", {}).get("lucro_liquido", "?")
            r = f_data.get("dre", {}).get("receita_liquida", "?")
            lines.append(f"  {p}: caixa={c} | LL={ll} | rec={r}")

    lines.append("")
    lines.append("## ESTATUTO SOCIAL")

    if estatuto:
        gov = estatuto.get("governanca", {})
        cap = estatuto.get("capital_social", {})
        lines.append(f"Tag along ON: {gov.get('tag_along_on_pct', '?')}%")
        pp = gov.get("poison_pill", {})
        if isinstance(pp, dict):
            lines.append(f"Poison pill: {pp.get('existe', '?')} (trigger: {pp.get('trigger_pct', '?')}%)")
            if pp.get("descricao"):
                lines.append(f"  Descricao: {pp['descricao']}")
        lines.append(f"Voto multiplo: {gov.get('voto_multiplo', '?')}")
        lines.append(f"Conselho: {gov.get('conselho_min_membros', '?')}-{gov.get('conselho_max_membros', '?')} membros")
        lines.append(f"Capital autorizado: {cap.get('capital_autorizado', '?')} acoes")
        lines.append(f"Total acoes: {cap.get('total_acoes', '?')}")

    lines.append("")
    lines.append("## COMPOSICAO ACIONARIA (movimentacoes recentes)")

    if acionario:
        # Ultimas 10 movimentacoes
        recent = acionario[-10:]
        for mov in recent:
            nome = mov.get("acionista", "?")[:30]
            pct_depois = mov.get("percentual_depois", "?")
            tipo = mov.get("tipo_movimentacao", "?")
            data_mov = mov.get("data", "?")
            intencao = (mov.get("intencao_declarada") or "")[:60]
            lines.append(f"  {data_mov} | {nome:30s} | {tipo:10s} | {pct_depois}%")
            if intencao:
                lines.append(f"    Intencao: {intencao}")

    lines.append("")
    lines.append("## EVENTOS RECENTES (severidade >= 4)")

    if events:
        for ev in events:
            data_ev = ev.get("data", "?")
            resumo = ev.get("resumo", "?")[:100]
            sev = ev.get("severidade", "?")
            flags = ev.get("flags", [])
            lines.append(f"  [{sev}] {data_ev} — {resumo}")
            if flags:
                lines.append(f"      flags: {', '.join(str(f) for f in flags if f)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agente de Avaliacao
# ---------------------------------------------------------------------------

THESIS_PROMPT = """\
{persona}

Voce recebe abaixo o SNAPSHOT completo de uma empresa brasileira listada na B3.
Com base nesses dados, produza uma AVALIACAO DE INVESTIMENTO completa.

IMPORTANTE:
- Use APENAS os dados fornecidos. Nao invente numeros.
- Seja cético — aponte inconsistências, red flags, e riscos.
- Calcule metricas de valuation com os dados disponiveis (P/PL, EV/EBITDA, caixa/MC).
- Avalie a qualidade da governanca e do management pelo historico de eventos.
- Identifique TRIGGERS especificos que mudariam sua recomendacao.

{snapshot}

PRODUZA SUA AVALIACAO EM JSON:
{{
  "empresa": "nome",
  "ticker": "WEST3",
  "data_avaliacao": "{as_of}",
  "recomendacao": "comprar|monitorar|evitar",
  "confianca": "alta|media|baixa",
  "tese_resumo": "2-3 frases com a tese principal",
  "valuation": {{
    "market_cap_mm": null,
    "caixa_liquido_mm": null,
    "desconto_sobre_caixa_pct": null,
    "pl_por_acao": null,
    "preco_sobre_pl": null,
    "ev_ebitda": null,
    "observacao_valuation": "comentario sobre o valuation"
  }},
  "tese_bull": {{
    "resumo": "cenario otimista em 2-3 frases",
    "target_price": null,
    "upside_pct": null,
    "probabilidade_estimada": null,
    "catalalisadores": ["lista de catalisadores"]
  }},
  "tese_bear": {{
    "resumo": "cenario pessimista em 2-3 frases",
    "target_price": null,
    "downside_pct": null,
    "probabilidade_estimada": null,
    "riscos": ["lista de riscos"]
  }},
  "governanca": {{
    "score": "1-10",
    "red_flags": ["lista de red flags"],
    "pontos_positivos": ["se houver"],
    "rotatividade_management": "alta|media|baixa",
    "risco_ativismo": "alto|medio|baixo",
    "comentario": "avaliacao qualitativa"
  }},
  "triggers": [
    {{
      "trigger": "descricao do evento que mudaria a tese",
      "direcao": "positivo|negativo",
      "impacto_estimado": "alto|medio|baixo",
      "probabilidade": "alta|media|baixa",
      "prazo": "curto|medio|longo"
    }}
  ],
  "proximos_passos": ["lista de acoes que o analista deveria tomar"],
  "nota_final": "comentario livre do analista com sua visao pessoal"
}}
"""


def _call_gemini(prompt: str, model: str = "gemini-2.5-pro") -> str:
    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY)

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "temperature": 0.2,
                    "max_output_tokens": 8000,
                    "response_mime_type": "application/json",
                    "thinking_config": {"thinking_budget": 4000},
                },
            )
            text = response.text or ""
            if not text and response.candidates:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "text") and part.text:
                        text = part.text
                        break
            return text
        except Exception as e:
            if "503" in str(e) or "429" in str(e):
                wait = (attempt + 1) * 10
                print(f"  [RETRY] {e} — aguardando {wait}s...", flush=True)
                time.sleep(wait)
            else:
                raise
    return ""


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```\s*$', '', text)
    text = re.sub(r',\s*([}\]])', r'\1', text)
    try:
        return json.loads(text)
    except:
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try:
                return json.loads(re.sub(r',\s*([}\]])', r'\1', m.group()))
            except:
                pass
        return {"raw": text}


def generate_thesis(as_of: str) -> dict:
    """Gera tese de investimento para a data especificada."""
    print(f"\n  Construindo snapshot para {as_of}...", flush=True)
    snapshot = build_company_snapshot(as_of)

    print(f"  Gerando tese via Gemini Pro...", flush=True)
    prompt = THESIS_PROMPT.format(
        persona=ANALYST_PERSONA,
        snapshot=snapshot,
        as_of=as_of,
    )

    response = _call_gemini(prompt)
    thesis = _parse_json(response)
    thesis["snapshot_used"] = snapshot

    return thesis


def format_thesis_readable(thesis: dict) -> str:
    """Formata tese para leitura humana."""
    lines = [
        "=" * 70,
        f"  AVALIACAO: {thesis.get('empresa', 'WESTWING')} ({thesis.get('ticker', 'WEST3')})",
        f"  Data: {thesis.get('data_avaliacao', '?')}",
        f"  Recomendacao: {thesis.get('recomendacao', '?').upper()} (confianca: {thesis.get('confianca', '?')})",
        "=" * 70,
        "",
        f"TESE: {thesis.get('tese_resumo', '')}",
        "",
    ]

    val = thesis.get("valuation", {})
    if val:
        lines.append("VALUATION:")
        lines.append(f"  Market Cap: R${val.get('market_cap_mm', '?')}M")
        lines.append(f"  Caixa liquido: R${val.get('caixa_liquido_mm', '?')}M")
        lines.append(f"  Desconto sobre caixa: {val.get('desconto_sobre_caixa_pct', '?')}%")
        lines.append(f"  P/PL: {val.get('preco_sobre_pl', '?')}x")
        lines.append(f"  Obs: {val.get('observacao_valuation', '')}")
        lines.append("")

    bull = thesis.get("tese_bull", {})
    if bull:
        lines.append(f"BULL CASE (prob: {bull.get('probabilidade_estimada', '?')}%):")
        lines.append(f"  {bull.get('resumo', '')}")
        lines.append(f"  Target: R${bull.get('target_price', '?')} (upside: {bull.get('upside_pct', '?')}%)")
        if bull.get("catalalisadores"):
            for c in bull["catalalisadores"]:
                lines.append(f"    - {c}")
        lines.append("")

    bear = thesis.get("tese_bear", {})
    if bear:
        lines.append(f"BEAR CASE (prob: {bear.get('probabilidade_estimada', '?')}%):")
        lines.append(f"  {bear.get('resumo', '')}")
        lines.append(f"  Target: R${bear.get('target_price', '?')} (downside: {bear.get('downside_pct', '?')}%)")
        if bear.get("riscos"):
            for r in bear["riscos"]:
                lines.append(f"    - {r}")
        lines.append("")

    gov = thesis.get("governanca", {})
    if gov:
        lines.append(f"GOVERNANCA (score: {gov.get('score', '?')}/10):")
        lines.append(f"  Rotatividade mgmt: {gov.get('rotatividade_management', '?')}")
        lines.append(f"  Risco ativismo: {gov.get('risco_ativismo', '?')}")
        if gov.get("red_flags"):
            lines.append("  Red flags:")
            for rf in gov["red_flags"]:
                lines.append(f"    ! {rf}")
        lines.append(f"  {gov.get('comentario', '')}")
        lines.append("")

    triggers = thesis.get("triggers", [])
    if triggers:
        lines.append("TRIGGERS:")
        for t in triggers:
            dir_symbol = "+" if t.get("direcao") == "positivo" else "-"
            lines.append(f"  [{dir_symbol}] {t.get('trigger', '')} (impacto: {t.get('impacto_estimado', '?')}, prob: {t.get('probabilidade', '?')})")
        lines.append("")

    if thesis.get("nota_final"):
        lines.append(f"NOTA DO ANALISTA: {thesis['nota_final']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Backtest: gerar teses trimestrais
# ---------------------------------------------------------------------------

BACKTEST_DATES = [
    "2021-06-30", "2021-12-31",
    "2022-06-30", "2022-12-31",
    "2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31",
    "2024-06-30", "2024-12-31",
    "2025-06-30", "2025-12-31",
    "2026-03-31",
]


def run_backtest():
    """Gera teses para cada ponto no tempo."""
    THESIS_DIR.mkdir(parents=True, exist_ok=True)

    for as_of in BACKTEST_DATES:
        print(f"\n{'='*60}")
        print(f"  TESE: {as_of}")
        print(f"{'='*60}")

        out_file = THESIS_DIR / f"thesis_{as_of}.json"
        if out_file.exists():
            print("  [CACHE] ja existe, pulando")
            thesis = json.loads(out_file.read_text(encoding="utf-8"))
        else:
            thesis = generate_thesis(as_of)
            out_file.write_text(json.dumps(thesis, indent=2, ensure_ascii=False), encoding="utf-8")

        readable = format_thesis_readable(thesis)
        print(readable)
        time.sleep(2)  # Rate limit Gemini Pro

    print(f"\n{'='*60}")
    print(f"  BACKTEST COMPLETO: {len(BACKTEST_DATES)} teses geradas")
    print(f"  Salvas em: {THESIS_DIR}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Agente de Avaliacao - Equity Research")
    parser.add_argument("--date", default=None, help="Data da avaliacao (YYYY-MM-DD)")
    parser.add_argument("--backtest", action="store_true", help="Gerar teses trimestrais")
    args = parser.parse_args()

    THESIS_DIR.mkdir(parents=True, exist_ok=True)

    if args.backtest:
        run_backtest()
    else:
        as_of = args.date or datetime.now().strftime("%Y-%m-%d")
        thesis = generate_thesis(as_of)

        out_file = THESIS_DIR / f"thesis_{as_of}.json"
        out_file.write_text(json.dumps(thesis, indent=2, ensure_ascii=False), encoding="utf-8")

        readable = format_thesis_readable(thesis)
        print(readable)

        readable_file = THESIS_DIR / f"thesis_{as_of}.txt"
        readable_file.write_text(readable, encoding="utf-8")
        print(f"\nSalvo: {out_file}")


if __name__ == "__main__":
    main()
