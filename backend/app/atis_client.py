"""
Cliente para ATIS (Automatic Terminal Information Service) ao vivo.

Fonte: atis.info (antigo datis.clowd.io) — agrega D-ATIS digital publicado
pela FAA via SWIM. Gratuito, sem API key.

IMPORTANTE: cobertura é praticamente restrita a aeroportos dos EUA (D-ATIS
digital). Aeroportos brasileiros e da maioria do resto do mundo não têm essa
informação disponível publicamente em texto — o ATIS lá é só por rádio VHF.
Por isso essa integração é "melhor esforço": quando não há dado, retornamos
disponível=False em vez de erro.
"""

from __future__ import annotations

import requests

ATIS_BASE_URL = "https://datis.clowd.io/api"


def fetch_atis(icao: str, timeout: int = 10) -> list[dict]:
    """Retorna lista de relatórios ATIS (pode ter mais de um: combined/dep/arr).

    Lista vazia significa que não há ATIS digital disponível para o ICAO —
    não é necessariamente um erro, é a maioria dos casos fora dos EUA.
    """
    icao = icao.strip().lower()
    if not icao:
        return []

    try:
        resp = requests.get(f"{ATIS_BASE_URL}/{icao}", timeout=timeout)
    except requests.RequestException:
        # Falha de rede ao consultar uma fonte auxiliar não deve derrubar
        # o resto da análise — tratamos como "indisponível".
        return []

    if resp.status_code != 200:
        return []

    try:
        data = resp.json()
    except ValueError:
        return []

    if not isinstance(data, list):
        return []

    return data
