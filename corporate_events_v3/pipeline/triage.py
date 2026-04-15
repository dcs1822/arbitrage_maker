"""
pipeline/triage.py - Estagio 1: classificacao binaria de relevancia.

Objetivo:
    Filtrar o lixo (avisos rotineiros, dividendos previsiveis, AGOs padrao)
    antes de gastar token caro com o estagio 2 (deep analysis).

Modelo: gemini-2.5-flash-lite (definido em config.LLM_TRIAGE).

Saida esperada do LLM (JSON):
    {
        "decision": "relevante" | "descartar",
        "reason":   "<frase curta em portugues>"
    }

Cache:
    Antes de chamar o LLM, calcula text_hash e consulta state.events.get_triage_cache.
    Se cacheado, devolve sem custo.
"""
from __future__ import annotations

import json

from .. import config, llm_provider
from ..state import db, events as events_state


PROMPT_TRIAGE = """Voce e um analista de eventos corporativos da bolsa brasileira.

Recebe o texto de um documento publicado por uma companhia listada na CVM.
Sua unica tarefa: classificar se este documento merece analise profunda ou
pode ser descartado.

Classifique como "relevante" (merece analise profunda) se contiver QUALQUER um:
- M&A: fusao, aquisicao, incorporacao, cisao, venda de ativo relevante
- OPA, oferta publica (qualquer tipo), tag along, art. 254-A da Lei das SAs
- Mudanca de controle, alteracao no bloco de controle, acordo de acionistas
- Reducao de capital, restituicao a acionistas, recompra relevante
- Aumento de capital, subscricao, bonus, diluicao significativa
- Conversao de classes de acoes, criacao/extincao de Units
- Distribuicao extraordinaria (dividendo extra, JCP extra) acima do recorrente
- Pedido de recuperacao judicial, default, evento de inadimplencia
- Acordo com credores, renegociacao de divida material
- Mudanca relevante na composicao acionaria (5%+) declarada na CVM
- Substituicao de controlador, novo acionista relevante
- Saida de bolsa (deslistagem, fechamento de capital)
- Qualquer fato envolvendo arbitragem entre classes ou Units
- Qualquer evento que mude materialmente o valuation ou tese da empresa

Classifique como "descartar" se for APENAS:
- Aviso de AGO/AGE rotineira sem item polemico
- Distribuicao de dividendo dentro do recorrente
- Calendario de eventos, agenda, divulgacao programada
- Aviso de release de resultados (sem o release em si)
- Atualizacao cadastral, mudanca de endereco/site/RI
- Comunicado generico de governanca, ESG ou compliance
- Aviso de pagamento de juros sobre debentures sem novidade
- Republicacao formal de documento ja existente

Em caso de duvida, prefira "relevante" - o estagio seguinte filtra o resto.

Devolva APENAS um JSON valido com o formato:
{{"decision": "relevante" OU "descartar", "reason": "<frase curta>"}}

Categoria do documento: {categoria}
Empresa: {denom} (CD_CVM {cd_cvm})

Texto do documento (truncado se muito longo):
---
{texto}
---
"""


def _build_prompt(texto: str, categoria: str, denom: str, cd_cvm: str) -> str:
    truncado = (texto or "")[: config.TRIAGE_MAX_INPUT_CHARS]
    return PROMPT_TRIAGE.format(
        categoria=categoria or "-",
        denom=denom or "-",
        cd_cvm=cd_cvm or "-",
        texto=truncado,
    )


def _parse_response(raw: str) -> tuple[str, str]:
    """Tenta extrair (decision, reason) do JSON do LLM. Tolerante a sujeira."""
    if not raw:
        return ("descartar", "resposta vazia do LLM")
    s = raw.strip()
    # Tira possivel cerca markdown
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        obj = json.loads(s)
    except Exception:
        # Fallback: procura "relevante" / "descartar" no texto cru
        low = s.lower()
        if "relevante" in low and "descartar" not in low:
            return ("relevante", s[:200])
        return ("descartar", f"json invalido: {s[:200]}")
    decision = str(obj.get("decision", "descartar")).strip().lower()
    if decision not in ("relevante", "descartar"):
        decision = "descartar"
    reason = str(obj.get("reason", ""))[:500]
    return (decision, reason)


def triage_text(
    texto: str,
    categoria: str,
    denom: str,
    cd_cvm: str,
    provider: llm_provider.LLMProvider | None = None,
) -> tuple[str, str, bool]:
    """
    Classifica um documento. Devolve (decision, reason, cache_hit).
    Usa o cache em triage_cache para evitar chamar o LLM duas vezes pelo
    mesmo texto.
    """
    if not texto or not texto.strip():
        return ("descartar", "texto vazio (PDF sem texto extraivel)", False)

    h = db.text_hash(texto)
    cached = events_state.get_triage_cache(h)
    if cached:
        return (cached["decision"], cached["reason"] or "", True)

    if provider is None:
        provider = llm_provider.get_provider()

    prompt = _build_prompt(texto, categoria, denom, cd_cvm)
    try:
        raw = provider.triage(prompt)
    except Exception as e:
        return ("descartar", f"erro LLM: {e}", False)

    decision, reason = _parse_response(raw)
    events_state.set_triage_cache(
        text_hash=h,
        decision=decision,
        reason=reason,
        model=config.LLM_TRIAGE[1],
    )
    return (decision, reason, False)
