"""
test_increment_4.py - Validacao end-to-end do incremento 4.

Pipeline testado:
    1. Garante que o universo (20 empresas) esta em company_state
    2. Para cada empresa, lista documentos da CVM nas ultimas N dias
    3. Filtra os que ja existem em events (deduplicacao)
    4. Baixa o PDF, extrai texto, insere em events
    5. Roda triagem (estagio 1) com gemini-2.5-flash-lite
    6. Atualiza events.triage_decision / triage_reason
    7. Mostra estatisticas finais

Execucao:
    cd "P:\\Analise\\Trader\\Projetos\\Fato Relevante GPT"
    python -m corporate_events_v3.test_increment_4

Configuracao do lookback:
    LOOKBACK_DIAS define quantos dias para tras buscar (default 30 para teste).
"""
from __future__ import annotations

import sys
import time
from datetime import date, timedelta

from . import config, llm_provider, universe_selector
from .pipeline import fetcher, triage
from .state import company, db, events as events_state


# Janela do teste. Em producao, usariamos `date.today()` mas a maquina de
# desenvolvimento esta com data adiantada (2026) enquanto a CVM ainda esta
# em 2025, entao para o teste fixamos uma janela conhecida que tem dados.
DATA_FIM_FIXA = date(2025, 12, 31)
LOOKBACK_DIAS = 30


def _fmt_pct(num: int, den: int) -> str:
    if den <= 0:
        return "0%"
    return f"{(100.0 * num / den):.1f}%"


def main() -> int:
    print("=" * 64)
    print("CORPORATE EVENTS V3 - INCREMENTO 4")
    print("CVM fetcher + estagio 1 (triagem com Gemini Flash-Lite)")
    print("=" * 64)

    # === 0. Sanity ===
    if not config.GEMINI_API_KEY:
        print("\n[ERRO] GEMINI_API_KEY nao definida nas variaveis de ambiente.")
        return 2

    # === 1. DB + universo ===
    print("\n[1] Inicializando DB e universo...")
    db.init_db()
    selecionados = universe_selector.build_universe()
    n = company.initialize_from_universe(selecionados)
    print(f"    Universo: {n} empresas em company_state")

    # === 2. Janela de datas ===
    data_fim = DATA_FIM_FIXA
    data_ini = data_fim - timedelta(days=LOOKBACK_DIAS)
    print(f"    Janela:   {data_ini} -> {data_fim} ({LOOKBACK_DIAS} dias, fixa para teste)")

    # === 3. Provider LLM (instancia uma vez para reusar conexao) ===
    print(f"\n[2] Inicializando provider LLM ({config.LLM_TRIAGE[1]})...")
    try:
        provider = llm_provider.get_provider()
    except Exception as e:
        print(f"    [ERRO] {e}")
        return 3
    print("    OK")

    # === 4. Loop por empresa ===
    print(f"\n[3] Iterando {n} empresas...")
    t0 = time.time()
    total_links = 0
    total_novos = 0
    total_dl_ok = 0
    total_triado = 0
    total_relev = 0
    total_desc = 0
    total_cache_hit = 0
    total_erros = 0

    todas = company.all_companies()
    for idx, c in enumerate(todas, 1):
        cd = c["cd_cvm"]
        denom = c["denom"] or "-"
        ticker = c["ticker"] or "-"
        fonte = c["fonte"] or "-"
        print(f"\n  ({idx:>2}/{n}) {ticker:8} {cd:>6}  {denom[:40]}")

        try:
            docs = fetcher.listar_todas_categorias(cd, data_ini, data_fim)
        except Exception as e:
            print(f"      [ERRO listar] {e}")
            total_erros += 1
            continue

        if not docs:
            print("      0 documentos")
            continue

        total_links += len(docs)
        novos = 0
        for d in docs:
            if events_state.event_exists(d.link):
                continue
            novos += 1
            total_novos += 1

            pdf_path = fetcher.pdf_path_for(cd, d.link)
            ok = pdf_path.exists() or fetcher.baixar_pdf(d.link, pdf_path)
            if not ok:
                print(f"      [DL falhou] {d.link[:80]}")
                total_erros += 1
                continue
            total_dl_ok += 1

            texto = fetcher.extrair_texto(pdf_path)

            ev_id = events_state.insert_event(
                cd_cvm=cd,
                denom=denom,
                ticker=ticker if ticker != "-" else None,
                categoria=d.categoria_nome,
                data_documento=str(data_fim),
                link_pdf=d.link,
                pdf_path=str(pdf_path),
                fonte=fonte,
            )

            if texto:
                events_state.update_text_hash(ev_id, db.text_hash(texto))

            decision, reason, cache_hit = triage.triage_text(
                texto=texto,
                categoria=d.categoria_nome,
                denom=denom,
                cd_cvm=cd,
                provider=provider,
            )
            events_state.update_triage(ev_id, decision, reason)

            total_triado += 1
            if cache_hit:
                total_cache_hit += 1
            if decision == "relevante":
                total_relev += 1
                marker = "***"
            else:
                total_desc += 1
                marker = "   "
            print(f"      {marker} [{decision:9}] {d.categoria_nome[:25]:25}  {reason[:60]}")

            time.sleep(0.05)  # gentil

        print(f"      total: {len(docs)} docs / {novos} novos")

    elapsed = time.time() - t0

    # === 5. Estatisticas ===
    print("\n" + "=" * 64)
    print("ESTATISTICAS")
    print("=" * 64)
    print(f"  Tempo total:           {elapsed:.1f}s")
    print(f"  Links retornados:      {total_links}")
    print(f"  Novos (nao em events): {total_novos}")
    print(f"  Downloads OK:          {total_dl_ok}")
    print(f"  Triados:               {total_triado}")
    print(f"  -> relevantes:         {total_relev} ({_fmt_pct(total_relev, total_triado)})")
    print(f"  -> descartados:        {total_desc} ({_fmt_pct(total_desc, total_triado)})")
    print(f"  Cache hits (triagem):  {total_cache_hit}")
    print(f"  Erros:                 {total_erros}")

    print("\n  Contagem por tabela:")
    for tbl, n in db.table_counts().items():
        print(f"    {tbl:15} {n:>5}")

    relev = events_state.list_relevant(limit=20)
    if relev:
        print(f"\n  TOP {len(relev)} eventos marcados como relevantes:")
        for r in relev:
            tk = r["ticker"] or "-"
            print(f"    [{tk:8}] {(r['categoria'] or '')[:25]:25}  {(r['triage_reason'] or '')[:70]}")

    print("\n" + "=" * 64)
    print("Incremento 4 concluido.")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
