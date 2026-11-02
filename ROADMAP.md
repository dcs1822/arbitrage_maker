# ROADMAP — Agente de eventos corporativos (Brasil + LatAm, equity e crédito)

> Documento **vivo**. Muda a cada sessão. Quando mudar direção, registre em *Decisões* e em
> *Histórico* em vez de apagar. Status: `[ ]` a fazer · `[~]` em andamento · `[x]` feito · `[?]` depende do Daniel.
>
> Última revisão: 2026-11-02 (sessão 1, escopo confirmado).

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
- [x] `arbmaker/sources/rad_collect.py` + `arbmaker/universe_cases.py` — coletor completo por empresa (cadastro → índice IPE → PDFs → DFP/ITR CSV) para as 5 empresas dos casos. Pronto; não rodou aqui por bloqueio de rede.

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

Foco acordado (2026-11-02): **responder bem os 5 casos** (WestWing, GetNinjas, Viveo, Energisa, Raízen) com os
documentos públicos das próprias empresas antes de escalar para descoberta em universo amplo.

1. `[?]` Liberar rede **ou** rodar `python -m arbmaker.sources.rad_collect` na máquina do Daniel e commitar
   `data/<slug>/index.csv`, `structured/` e `collect_report.json` (PDFs/textos ficam fora do git).
   Hosts: `dados.cvm.gov.br` (índice IPE, DFP/ITR, cadastro) e `www.rad.cvm.gov.br` (PDFs).
2. Validar `cvm_open_data` com WestWing real (comparar com os 11 períodos parseados do v3); corrigir mapeamento de contas.
3. Raízen: localizar no índice o comunicado art. 12 da SPX, estatuto (capital autorizado), documentos da REJ; preencher o caso.
4. GetNinjas, Viveo, Energisa: montar timeline a partir do índice, rodar o motor no momento detectável, fechar os casos.
5. Só depois: screener caixa líquido vs MC no universo de 20 empresas de `company_state`, e expansão do universo.

## 6. Decisões

| Data | Decisão | Motivo |
|---|---|---|
| 2026-11-02 | Nova camada `arbmaker/` ao lado de `corporate_events_v3/`, sem reescrever o v3 agora | v3 funciona para o e-mail diário; migrar por partes quando a base determinística estiver validada |
| 2026-11-02 | Motor sem LLM e sem estimativas; `MissingInput` obrigatório | pedido explícito: "não ficar chutando valores" |
| 2026-11-02 | Financeiros via CSV da CVM, não via PDF+LLM | 25/36 períodos falharam no WestWing; CSV é determinístico |
| 2026-11-02 | Casos históricos como suíte de regressão antes de mexer em prompts | sem ground truth, mudança de prompt é chute |
| 2026-11-02 | Escopo confirmado pelo Daniel: LatAm (não "OTAN"); casos Viveo (VVEO3) e Energisa ENGI3→ENGI4 | transcrição do áudio |
| 2026-11-02 | Foco: fechar os 5 casos com documentos públicos das empresas antes de escalar descoberta | proposta do Daniel; evita otimizar detecção sem ground truth |
| 2026-11-02 | Coleta por empresa = índice IPE (todas as categorias) + PDFs do RAD + DFP/ITR em CSV; `rad_collect.py` | mesmo caminho que o backtest WestWing já usou, generalizado |
| 2026-11-02 | Unidades: motor aceita qualquer unidade, desde que consistente; dados CVM normalizados para R$ mil | evitar erro de escala (UNIDADE vs MIL) |

## 7. Perguntas abertas para o Daniel

1. Fonte de preços de bonds e debêntures: Bloomberg export? Qual formato/periodicidade?
2. Formato do export Bloomberg de preços de ações (todas as classes) para substituir yfinance.
3. Lista inicial de 10–15 casos históricos que você considera "arbitragens claras".
4. Manter Gemini para o agente ou trocar? (custo, qualidade em português jurídico, tool use).
5. Raízen/SPX: os dados listados em `cases/raizen_spx_2026.json → dados_a_pedir_ao_daniel`.
6. Confirmar o valor de R$60M da redução de capital da Westwing no Fato Relevante de 2026-03-22 (hoje vem do alerta do backtest, gerado por LLM).

## 8. Bloqueios de ambiente

- Política de rede do ambiente cloud libera só gerenciadores de pacotes e GitHub. Negados com 403 no gateway (testado 2026-11-02):
  `www.rad.cvm.gov.br`, `rad.cvm.gov.br`, `dados.cvm.gov.br`, `sistemas.cvm.gov.br`, `cvmweb.cvm.gov.br`,
  `sistemaswebb3-listados.b3.com.br`, `query1.finance.yahoo.com`, `fnet.bmfbovespa.com.br`.
  Remédio: *Network access → Allowed domains* com `dados.cvm.gov.br` e `www.rad.cvm.gov.br` (mínimo), mais
  `query1.finance.yahoo.com`/`query2.finance.yahoo.com` para preços e `arquivos.b3.com.br` para aluguel.
  Alternativa: rodar o coletor na máquina do Daniel e commitar os índices/estruturados.
- Sem acesso a Bloomberg daqui: preços de bonds/debêntures e exports chegam via arquivos do Daniel.

## 9. Histórico

- **2026-11-02 · sessão 1** — Definição das 5 linhas (motor, fontes, casos, agente, screeners). Criada a camada `arbmaker/` com motor + testes, conector CVM offline, biblioteca de casos, demo WestWing e este roteiro.
