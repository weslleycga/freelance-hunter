"""Workana: a página pública /jobs embute os resultados em JSON no atributo `results-initials`."""
from __future__ import annotations

import html
import json
import re

from ..models import Job
from .base import Source, parse_budget, strip_html

_ATTR = re.compile(r"results-initials='([^']*)'")
BASE = "https://www.workana.com"


def parse_workana(page: str, cambio: dict[str, float]) -> list[Job]:
    m = _ATTR.search(page)
    if not m:
        raise ValueError("Workana: bloco 'results-initials' não encontrado (layout mudou?)")
    data = json.loads(html.unescape(m.group(1)))
    jobs = []
    for r in data.get("results", []):
        slug = r["slug"]
        desc = strip_html(r.get("description", ""))
        # A descrição pública termina com "Categoria: ... Subcategoria: ..." — útil para o score, mantemos.
        budget_raw = strip_html(r.get("budget", ""))
        bmin, bmax = parse_budget(budget_raw, cambio)
        bids = re.search(r"\d+", r.get("totalBids", "") or "")
        jobs.append(Job(
            platform="workana",
            external_id=slug,
            title=strip_html(r.get("title", slug)),
            description=desc,
            url=f"{BASE}/job/{slug}",
            budget_min=bmin,
            budget_max=bmax,
            budget_raw=budget_raw,
            is_hourly=bool(r.get("isHourly")),
            skills=[s.get("anchorText", "") for s in r.get("skills", [])],
            bids=int(bids.group()) if bids else None,
        ))
    return jobs


class WorkanaSource(Source):
    name = "workana"

    def __init__(self, client, urls: list[str], cambio):
        super().__init__(client, cambio)
        self.urls = urls

    async def fetch(self) -> list[Job]:
        out: list[Job] = []
        for url in self.urls:
            resp = await self.client.get(url)
            out.extend(parse_workana(resp.text, self.cambio))
        return out
