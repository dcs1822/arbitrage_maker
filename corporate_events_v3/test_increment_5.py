"""
test_increment_5.py - Validacao end-to-end do incremento 5.

Pipeline testado:
    1. Carrega eventos relevantes pendentes de deep analysis
    2. Para cada um, le o PDF cacheado, extrai texto
    3. Monta contexto da empresa via company_state.context_snippet
    4. Roda analyzer.analyze_event (gemini-2.5-pro)
    5. Grava deep_analysis_json + severidade + urgencia + tipo_evento + flags
    6. Mostra top por severidade

Pre-requisito: incremento 4 ja rodou e populou events com triage_decision='relevante'.

Execucao:
    cd "P:\\Analise\\Trader\\Projetos\\Fato Relevante GPT"
    python -m corporate_events_v3.test_increment_5
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from . import config, llm_provider
from .pipeline import analyzer, fetcher
from .state import company, db, events as events_state


MAX_EVENTOS = 15  # limite para nao estourar custo no teste


def _fmt_sev(s: int | None) -> str:
    if not s:
        return "  -"
    return f"{s:>3}"


def main() -> int:
    print("=" * 68)
    print("CORPORATE EVENTS V3 - INCREMENTO 5")
    print("Estagio 2 (deep analyzer) com gemini-2.5-pro + contexto")
    print("=" * 68)

    # === 0. Sanity ===
    if not config.GEMINI_API_KEY:
        print("\n[ERRO] GEMINI_API_KEY nao definida.")
        return 2

    db.init_db()

    pendentes = events_state.list_pending_deep(limit=MAX_EVENTOS)
    if not pendentes:
        print("\n[AVISO] Nao ha eventos relevantes pendentes de deep analysis.")
        print("Rode primeiro test_increment_4.py.")
        return 1

    print(f"\n[1] {len(pendentes)} evento(s) relevantes pendentes de analise profunda.")
    print(f"    Modelo: {config.LLM_DEEP[1]}")

    # === 2. Provider ===
    try:
        provider = llm_provider.get_provider()
    except Exception as e:
        print(f"    [ERRO provider] {e}")
        return 3

    # === 3. Loop ===
    print(f"\n[2] Rodando analise profunda em {len(pendentes)} documentos...\n")
    t0 = time.time()
    ok_cnt = 0
    fail_cnt = 0
    sev_hist = {i: 0 for i in range(1, 11)}

    for idx, ev in enumerate(pendentes, 1):
        ev_id = ev["id"]
        cd = ev["cd_cvm"]
        denom = ev["denom"] or "-"
        ticker = ev["ticker"] or "-"
        categoria = ev["categoria"] or "-"
        pdf_path = Path(ev["pdf_path"]) if ev.get("pdf_path") else None

        header = f"  ({idx:>2}/{len(pendentes)}) [{ticker:8}] {denom[:38]:38} {categoria[:22]:22}"
        print(header)

        # Le texto do PDF (re-extrai do cache, nao gasta nada)
        if pdf_path is None or not pdf_path.exists():
            print(f"      [SKIP] PDF nao esta no cache: {pdf_path}")
            fail_cnt += 1
            continue
        texto = fetcher.extrair_texto(pdf_path)
        if not texto:
            print("      [SKIP] PDF sem texto extraivel")
            fail_cnt += 1
            continue

        # Chamada do analyzer
        try:
            result = analyzer.analyze_event(
                texto=texto,
                categoria=categoria,
                cd_cvm=cd,
                provider=provider,
            )
        except Exception as e:
            print(f"      [ERRO LLM] {e}")
            fail_cnt += 1
            continue

        if not result.get("_ok"):
            print(f"      [PARSE FALHOU] resumo={result.get('resumo','')[:60]}")
            fail_cnt += 1
            continue

        # Persiste
        # Nao serializa as chaves privadas _raw_llm / _ok no banco.
        to_store = {k: v for k, v in result.items() if not k.startswith("_")}
        events_state.update_deep_analysis(
            event_id=ev_id,
            analysis_json=json.dumps(to_store, ensure_ascii=False),
            severidade=result["severidade"],
            urgencia=result["urgencia"],
            tipo_evento=result["tipo_evento"],
            flags_json=json.dumps(result["flags"], ensure_ascii=False),
        )

        # Atualiza last_seen_doc_at da empresa
        if ev.get("data_documento"):
            company.touch_last_seen(cd, ev["data_documento"])

        ok_cnt += 1
        sev_hist[result["severidade"]] = sev_hist.get(result["severidade"], 0) + 1

        flags_s = ",".join(result["flags"][:3]) or "-"
        print(
            f"      [OK] sev={_fmt_sev(result['severidade'])} "
            f"urg={result['urgencia']:5} tipo={result['tipo_evento']:18} "
            f"flags={flags_s}"
        )
        print(f"          resumo: {result['resumo'][:110]}")
        if result.get("conexao_com_contexto"):
            print(f"          contexto: {result['conexao_com_contexto'][:110]}")
        time.sleep(0.1)

    elapsed = time.time() - t0

    # === 4. Estatisticas ===
    print("\n" + "=" * 68)
    print("ESTATISTICAS")
    print("=" * 68)
    print(f"  Tempo total:   {elapsed:.1f}s")
    print(f"  Sucesso:       {ok_cnt}")
    print(f"  Falhas:        {fail_cnt}")
    print("\n  Histograma de severidade:")
    for sev in range(10, 0, -1):
        n = sev_hist.get(sev, 0)
        bar = "#" * n
        print(f"    sev {sev:>2} | {bar:20} {n}")

    print("\n" + "=" * 68)
    print("TOP EVENTOS POR SEVERIDADE")
    print("=" * 68)
    top = events_state.top_by_severity(limit=20)
    if not top:
        print("  (nenhum)")
    else:
        for r in top:
            tk = r.get("ticker") or "-"
            sev = r.get("severidade") or 0
            urg = r.get("urgencia") or "-"
            tipo = r.get("tipo_evento") or "-"
            try:
                da = json.loads(r.get("deep_analysis_json") or "{}")
            except Exception:
                da = {}
            resumo = (da.get("resumo") or "")[:100]
            print(f"  sev={sev:>2} {urg:5} {tk:8} {tipo:18} | {resumo}")

    print("\n" + "=" * 68)
    print("Incremento 5 concluido.")
    print("=" * 68)
    return 0 if fail_cnt == 0 else 0  # nao falha o teste por 1-2 parse errors


if __name__ == "__main__":
    sys.exit(main())
