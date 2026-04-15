"""
pipeline/analyzer.py - Estagio 2: analise profunda com contexto injetado.

Objetivo:
    Para eventos marcados como 'relevante' no estagio 1, chamar um LLM mais
    capaz (gemini-2.5-pro) com:
        - texto do documento (ate DEEP_MAX_INPUT_CHARS)
        - contexto da empresa (company_state.context_snippet)
        - instrucoes estruturadas para devolver JSON padronizado

Saida esperada do LLM (JSON):
    {
        "tipo_evento": "<um dos enumerados>",
        "severidade": <1..10>,
        "urgencia": "alta" | "media" | "baixa",
        "resumo": "<1 frase>",
        "detalhes": "<paragrafo curto com numeros>",
        "flags": ["opa_254a", "reducao_capital", ...],
        "precisa_acao": true|false,
        "prazo_acao": "YYYY-MM-DD" | null,
        "impacto_tese": "<como isso afeta a tese da empresa>",
        "conexao_com_contexto": "<como isso se relaciona com o snapshot da empresa>",
        "confianca": "alta" | "media" | "baixa"
    }

Tipos de evento reconhecidos:
    opa, m&a, reducao_capital, aumento_capital, deslistagem,
    reorg_societaria, dividendo_extra, units_arbitrage, recompra,
    mudanca_controle, recuperacao_judicial, outro
"""
from __future__ import annotations

import json

from .. import config, llm_provider
from ..state import company as company_state


TIPOS_EVENTO = [
    "opa",
    "m&a",
    "reducao_capital",
    "aumento_capital",
    "deslistagem",
    "reorg_societaria",
    "dividendo_extra",
    "units_arbitrage",
    "recompra",
    "mudanca_controle",
    "recuperacao_judicial",
    "outro",
]


PROMPT_DEEP = """Voce e um analista de eventos corporativos senior na Bogari
Capital. Recebe um documento publicado na CVM por uma empresa listada e
precisa produzir uma analise estruturada e acionavel para um gestor.

Sua resposta DEVE ser um JSON valido (apenas o JSON, sem markdown, sem texto
antes ou depois) no seguinte formato:

{{
  "tipo_evento": "<um dos valores permitidos>",
  "severidade": <inteiro de 1 a 10>,
  "urgencia": "alta" | "media" | "baixa",
  "resumo": "<uma frase curta em portugues>",
  "detalhes": "<ate 4 frases com os numeros principais: valores, prazos, percentuais, partes envolvidas>",
  "flags": ["<lista de flags curtas tipo opa_254a, cash_gt_mc, tag_along, reducao_capital>"],
  "precisa_acao": true | false,
  "prazo_acao": "YYYY-MM-DD" ou null,
  "impacto_tese": "<frase sobre como isso muda ou confirma a tese da empresa>",
  "conexao_com_contexto": "<frase ligando o evento ao contexto fornecido. Se o contexto nao ajudar, diga 'sem conexao relevante'>",
  "confianca": "alta" | "media" | "baixa"
}}

Valores permitidos para tipo_evento (escolha EXATAMENTE um):
  opa, m&a, reducao_capital, aumento_capital, deslistagem, reorg_societaria,
  dividendo_extra, units_arbitrage, recompra, mudanca_controle,
  recuperacao_judicial, outro

Calibracao de severidade (inteiro 1..10):
  10 - Evento transformacional confirmado (OPA fechada, mudanca de controle, RJ)
  8-9 - Evento quase certo mas ainda em execucao (OPA anunciada, M&A assinado)
  6-7 - Evento material anunciado (reducao de capital relevante, reorg)
  4-5 - Evento recorrente mas maior que o normal (dividendo extra grande, recompra grande)
  2-3 - Aviso com leve mudanca (retificacao, ajuste de data)
  1   - Ruido que escapou da triagem

Regras especiais (marque flag correspondente se aplicavel):
  - Se a empresa tem "caixa > MC" no contexto E o documento fala de redistribuicao
    de caixa (reducao_capital, dividendo extraordinario grande, recompra acima
    do normal): flag "cash_gt_mc_trigger" e severidade >= 7 automaticamente.
  - Se envolver Units e mudanca de ratio ou conversao: flag "units_ratio".
  - Se mencionar art. 254-A da Lei 6.404: flag "opa_254a" e severidade >= 8.
  - Se o contexto mostra controlador acumulando E o documento eh um CVM 44
    ou similar: flag "controlador_acumulando".

Contexto da empresa (snapshot do estado interno):
---
{contexto}
---

Categoria do documento na CVM: {categoria}

Texto do documento (truncado se muito longo):
---
{texto}
---

Lembre: retorne APENAS o JSON, comecando por {{ e terminando em }}."""


def _build_prompt(texto: str, categoria: str, contexto: str) -> str:
    truncado = (texto or "")[: config.DEEP_MAX_INPUT_CHARS]
    return PROMPT_DEEP.format(
        contexto=contexto or "(sem contexto)",
        categoria=categoria or "-",
        texto=truncado,
    )


def _strip_markdown_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    return s


def _parse_response(raw: str) -> dict:
    """
    Tenta fazer parse do JSON. Tolerante a cercas markdown e texto extra.
    Devolve dict vazio se impossivel.
    """
    if not raw:
        return {}
    s = _strip_markdown_fences(raw)
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # Fallback: tenta achar o primeiro { ate o ultimo }
    try:
        i = s.index("{")
        j = s.rindex("}")
        return json.loads(s[i : j + 1])
    except Exception:
        return {}


def _coerce(obj: dict) -> dict:
    """Normaliza / valida os campos esperados, com defaults seguros."""
    tipo = str(obj.get("tipo_evento") or "outro").strip().lower()
    if tipo not in TIPOS_EVENTO:
        tipo = "outro"

    try:
        severidade = int(obj.get("severidade") or 0)
    except Exception:
        severidade = 0
    severidade = max(1, min(10, severidade)) if severidade else 1

    urgencia = str(obj.get("urgencia") or "baixa").strip().lower()
    if urgencia not in ("alta", "media", "baixa"):
        urgencia = "baixa"

    flags = obj.get("flags") or []
    if not isinstance(flags, list):
        flags = [str(flags)]
    flags = [str(f).strip() for f in flags if str(f).strip()]

    precisa_acao = bool(obj.get("precisa_acao") or False)
    prazo = obj.get("prazo_acao")
    if prazo in ("", "null", "None"):
        prazo = None

    return {
        "tipo_evento": tipo,
        "severidade": severidade,
        "urgencia": urgencia,
        "resumo": str(obj.get("resumo") or "")[:500],
        "detalhes": str(obj.get("detalhes") or "")[:2000],
        "flags": flags,
        "precisa_acao": precisa_acao,
        "prazo_acao": prazo,
        "impacto_tese": str(obj.get("impacto_tese") or "")[:1000],
        "conexao_com_contexto": str(obj.get("conexao_com_contexto") or "")[:1000],
        "confianca": str(obj.get("confianca") or "media").strip().lower(),
    }


def analyze_event(
    texto: str,
    categoria: str,
    cd_cvm: str,
    provider: llm_provider.LLMProvider | None = None,
) -> dict:
    """
    Roda o estagio 2 num evento. Devolve dict normalizado (sempre preenchido).
    Adiciona o campo '_raw_llm' para debug e '_ok' indicando se o JSON veio
    bem formado.
    """
    if not texto or not texto.strip():
        return {
            **_coerce({}),
            "resumo": "documento sem texto extraivel",
            "_raw_llm": "",
            "_ok": False,
        }

    if provider is None:
        provider = llm_provider.get_provider()

    contexto = company_state.context_snippet(cd_cvm)
    prompt = _build_prompt(texto, categoria, contexto)

    try:
        raw = provider.analyze(prompt, json_mode=True)
    except Exception as e:
        return {
            **_coerce({}),
            "resumo": f"erro no LLM: {e}",
            "_raw_llm": "",
            "_ok": False,
        }

    parsed = _parse_response(raw)
    ok = bool(parsed)
    result = _coerce(parsed)
    result["_raw_llm"] = raw
    result["_ok"] = ok
    return result
