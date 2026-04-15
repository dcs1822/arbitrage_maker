"""
pipeline/fetcher.py - Coleta de documentos da CVM via RAD.

Adaptado do v2 (comporate_event_v2.py) com:
    - Cache de PDFs em config.PDF_CACHE_DIR (caminho deterministico por hash do link)
    - Estrutura tipada (dataclass CvmDoc)
    - Funcoes pequenas e isoladas (listar / baixar / extrair texto)

Nao tem deduplicacao aqui dentro - quem orquestra (test/main_daily) consulta
a tabela `events` para saber se um link ja foi processado.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF
import requests

from .. import config


HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Content-Type": "application/json; charset=UTF-8",
    "Origin": "https://www.rad.cvm.gov.br",
    "Referer": "https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}

LIST_URL = "https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx/ListarDocumentos"

# Template do payload (pseudo-JSON que o endpoint aceita).
# Chaves duplicadas {{ }} sao escapes do .format() para emitir { } literais.
_PAYLOAD_TPL = (
    "{{"
    "dataDe: '{di}', dataAte: '{df}' , empresa: ',{cd}', "
    "setorAtividade: '-1', categoriaEmissor: '-1', situacaoEmissor: '-1', "
    "tipoParticipante: '-1', dataReferencia: '', categoria: '{cat}', "
    "periodo: '2', horaIni: '', horaFim: '', palavraChave:'',"
    "ultimaDtRef:'false', tipoEmpresa:'0', token: '', versaoCaptcha: ''"
    "}}"
)


@dataclass
class CvmDoc:
    cd_cvm: str
    categoria_codigo: str
    categoria_nome: str
    link: str


def listar_documentos(
    cd_cvm: str,
    data_inicial: date,
    data_final: date,
    categoria_codigo: str,
) -> list[str]:
    """
    Consulta o RAD/CVM e devolve lista de URLs de download dos documentos
    de uma categoria, para a empresa, no intervalo de datas.
    """
    body = _PAYLOAD_TPL.format(
        di=str(data_inicial),
        df=str(data_final),
        cd=cd_cvm,
        cat=categoria_codigo,
    )
    try:
        r = requests.post(LIST_URL, headers=HEADERS, data=body, timeout=60)
        if r.status_code != 200:
            return []
        j = r.json()
    except Exception:
        return []

    links: list[str] = []
    try:
        dados_html = (j.get("d") or {}).get("dados") or ""
        if not dados_html:
            return []
        for match in re.findall(r"OpenDownloadDocumentos\(([^)]+)\)", dados_html):
            params = match.replace("'", "").split(",")
            if len(params) >= 4:
                num_seq, cod_inst, num_proto, desc_tipo = params[:4]
                num_seq = num_seq.strip()
                cod_inst = cod_inst.strip()
                num_proto = num_proto.strip()
                desc_tipo = desc_tipo.strip()
                link = (
                    "https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx"
                    f"?Tela=ext&descTipo={desc_tipo}"
                    f"&CodigoInstituicao={cod_inst}"
                    f"&numProtocolo={num_proto}"
                    f"&numSequencia={num_seq}"
                    f"&numVersao=1"
                )
                links.append(link)
    except Exception:
        pass
    return links


def listar_todas_categorias(
    cd_cvm: str,
    data_inicial: date,
    data_final: date,
) -> list[CvmDoc]:
    """Consulta TODAS as categorias de config.CATEGORIAS_CVM e agrega o resultado."""
    out: list[CvmDoc] = []
    for cat_codigo, cat_nome in config.CATEGORIAS_CVM.items():
        for link in listar_documentos(cd_cvm, data_inicial, data_final, cat_codigo):
            out.append(
                CvmDoc(
                    cd_cvm=cd_cvm,
                    categoria_codigo=cat_codigo,
                    categoria_nome=cat_nome,
                    link=link,
                )
            )
        time.sleep(0.05)  # gentil com a CVM
    return out


def baixar_pdf(url: str, dest: Path) -> bool:
    """Baixa um PDF e grava em disco. Retorna True se sucesso."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(url, stream=True, timeout=120)
        if r.status_code != 200:
            return False
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return True
    except Exception:
        return False


def extrair_texto(pdf_path: Path) -> str:
    """Extrai texto de um PDF via PyMuPDF. Devolve string vazia em qualquer erro."""
    try:
        doc = fitz.open(str(pdf_path))
        texto_paginas = []
        for pagina in doc:
            texto_paginas.append(pagina.get_text())
        doc.close()
        return "".join(texto_paginas)
    except Exception:
        return ""


def pdf_path_for(cd_cvm: str, link: str) -> Path:
    """
    Caminho deterministico para cachear um PDF, derivado do hash do link.
    Sempre o mesmo arquivo para o mesmo link, entre execucoes.
    """
    h = hashlib.sha1(link.encode("utf-8")).hexdigest()[:12]
    return config.PDF_CACHE_DIR / f"{cd_cvm}_{h}.pdf"
