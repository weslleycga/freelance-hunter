from .base import Source
from .freelancer import FreelancerSource
from .noventa_nove import NoventaNoveSource
from .workana import WorkanaSource


def build_sources(perfil: dict, client) -> list[Source]:
    fontes = perfil.get("fontes", {})
    cambio = perfil.get("cambio_brl", {"BRL": 1.0})
    out: list[Source] = []
    if fontes.get("workana", {}).get("ativo"):
        out.append(WorkanaSource(client, fontes["workana"]["urls"], cambio))
    if fontes.get("noventa_nove", {}).get("ativo"):
        out.append(NoventaNoveSource(client, fontes["noventa_nove"]["urls"], cambio))
    if fontes.get("freelancer", {}).get("ativo"):
        out.append(FreelancerSource(client, fontes["freelancer"]["buscas"], cambio))
    return out
