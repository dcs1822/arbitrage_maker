# ROADMAP — Agente de eventos corporativos (Brasil + LatAm, equity e crédito)

> Documento **vivo**. Muda a cada sessão. Quando mudar direção, registre em *Decisões* e em
> *Histórico* em vez de apagar. Status: `[ ]` a fazer · `[~]` em andamento · `[x]` feito · `[?]` depende do Daniel.
>
> Última revisão: 2026-11-02 (sessão 1).

## 1. Objetivo

Um analista de eventos corporativos que, a partir de informação pública (CVM, B3, bonds offshore),
encontre arbitragens e teses de special situations em **ações e dívida** e consiga discutir casos
novos com o Daniel sem chutar número. Exemplos-alvo: GetNinjas, Westwing, Viveo, troca ON/PN
(Energisa), conversão dívida→equity, bonds abaixo do par vs. equity positivo (Raízen/SPX),
assembleias onde alguém monta posição para votar.

## 2. Princípios (não negociáveis)

1. **Conta em código, narrativa no LLM.** Toda métrica sai de `arbmaker/calc`. O LLM extrai inputs e escreve.
2. **Input faltando = pedir, nunca estimar.** O motor levanta `MissingInput` com a lista exata. O agente repassa o pedido ao Daniel.
3. **Todo número tem fonte e data.** `Result.with_sources(...)`. Sem fonte, não entra em tese.
4. **Reconciliação explícita.** Checks em cada cálculo (ações × preço = MC; waterfall soma o EV; TERP entre preços).
5. **Casos históricos são o teste.** Nenhuma mudança de prompt ou regra entra sem rodar a regressão de casos (`cases/`).

## 3. Estado atual

**Já existia (corporate_events_v3):** coleta RAD/CVM de 4 categorias IPE, triagem (flash-lite), análise profunda (pro),
agente de tese trimestral, backtest WestWing (eventos vs. tese). Limitações encontradas na sessão 1:

- Extração de DFP/ITR por LLM a partir de PDF falhou em 25 de 36 períodos (campo `raw`).
- Não coleta Comunicado de Participação Relevante (Res. CVM 44 art. 12), insiders (art. 11), editais/mapas de AGE, FRE, debêntures, RJ/REJ.
- Preços só de WEST3 via yfinance; sem classes, Units, aluguel, bonds.
- Valuation gerado em texto livre pelo LLM (target price, probabilidades) sem conta auditável.
- Caminhos hardcoded de Windows (`P:\`, `C:\Agent`) nos módulos antigos.

**Feito na sessão 1 (esta):**

- [x] `arbmaker/calc` — motor determinístico: `capital_structure` (MC, EV, waterfall, EV implícito por bond, cross-check bond×equity),
  `conversion` (dívida→equity, breakeven entre comprar ação ou dívida), `parity` (ON/PN com aluguel e dividendos; Units),
  `tender` (OPA, tag along 254-A, recesso), `capital_ops` (TERP/direitos, redução de capital, caixa vs MC), `merger` (relação de troca).
- [x] `tests/test_calc.py` — 20 testes com valores conferidos à mão.
- [x] `arbmaker/sources/cvm_open_data.py` — conector dos CSVs oficiais (DFP/ITR/IPE/FRE/CAD) com mapeamento do plano de contas,
  reapresentações, escala, trimestre vs acumulado, EBITDA via DVA, filtro IPE por padrão (participação relevante, art. 11, AGE, RJ...).
  Testado offline com CSV sintético (3 testes). **Rede bloqueada nesta sessão: validar contra arquivo real.**
- [x] `cases/` — schema + WestWing (fechado parcial, conta pelo motor) + esqueletos GetNinjas, Viveo, Energisa + caso vivo Raízen/SPX com hipóteses e lista de dados a pedir.
- [x] `arbmaker/examples/westwing_reducao_capital.py` — demo com dados reais do repo (pede dívida que falta; calcula a redução de capital).

## 4. Fases

### Fase 0 — Fundação (sessão 1) `[x]`
Critério de pronto: motor com testes, conector offline, schema de casos, roteiro. **Atingido.**

### Fase 1 — Base de dados determinística `[~]`
Objetivo: nenhum número financeiro vem de LLM.
- [ ] Rodar `cvm_open_data` contra arquivos reais (DFP/ITR 2021–2026) e validar o mapeamento de contas com WestWing (comparar com os 11 períodos parseados). `[?]` precisa liberar `dados.cvm.gov.br` no ambiente ou copiar os zips de `P:\Analise\CVM`.
- [ ] Substituir `extract_structured_data.py` (LLM) pelo conector para DFP/ITR; LLM só para estatuto e acionário.
- [ ] Substituir a lista de categorias RAD por IPE do portal (tem tudo com link) + manter RAD para intradiário.
- [ ] Adicionar: participação relevante (art. 12), insiders (art. 11), editais/propostas/boletim/mapa de AGE, avisos a debenturistas, documentos de RJ/REJ.
- [ ] FRE: seções 15 (acionistas), 18 (valores mobiliários), 22 (negócios extraordinários) via `fre_cia_aberta` CSV.
- [ ] Preços: todas as classes + Units (yfinance como fallback; export Bloomberg do Daniel como fonte primária). `[?]` formato do export.
- [ ] Aluguel B3: posição em aberto e taxa por ticker (arquivo diário de empréstimo de ativos).
- [ ] Cadastro: nome ↔ CD_CVM ↔ CNPJ ↔ tickers (cad_cia_aberta + arquivo Bloomberg já existente em `universe.py`).
- [ ] Tirar os caminhos Windows hardcoded; config por env/arquivo.

### Fase 2 — Casos históricos + regressão `[ ]`
Objetivo: 15–30 casos fechados; harness "as of" que mede detecção, atraso e reconciliação.
- [ ] Preencher GetNinjas, Viveo, Energisa com documentos reais (IPE) e preços. `[?]` confirmar nomes/tickers.
- [ ] Escolher mais 10–15 casos (sugestões: OPAs com 254-A, fechamentos de capital, reduções de capital, conversões de debêntures, Units com prêmio, RJ com conversão). `[?]` lista do Daniel.
- [ ] `arbmaker/regression.py`: roda agente as-of em cada data da timeline, compara com `momento_detectavel`, gera placar.
- [ ] Métricas: recall por tipo de evento, atraso mediano em dias, % de contas que reconciliam, falsos positivos por mês.

### Fase 3 — Screeners quantitativos `[ ]`
Objetivo: detectar sem depender de texto.
- [ ] Paridade ON/PN/Unit vs histórico (z-score) e vs regra de conversão.
- [ ] Caixa líquido > MC (com queima de caixa dos últimos 12m).
- [ ] EV visto pelo equity vs EV visto pelo bond (gap) para empresas com bond < 70.
- [ ] Spread de OPA anunciada vs preço; recesso vs preço em reorganizações.
- [ ] Salto de aluguel/posição tomada antes de AGE; cruzamento de 5% vs poison pill do estatuto.
- [ ] Direitos de subscrição vs teórico (TERP).

### Fase 4 — Agente conversacional `[ ]`
Objetivo: "trocar ideia" com ferramentas e sem chute.
- [ ] Ferramentas: buscar docs (IPE/RAD), financeiros, preços, aluguel, `calc.*`, carregar caso, **pedir_dados** (devolve checklist com ISIN/data/fonte).
- [ ] Tese como objeto versionado: inputs + fórmulas + narrativa; novo dado recalcula, não reescreve.
- [ ] Lista de hipóteses abertas por empresa com "documento que confirma / derruba" (modelo em `cases/raizen_spx_2026.json`).
- [ ] Base de regras: Lei 6.404 (direitos de 5% e 10%, 254-A, recesso, redução de capital art. 173/174), Res. CVM 44/85/160, regulamento de Units, Novo Mercado.
- [ ] Decidir provedor LLM para o agente (hoje Gemini no v3). `[?]`

### Fase 5 — Crédito e LatAm `[ ]`
- [ ] Bonds offshore: termos (prospecto Luxemburgo/Irlanda), preço (fonte do Daniel), cupom, senioridade, covenants.
- [ ] Debêntures locais: escrituras, AGD, preço secundário (ANBIMA/REUNE).
- [ ] Extensão para emissores LatAm (fontes equivalentes à CVM: CNV, CMF, SMV; bonds 144A/RegS).

## 5. Backlog imediato (próxima sessão)

1. `[?]` Liberar `dados.cvm.gov.br` no ambiente **ou** subir os zips DFP/ITR/IPE 2021–2026 para `data/cvm_raw/` (gitignored).
2. Validar `cvm_open_data` com WestWing real; corrigir mapeamento de contas se necessário.
3. Buscar no IPE o comunicado art. 12 da SPX em Raízen e preencher `cases/raizen_spx_2026.json` com os dados que o Daniel passar.
4. Preencher `cases/getninjas_2023.json` com documentos reais.
5. Primeiro screener: caixa líquido vs MC para o universo de 20 empresas já em `company_state`.

## 6. Decisões

| Data | Decisão | Motivo |
|---|---|---|
| 2026-11-02 | Nova camada `arbmaker/` ao lado de `corporate_events_v3/`, sem reescrever o v3 agora | v3 funciona para o e-mail diário; migrar por partes quando a base determinística estiver validada |
| 2026-11-02 | Motor sem LLM e sem estimativas; `MissingInput` obrigatório | pedido explícito: "não ficar chutando valores" |
| 2026-11-02 | Financeiros via CSV da CVM, não via PDF+LLM | 25/36 períodos falharam no WestWing; CSV é determinístico |
| 2026-11-02 | Casos históricos como suíte de regressão antes de mexer em prompts | sem ground truth, mudança de prompt é chute |
| 2026-11-02 | Unidades: motor aceita qualquer unidade, desde que consistente; dados CVM normalizados para R$ mil | evitar erro de escala (UNIDADE vs MIL) |

## 7. Perguntas abertas para o Daniel

1. "OTAN" no áudio = LatAm? "Vigio" = Viveo? "NG3 pra Indy4" = ENGI3→ENGI4?
2. Fonte de preços de bonds e debêntures: Bloomberg export? Qual formato/periodicidade?
3. Formato do export Bloomberg de preços de ações (todas as classes) para substituir yfinance.
4. Lista inicial de 10–15 casos históricos que você considera "arbitragens claras".
5. Manter Gemini para o agente ou trocar? (custo, qualidade em português jurídico, tool use).
6. Raízen/SPX: os dados listados em `cases/raizen_spx_2026.json → dados_a_pedir_ao_daniel`.
7. Confirmar o valor de R$60M da redução de capital da Westwing no Fato Relevante de 2026-03-22 (hoje vem do alerta do backtest, gerado por LLM).

## 8. Bloqueios de ambiente

- `dados.cvm.gov.br` negado pela política de rede do ambiente (403 no proxy). Liberar em *Network access → Allowed domains* ou trabalhar offline com zips.
- Sem acesso a Bloomberg/B3 daqui: dados chegam via export do Daniel.

## 9. Histórico

- **2026-11-02 · sessão 1** — Definição das 5 linhas (motor, fontes, casos, agente, screeners). Criada a camada `arbmaker/` com motor + testes, conector CVM offline, biblioteca de casos, demo WestWing e este roteiro.
