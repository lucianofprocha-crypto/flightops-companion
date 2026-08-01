"""
Cliente para NOTAM oficial via API AISWEB (DECEA).

Documentação: https://documenter.getpostman.com/view/7201070/SzKQyg3H
Credenciais: variáveis de ambiente AISWEB_API_KEY / AISWEB_API_PASS.

Em produção (Render), configure essas variáveis no painel do serviço.
Em desenvolvimento local, você pode criar um arquivo ".env" na pasta
backend/ (veja .env.example) — carregado automaticamente por este módulo,
sem dependências externas.

Diferente do ATIS (best-effort, silencioso quando indisponível), uma falha
aqui é reportada como erro explícito: NOTAM é informação de segurança, e
"não consegui verificar" nunca deve parecer visualmente igual a "nenhum
NOTAM ativo".
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import requests

AISWEB_BASE_URL = "https://aisweb.decea.mil.br/api/"
_TIMEOUT_SECONDS = 12


def _load_dotenv() -> None:
    """Carrega um .env simples (KEY=VALUE por linha) da pasta backend/, se existir."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    path = os.path.normpath(path)
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


_load_dotenv()


class NotamFetchError(RuntimeError):
    """Falha ao consultar ou interpretar a resposta da API AISWEB."""

    pass


@dataclass
class Notam:
    cod: str | None
    tipo: str | None  # N (novo), R (substituidor), C (cancelado)
    numero: str | None
    loc: str | None
    inicio: str | None  # <b> - início da efetivação (yyMMddhhmm)
    fim: str | None  # <c> - término da validade, ou "PERM"
    periodo: str | None  # <d> - descrição textual do período
    texto: str | None  # <e> - descrição do NOTAM (obrigatório)
    limite_inferior: str | None
    limite_superior: str | None
    aero: str | None

    def to_dict(self) -> dict:
        return {
            "cod": self.cod,
            "tipo": self.tipo,
            "numero": self.numero,
            "loc": self.loc,
            "inicio": self.inicio,
            "fim": self.fim,
            "periodo": self.periodo,
            "texto": self.texto,
            "limite_inferior": self.limite_inferior,
            "limite_superior": self.limite_superior,
            "aero": self.aero,
        }


def _credentials() -> tuple[str, str]:
    api_key = os.environ.get("AISWEB_API_KEY")
    api_pass = os.environ.get("AISWEB_API_PASS")
    if not api_key or not api_pass:
        raise NotamFetchError(
            "AISWEB_API_KEY / AISWEB_API_PASS não configurados (variáveis de "
            "ambiente ou backend/.env — veja .env.example)."
        )
    return api_key, api_pass


def fetch_notams(icao: str, lang: str = "N", only_active: bool = True, timeout: int = _TIMEOUT_SECONDS) -> list[Notam]:
    """Busca NOTAM vigentes para o aeródromo informado.

    lang: "N" (português/nacional) ou "I" (inglês/internacional).
    only_active: mantido por compatibilidade, mas não usado — testamos ao vivo
    contra a API (01/08/2026) e o parâmetro "all=1" faz a API retornar SOMENTE
    1 resultado (aeródromo exato), enquanto omiti-lo retorna o conjunto
    completo (aeródromo + NOTAM en-route/FIR relevantes), que é o mesmo total
    mostrado na página pública do aeródromo em aisweb.decea.mil.br. Ou seja,
    "all" faz o oposto do que o nome sugere — por isso não é mais enviado.

    Levanta NotamFetchError em qualquer falha (credenciais ausentes, rede,
    resposta inválida) — o chamador decide como comunicar isso ao usuário.
    """
    icao = (icao or "").strip().upper()
    if not icao:
        raise NotamFetchError("Código ICAO não informado.")

    api_key, api_pass = _credentials()
    params = {
        "apiKey": api_key,
        "apiPass": api_pass,
        "area": "notam",
        "icaocode": icao,
        "dist": lang,
    }

    try:
        resp = requests.get(AISWEB_BASE_URL, params=params, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise NotamFetchError(f"Falha ao consultar AISWEB: {exc}") from exc

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        raise NotamFetchError(f"Resposta inválida da AISWEB: {exc}") from exc

    notams: list[Notam] = []
    for el in root.iter():
        # Um registro de NOTAM sempre tem os campos <cod> e <e> (texto do
        # aviso) — o elemento contêiner (<notam total=".." ..>) não tem
        # esses filhos diretos, então isso funciona independente de a API
        # aninhar os registros em <item> ou não.
        if el.findtext("cod") is not None and el.findtext("e") is not None:
            notams.append(
                Notam(
                    cod=el.findtext("cod"),
                    tipo=el.findtext("tp"),
                    numero=el.findtext("n"),
                    loc=el.findtext("loc"),
                    inicio=el.findtext("b"),
                    fim=el.findtext("c"),
                    periodo=el.findtext("d"),
                    texto=el.findtext("e"),
                    limite_inferior=el.findtext("f"),
                    limite_superior=el.findtext("g"),
                    aero=el.findtext("aero"),
                )
            )

    return notams
