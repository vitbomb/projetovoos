# -*- coding: utf-8 -*-
"""Coleta voos do SIROS/ANAC e os envia para o Supabase.

Variaveis de ambiente:
    SUPABASE_URL: URL do projeto Supabase.
    SUPABASE_SERVICE_KEY: chave secreta usada somente no backend.
    AIRPORTS: codigos ICAO separados por virgula. Padrao: SBCA.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from supabase import Client, create_client


SIROS_URL = "https://sas.anac.gov.br/sas/siros_api/voos"
TAMANHO_LOTE = 500
COLUNAS_CONFLITO = (
    "data_referencia,codigo_icao_empresa,numero_voo,etapa,"
    "aeroporto_icao_origem,aeroporto_icao_destino,"
    "horario_previsto_partida"
)


def fuso_sao_paulo() -> dt.tzinfo:
    """Retorna o fuso de Sao Paulo, com fallback para ambientes sem tzdata."""
    try:
        return ZoneInfo("America/Sao_Paulo")
    except ZoneInfoNotFoundError:
        return dt.timezone(dt.timedelta(hours=-3))


def agora_sao_paulo() -> dt.datetime:
    """Retorna a data e hora atuais no fuso de Sao Paulo."""
    return dt.datetime.now(tz=fuso_sao_paulo())


def texto(valor: Any) -> str:
    """Normaliza um valor possivelmente numerico ou nulo como texto."""
    return str(valor if valor is not None else "").strip()


def inteiro_ou_nulo(valor: Any) -> int | None:
    """Converte um valor para inteiro; retorna None quando nao for possivel."""
    valor_texto = texto(valor)
    if not valor_texto:
        return None
    try:
        return int(float(valor_texto.replace(",", ".")))
    except (TypeError, ValueError):
        return None


def parse_horario_utc(valor: Any) -> str | None:
    """Converte um horario informado pelo SIROS para ISO 8601 em UTC.

    Os campos ``dt_*_prevista_utc`` ja representam UTC. Portanto, o horario
    nao deve ser interpretado como America/Sao_Paulo antes da conversao.
    """
    valor_texto = texto(valor)
    if not valor_texto:
        return None

    for formato in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
        try:
            instante = dt.datetime.strptime(valor_texto, formato)
            return instante.replace(tzinfo=dt.timezone.utc).isoformat()
        except ValueError:
            pass

    try:
        instante = dt.datetime.fromisoformat(valor_texto.replace("Z", "+00:00"))
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=dt.timezone.utc)
        return instante.astimezone(dt.timezone.utc).isoformat()
    except ValueError:
        return None


def carregar_configuracao() -> tuple[str, str, list[str]]:
    """Le e valida as variaveis de ambiente obrigatorias."""
    supabase_url = texto(os.getenv("SUPABASE_URL"))
    supabase_key = texto(os.getenv("SUPABASE_SERVICE_KEY"))
    aeroportos = [
        codigo.strip().upper()
        for codigo in os.getenv("AIRPORTS", "SBCA").split(",")
        if codigo.strip()
    ]

    if not supabase_url or not supabase_key:
        raise RuntimeError(
            "SUPABASE_URL e SUPABASE_SERVICE_KEY sao obrigatorias."
        )
    if not aeroportos:
        aeroportos = ["SBCA"]

    return supabase_url, supabase_key, aeroportos


def buscar_voos_api(sessao: requests.Session | None = None) -> list[dict[str, Any]]:
    """Consulta a API publica SIROS/ANAC para a data atual em Sao Paulo."""
    data_referencia = agora_sao_paulo().strftime("%d%m%Y")
    cliente_http = sessao or requests

    try:
        resposta = cliente_http.get(
            SIROS_URL,
            params={"dataReferencia": data_referencia},
            timeout=60,
        )
        resposta.raise_for_status()
        payload: Any = resposta.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"Falha ao consultar o SIROS: {exc}") from exc
    except ValueError as exc:
        raise RuntimeError("O SIROS retornou uma resposta que nao e JSON.") from exc

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "O SIROS retornou uma string que nao contem JSON valido."
            ) from exc

    if not isinstance(payload, list):
        raise RuntimeError(
            f"Formato inesperado do SIROS: esperado list, recebido "
            f"{type(payload).__name__}."
        )

    return [registro for registro in payload if isinstance(registro, dict)]


def inferir_tipo_operacao(tipo_servico: str) -> str | None:
    """Infere operacao domestica ou internacional quando o texto permitir."""
    tipo_maiusculo = tipo_servico.upper()
    if "INTERNAC" in tipo_maiusculo:
        return "Internacional"
    if tipo_maiusculo:
        return "Domestico"
    return None


def mapear_voo(raw: dict[str, Any], data_referencia: str) -> dict[str, Any]:
    """Mapeia um registro bruto do SIROS para a tabela ``public.voos``."""
    tipo_servico = texto(raw.get("ds_tipo_servico"))

    return {
        "data_referencia": data_referencia,
        "codigo_icao_empresa": texto(raw.get("sg_empresa_icao")).upper(),
        "numero_voo": texto(raw.get("nr_voo")),
        "etapa": texto(raw.get("nr_etapa")),
        "aeroporto_icao_origem": texto(raw.get("sg_icao_origem")).upper(),
        "aeroporto_icao_destino": texto(raw.get("sg_icao_destino")).upper(),
        "horario_previsto_partida": parse_horario_utc(
            raw.get("dt_partida_prevista_utc")
        ),
        "horario_previsto_chegada": parse_horario_utc(
            raw.get("dt_chegada_prevista_utc")
        ),
        "equipamento": texto(raw.get("sg_equipamento_icao")).upper() or None,
        "quantidade_assentos": inteiro_ou_nulo(raw.get("qt_assentos_previstos")),
        "tipo_operacao": inferir_tipo_operacao(tipo_servico),
        "tipo_servico": tipo_servico or None,
    }


def filtrar_por_aeroportos(
    voos: list[dict[str, Any]], aeroportos: list[str]
) -> list[dict[str, Any]]:
    """Mantem voos cuja origem ou destino esteja entre os ICAOs informados."""
    conjunto_aeroportos = set(aeroportos)
    return [
        voo
        for voo in voos
        if voo["aeroporto_icao_origem"] in conjunto_aeroportos
        or voo["aeroporto_icao_destino"] in conjunto_aeroportos
    ]


def registro_valido(voo: dict[str, Any]) -> bool:
    """Verifica os campos obrigatorios definidos em ``sql/setup.sql``."""
    campos_obrigatorios = (
        "data_referencia",
        "codigo_icao_empresa",
        "numero_voo",
        "etapa",
        "aeroporto_icao_origem",
        "aeroporto_icao_destino",
        "horario_previsto_partida",
    )
    return all(voo.get(campo) not in (None, "") for campo in campos_obrigatorios)


def chave_unica(voo: dict[str, Any]) -> tuple[Any, ...]:
    """Monta a mesma chave definida pela constraint ``voos_unico``."""
    return (
        voo["data_referencia"],
        voo["codigo_icao_empresa"],
        voo["numero_voo"],
        voo["etapa"],
        voo["aeroporto_icao_origem"],
        voo["aeroporto_icao_destino"],
        voo["horario_previsto_partida"],
    )


def deduplicar_voos(voos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicados conforme a constraint UNIQUE da tabela ``voos``."""
    vistos: set[tuple[Any, ...]] = set()
    unicos: list[dict[str, Any]] = []

    for voo in voos:
        chave = chave_unica(voo)
        if chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(voo)

    return unicos


def enviar_para_supabase(cliente: Client, voos: list[dict[str, Any]]) -> int:
    """Faz upsert dos voos em lotes e retorna a quantidade processada."""
    total_enviado = 0

    for inicio in range(0, len(voos), TAMANHO_LOTE):
        lote = voos[inicio : inicio + TAMANHO_LOTE]
        if not lote:
            continue
        try:
            (
                cliente.table("voos")
                .upsert(lote, on_conflict=COLUNAS_CONFLITO)
                .execute()
            )
        except Exception as exc:
            numero_lote = inicio // TAMANHO_LOTE + 1
            raise RuntimeError(
                f"Falha ao enviar o lote {numero_lote} ao Supabase: {exc}"
            ) from exc
        total_enviado += len(lote)

    return total_enviado


def imprimir_metricas(
    total_api: int,
    total_filtrados: int,
    duplicados_removidos: int,
    total_enviados: int,
    status: str,
) -> None:
    """Exibe as metricas exigidas pelo questionario da atividade."""
    print(f"Total retornado pela API SIROS: {total_api}")
    print(f"Filtrados para o ICAO configurado: {total_filtrados}")
    print(f"Duplicados removidos: {duplicados_removidos}")
    print(f"Enviados ao Supabase: {total_enviados}")
    print(f"Status final: {status}")


def main() -> int:
    """Executa a coleta, normalizacao, deduplicacao e persistencia dos voos."""
    total_api = 0
    total_filtrados = 0
    duplicados_removidos = 0
    total_enviados = 0

    try:
        supabase_url, supabase_key, aeroportos = carregar_configuracao()
        cliente_supabase = create_client(supabase_url, supabase_key)

        voos_raw = buscar_voos_api()
        total_api = len(voos_raw)

        data_referencia = agora_sao_paulo().date().isoformat()
        voos_mapeados = [
            mapear_voo(voo, data_referencia) for voo in voos_raw
        ]
        voos_filtrados = filtrar_por_aeroportos(voos_mapeados, aeroportos)
        total_filtrados = len(voos_filtrados)

        voos_validos = [voo for voo in voos_filtrados if registro_valido(voo)]
        descartados_invalidos = total_filtrados - len(voos_validos)
        if descartados_invalidos:
            print(
                f"Aviso: {descartados_invalidos} registro(s) incompleto(s) "
                "foram descartados."
            )

        voos_unicos = deduplicar_voos(voos_validos)
        duplicados_removidos = len(voos_validos) - len(voos_unicos)
        total_enviados = enviar_para_supabase(cliente_supabase, voos_unicos)

        imprimir_metricas(
            total_api,
            total_filtrados,
            duplicados_removidos,
            total_enviados,
            "Sucesso",
        )
        return 0
    except Exception as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        imprimir_metricas(
            total_api,
            total_filtrados,
            duplicados_removidos,
            total_enviados,
            "Erro",
        )
        return 1


if __name__ == "__main__":
    codigo_saida = main()
    if codigo_saida != 0:
        sys.exit(1)