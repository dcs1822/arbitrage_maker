"""
config.py — Configuração central do corporate_events_v3.

Tudo que é parametrizável (caminhos, modelos, thresholds, env vars) vive aqui.
NUNCA hardcode chaves de API neste arquivo — use variáveis de ambiente.
"""
import os
from pathlib import Path

# =========================
# PATHS
# =========================
PROJECT_DIR = Path(r"P:\Analise\Trader\Projetos\Fato Relevante GPT\corporate_events_v3")
DATA_DIR = Path(r"P:\Analise\CVM")

# Storage interno do v3
STORAGE_DIR = PROJECT_DIR / "storage"
DB_PATH = STORAGE_DIR / "events_v3.sqlite"
STATE_DIR = STORAGE_DIR / "state"          # snapshot JSON por empresa
PDF_CACHE_DIR = DATA_DIR / "PDF_v3"
LOG_PATH = STORAGE_DIR / "v3.log"

# Fontes externas (somente leitura)
BLOOMBERG_TICKERS_PATH = Path(r"P:\Transf_Bloomberg\Daniel\dferfr.txt")
CADASTRO_CVM_XLSX = Path(r"P:\Analise\CVM\Cadastro CVM.xlsx")
CAD_CIA_ABERTA_CSV = Path(r"P:\Analise\Trader\Projetos\ANBIMA\IB\Arquivo_Anbima\cad_cia_aberta.csv")

# =========================
# UNIVERSO INVESTÍVEL
# =========================
EXCHANGES_INVESTIBLE = {"BZ"}              # só B3 (descarta ADRs em US)
MAX_MARKET_CAP_BRL = 1_000_000_000         # filtro: small caps até R$ 1bi (uso futuro)
INCLUDE_FIIS = False                       # FIIs entram em fase 2 (regime distinto)

# --- Universo de teste do incremento 2 ---
# Substitui o filtro por market cap durante a calibracao do pipeline.
# Trabalhamos com 20 empresas: as curadas abaixo + sorteio do pool TIER 1/2.
TICKERS_CURADOS = [
    "RENT3", "RDNI3", "TKNO4", "WEST3", "SHOW3",
    "ZAMP3", "ENGI11", "ALPA4",
]
TARGET_UNIVERSE_SIZE = 20
RANDOM_SEED = 42                           # muda este numero para sortear de novo

# Auditoria de tickers nao reconhecidos
UNKNOWNS_LOG_PATH = Path(r"P:\Analise\CVM\v3_unknowns.txt")

# =========================
# LLM PROVIDER
# =========================
LLM_PROVIDER = "gemini"                    # gemini | openai | anthropic

# (provider, model_id) por estágio do pipeline
LLM_TRIAGE = ("gemini", "gemini-2.5-flash-lite")
LLM_DEEP   = ("gemini", "gemini-2.5-pro")

# Limites de tamanho
TRIAGE_MAX_INPUT_CHARS    = 12_000
DEEP_MAX_INPUT_CHARS      = 60_000
TRIAGE_MAX_OUTPUT_TOKENS  = 300
# Gemini 2.5 pro consome thinking tokens do mesmo orcamento de output.
# Usamos 8000 + thinking_budget separado para evitar respostas truncadas.
DEEP_MAX_OUTPUT_TOKENS    = 8_000
DEEP_THINKING_BUDGET      = 2_000   # tokens reservados p/ 'thinking' (None = auto, 0 = off)
DEEP_MAX_RETRIES          = 3       # retries em 503 / timeouts
DEEP_RETRY_BACKOFF_S      = 4.0     # backoff base em segundos (dobra a cada retry)

# API keys (SEMPRE via env var)
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")
OPENAI_API_KEY  = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# =========================
# CVM — categorias monitoradas
# =========================
CATEGORIAS_CVM = {
    "IPE_4_-1_-1":  "Fatos Relevantes",
    "IPE_-1_84_-1": "Outros Avisos",
    "IPE_3_-1_-1":  "Avisos aos Acionistas",
    "IPE_48_-1_-1": "Avisos aos Debenturistas",
}

# =========================
# NOTIFICAÇÕES
# =========================
EMAIL_DESTINO = "ds@bogaricapital.com.br"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_IDS: list[str] = []

# =========================
# RUNTIME UTILS
# =========================
def ensure_dirs() -> None:
    """Garante que todos os diretórios de storage existam."""
    for d in [STORAGE_DIR, STATE_DIR, PDF_CACHE_DIR]:
        d.mkdir(parents=True, exist_ok=True)
