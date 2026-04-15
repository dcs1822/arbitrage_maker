"""
pipeline - Estagios de processamento dos documentos CVM.

Submodulos:
    fetcher    - download e extracao dos PDFs do RAD/CVM
    triage     - estagio 1: classificacao binaria de relevancia (LLM barato)
    analyzer   - estagio 2: analise profunda com contexto (LLM forte) - incremento 5
"""
