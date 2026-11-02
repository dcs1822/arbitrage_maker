# Biblioteca de casos (ground truth)

Cada caso e um JSON em `cases/<id>.json`. Serve para tres coisas:

1. **Regressao**: rodar o agente "as of" cada data e medir se detectou, com quantos dias de atraso,
   e se os numeros reconciliaram.
2. **Memoria**: o agente conversacional cita casos parecidos quando discute uma situacao nova.
3. **Calibracao de severidade**: o que de fato moveu preco vs o que foi ruido.

Status `aberto` = caso vivo, em acompanhamento (ex: Raizen/SPX). Status `fechado` = evento concluido.
Status `esqueleto` = so a estrutura; precisa de dados do Daniel antes de entrar na regressao.

## Schema

```json
{
  "id": "slug_unico",
  "status": "fechado | aberto | esqueleto",
  "empresa": "Nome",
  "tickers": ["WEST3"],
  "cd_cvm": "25518",
  "tipos_evento": ["ativismo", "caixa_gt_mc", "reducao_capital"],
  "instrumentos": ["acao ON"],
  "resumo": "2-4 frases: qual era a assimetria e como se resolveu",
  "timeline": [
    {"data": "YYYY-MM-DD", "documento": "Fato Relevante", "fonte": "link ou caminho", "o_que_mudou": "...", "severidade_real": 1-10}
  ],
  "momento_detectavel": {"data": "YYYY-MM-DD", "documento": "...", "por_que": "qual dado tornou a conta possivel"},
  "conta_no_momento": {"calculo": "arbmaker.calc.<modulo>.<funcao>", "inputs": {}, "outputs": {}, "fontes": {}},
  "resultado": {"preco_na_deteccao": 0, "data_resultado": "", "preco_resultado": 0, "retorno_pct": 0, "dias": 0, "o_que_resolveu": ""},
  "licoes": ["o que o agente precisa saber para pegar o proximo parecido"],
  "dados_que_faltaram": ["o que teria melhorado a conta"],
  "confirmar_com_daniel": ["fatos que foram inferidos e precisam de confirmacao"]
}
```

Regras:
- Numeros em `conta_no_momento` sao saida do motor (`arbmaker.calc`), nunca digitados a mao.
- Toda data e a data de **publicacao** do documento, nao a data do evento.
- `confirmar_com_daniel` nao pode ficar vazio num caso `esqueleto`.

## Casos

| id | status | tipo | nota |
|---|---|---|---|
| westwing_2022_2026 | fechado (parcial) | ativismo, caixa > MC, reducao de capital | dados do repo; conta pelo motor |
| getninjas_2023 | esqueleto | caixa > MC, reducao de capital, ativismo | confirmar valores |
| viveo_2025 | esqueleto | reestruturacao de divida, conversao | Viveo (VVEO3), confirmado |
| energisa_on_pn | esqueleto | paridade de classes | ENGI3 -> ENGI4, confirmado |
| raizen_spx_2026 | aberto | credito distressed x equity, participacao relevante | lista de dados a pedir |
