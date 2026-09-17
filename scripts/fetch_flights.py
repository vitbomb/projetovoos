# scripts/fetch_flights.py
# -*- coding: utf-8 -*-

"""
Script que consulta a API pública SIROS/ANAC, filtra voos por aeroportos,
elimina duplicados conforme a constraint do banco, e faz upsert em lote
na tabela public.voos do Supabase.
"""

import os
import sys
import datetime
from typing import List, Dict, Tuple

import requests
from supabase import create_client, Client


# ----------------------------------------------------------------------
# Configuração das variáveis de ambiente
# ----------------------------------------------------------------------
SUPABASE_URL: str | None = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY: str | None = os.getenv("SUPABASE_SERVICE_KEY")
if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("Variáveis SUPABASE_URL e SUPABASE_SERVICE_KEY são obrigatórias.")
    sys.exit(1)

AIRPORTS_ENV: str | None = os.getenv("AIRPORTS")
AIRPORTS: List[str] = [icao.strip().upper() for icao in (AIRPORTS_ENV or "SBCA").split(",")]


# ----------------------------------------------------------------------
# Cliente Supabase
# ----------------------------------------------------------------------
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ----------------------------------------------------------------------
# Funções de negócio
# ----------------------------------------------------------------------
def buscar_voos_api() -> List[Dict]:
    """
    Consulta a API SIROS/ANAC e devolve a lista de voos retornados.
    """
    hoje: str = datetime.datetime.now().strftime("%d%m%Y")
    url: str = "https://sas.anac.gov.br/sas/siros_api/voos"
    try:
        resp = requests.get(url, params={"dataReferencia": hoje}, timeout=10)
    except requests.RequestException as e:
        print(f"Erro de rede ao consultar SIROS: {e}")
        sys.exit(1)

    if resp.status_code != 200:
        print(f"Erro ao obter dados da SIROS: {resp.status_code}")
        sys.exit(1)

    try:
        data = resp.json()
    except ValueError:
        print("Resposta inválida da SIROS (não é JSON).")
        sys.exit(1)

    if not isinstance(data, list):
        print("Formato inesperado da resposta da SIROS: deve ser lista.")
        sys.exit(1)

    return data


def filtrar_por_aeroportos(voos: List[Dict]) -> List[Dict]:
    """
    Mantém voos cujo aeroporto de origem ou de destino esteja na lista AIRPORTS.
    """
    return [
        voo
        for voo in voos
        if voo.get("sg_icao_origem") in AIRPORTS
        or voo.get("sg_icao_destino") in AIRPORTS
    ]


def deduplicar_voos(voos: List[Dict]) -> List[Dict]:
    """
    Remove voos duplicados com base na chave da constraint UNIQUE do banco.
    """
    vistos: set[Tuple] = set()
    result: List[Dict] = []

    for voo in voos:
        chave = (
            voo.get("data_referencia"),
            voo.get("sg_empresa_icao"),
            voo.get("nr_voo"),
            voo.get("nr_etapa"),
            voo.get("sg_icao_origem"),
            voo.get("sg_icao_destino"),
            voo.get("dt_partida_prevista_utc"),
        )
        if chave not in vistos:
            vistos.add(chave)
            result.append(voo)

    return result


def mapear_para_estrutura(voo: Dict) -> Dict:
    """
    Converte o dicionário da API para a estrutura de dados da tabela public.voos.
    """
    return {
        "data_referencia": voo.get("data_referencia"),  # data já deve estar no formato YYYY-MM-DD
        "codigo_icao_empresa": voo.get("sg_empresa_icao"),
        "numero_voo": voo.get("nr_voo"),
        "etapa": voo.get("nr_etapa"),
        "aeroporto_icao_origem": voo.get("sg_icao_origem"),
        "aeroporto_icao_destino": voo.get("sg_icao_destino"),
        "horario_previsto_partida": voo.get("dt_partida_prevista_utc"),
        "horario_previsto_chegada": voo.get("dt_chegada_prevista_utc"),
        "equipamento": voo.get("sg_equipamento_icao"),
        "quantidade_assentos": voo.get("qt_assentos_previstos"),
        "tipo_operacao": None,          # não fornecido pela API
        "tipo_servico": voo.get("ds_tipo_servico"),
    }


def enviar_para_supabase(voos: List[Dict]) -> None:
    """
    Faz upsert em lote na tabela 'voos' do Supabase.
    """
    try:
        response = supabase.table("voos").upsert(voos).execute()
    except Exception as e:
        print(f"Erro ao comunicar com Supabase: {e}")
        sys.exit(1)

    if response.get("error"):
        print(f"Erro no upsert do Supabase: {response['error']}")
        sys.exit(1)


# ----------------------------------------------------------------------
# Fluxo principal
# ----------------------------------------------------------------------
def main() -> None:
    voos_raw = buscar_voos_api()
    total_api = len(voos_raw)

    # Normalizar a data_referencia para o formato YYYY-MM-DD
    for voo in voos_raw:
        # A API já retorna data em formato ISO; se precisar converter, faça aqui
        # Exemplo: voo["data_referencia"] = datetime.datetime.strptime(voo["data_referencia"], "%d/%m/%Y").strftime("%Y-%m-%d")
        voo["data_referencia"] = datetime.datetime.now().strftime("%Y-%m-%d")

    voos_filtrados = filtrar_por_aeroportos(voos_raw)
    filtrados = len(voos_filtrados)

    voos_dedup = deduplicar_voos(voos_filtrados)
    deduped = len(voos_dedup)

    # Remover duplicados: quantidade filtrada - quantidade depois de dedup
    duplicados_removidos = filtrados - deduped

    # Mapeia para a estrutura de dados correta
    registros_para_upsert = [mapear_para_estrutura(v) for v in voos_dedup]

    enviar_para_supabase(registros_para_upsert)
    enviados = len(registros_para_upsert)

    # Impressão de métricas
    print(f"Total retornado pela API SIROS: {total_api}")
    print(f"Filtrados para o ICAO configurado: {filtrados}")
    print(f"Duplicados removidos: {duplicados_removidos}")
    print(f"Enviados ao Supabase: {enviados}")
    print("Status final: Sucesso")



if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Falha inesperada: {exc}")
        sys.exit(1)