# Arbitrage Maker

Sistema de monitoramento de eventos corporativos da CVM para identificar oportunidades de investimento (special situations, arbitragens, ativismo).

## Arquitetura

```
corporate_events_v3/          # Core do sistema
  pipeline/                   # Coleta e triagem de documentos CVM
    fetcher.py                # Download de docs CVM (IPE)
    triage.py                 # Classificacao por severidade
    analyzer.py               # Analise LLM de eventos
  state/                      # Estado persistente
    company.py                # Modelo de empresa
    events.py                 # Modelo de eventos
    db.py                     # SQLite persistence
  agente_avaliacao.py         # Agente Analista Senior (tese de investimento)
  backtest_westwing.py        # Coleta + backtest historico WestWing
  backtest_integrated.py      # Backtest: eventos avaliados contra tese vigente
  extract_structured_data.py  # Extracao de DFs, acionario, estatuto via LLM
  config.py                   # Configuracoes
  llm_provider.py             # Abstracoes LLM (Gemini)
  universe.py                 # Universo de empresas monitoradas

data/westwing/                # Dados estruturados do backtest WestWing
  structured/                 # Financeiros, acionario, estatuto, precos
  thesis/                     # 13 teses trimestrais (2021-2026)
  backtest/                   # Resultados do backtest de eventos
  backtest_integrated/        # Alertas integrados (evento + tese)
  context_samples/            # Exemplos de contexto extraido
```

## Pipeline

```
CVM Docs (PDF) --> Extracao Texto --> Triagem (severidade)
                                         |
                                         v
                           Extracao Estruturada (LLM)
                           - DRE, Balanco, FCF
                           - Composicao acionaria
                           - Estatuto social
                                         |
                                         v
                           Company Snapshot (trimestral)
                                         |
                                         v
                           Agente de Avaliacao (tese)
                           - Recomendacao: comprar/monitorar/evitar
                           - Valuation: MC, caixa, EV/EBITDA
                           - Governanca: score 1-10, red flags
                           - Triggers: eventos que mudam a tese
                                         |
                                         v
                           Agente de Eventos (alerta)
                           - Novo doc CVM vs tese vigente
                           - Confirma/contradiz/novo fator
                           - Alerta com contexto de valuation
```

## Backtest WestWing (WEST3)

Case study completo: reconstrucao historica de 2021-2026 para validar se o sistema teria identificado a oportunidade de special situation.

**Resultado**: O agente identificou corretamente:
- Entrada do ativista WNT (nov/2022, sev=6)
- Crise de governanca com renuncias em cadeia (2023)
- Caixa > Market Cap como "special situation" (Q4/2022)
- Proposta de reducao de capital R$60M (mar/2026, sev=9)

## Setup

```bash
pip install -r requirements.txt
export GEMINI_API_KEY="sua_chave_aqui"
```

## Uso

```bash
# Coleta completa de docs CVM de uma empresa
python corporate_events_v3/backtest_westwing.py --step collect

# Extracao estruturada (financeiros, acionario, estatuto)
python corporate_events_v3/extract_structured_data.py --step all

# Gerar tese de investimento para uma data
python corporate_events_v3/agente_avaliacao.py --date 2023-06-30

# Backtest completo de teses trimestrais
python corporate_events_v3/agente_avaliacao.py --backtest

# Backtest integrado (eventos vs tese)
python corporate_events_v3/backtest_integrated.py
```
