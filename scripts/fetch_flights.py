# Importações necessárias
import os
import sys
import requests
import pandas as pd
from supabase import create_client, Client
from typing import List, Dict

# Definição da URL da API e do serviço do Supabase
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')
AIRPORTS = os.environ.get('AIRPORTS').split(',')

# Configuração do Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# Função para buscar voos da data atual da API SIROS
def fetch_flights() -> List[Dict]:
    url = "https://api.sirionlh.com/flights/active"
    response = requests.get(url)
    if response.status_code != 200:
        print(f"Erro ao obter voos da API SIROS: {response.status_code}")
        sys.exit(1)
    return response.json()

# Função para filtrar voos para os aeroportos configurados
def filter_flights(flights: List[Dict]) -> List[Dict]:
    return [flight for flight in flights if flight['airport_icao'] in AIRPORTS]

# Função para remover duplicados com base na constraint do banco
def deduplicar_voos(flights: List[Dict]) -> List[Dict]:
    df = pd.DataFrame(flights)
    df.drop_duplicates(subset=['data_referencia', 'codigo_icao_empresa', 'numero_voo',
                              'etapa', 'aeroporto_icao_origem', 'aeroporto_icao_destino',
                              'horario_previsto_partida'], inplace=True)
    return df.to_dict('records')

# Função para enviar voos ao Supabase
def enviar_ao_supabase(flights: List[Dict]) -> None:
    payload = {'records': flights}
    response = supabase.table('public.voos').upsert(payload).execute()
    if response.get('error'):
        print(f"Erro ao enviar voos ao Supabase: {response['error']}")
        sys.exit(1)

# Função principal
def main() -> None:
    flights = fetch_flights()
    total_api = len(flights)
    print(f"Total retornado pela API SIROS: {total_api}")

    flights = filter_flights(flights)
    filtrados = len(flights)
    print(f"Filtrados para os aeroportos configurados: {filtrados}")

    flights = deduplicar_voos(flights)
    duplicados = total_api - len(flights)
    print(f"Duplicados removidos: {duplicados}")

    enviar_ao_supabase(flights)
    enviados = len(flights)
    print(f"Enviados ao Supabase: {enviados}")

    status_final = "Sucesso" if total_api == (filtrados + duplicados + enviados) else "Falha"
    print(f"Status final: {status_final}")

# Chamada da função principal
if __name__ == "__main__":
    main()