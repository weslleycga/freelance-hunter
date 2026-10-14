"""99Freelas: listagem pública em HTML (li.result-item). A listagem não mostra orçamento."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import Job
from .base import Source, strip_html

BASE = "https://www.99freelas.com.br"


def parse_99freelas(page: str) -> list[Job]:
    soup = BeautifulSoup(page, "html.parser")
    items = soup.select("li.result-item")
    if not items and "result-list" not in page:
        raise ValueError("99Freelas: lista de resultados não encontrada (layout mudou?)")
    jobs = []
    for li in items:
        link = li.select_one("h1.title a")
        if not link:
            continue
        desc_el = li.select_one("div.description")
        desc = strip_html(desc_el.get("data-content", "") if desc_el else "")
        info = li.select_one("p.information")
        info_text = " ".join(info.get_text(" ").split()) if info else ""
        bids = re.search(r"Propostas:\s*(\d+)", info_text)
        categoria = info_text.split("|")[0].strip() if info_text else ""
        jobs.append(Job(
            platform="99freelas",
            external_id=li.get("data-id") or link["href"],
            title=link.get_text(strip=True),
            description=desc,
            url=BASE + link["href"].split("?")[0],
            skills=[categoria] if categoria else [],
            bids=int(bids.group(1)) if bids else None,
        ))
    return jobs


class NoventaNoveSource(Source):
    name = "99freelas"

    def __init__(self, client, urls: list[str], cambio):
        super().__init__(client, cambio)
        self.urls = urls

    async def fetch(self) -> list[Job]:
        out: list[Job] = []
        for url in self.urls:
            resp = await self.client.get(url)
            out.extend(parse_99freelas(resp.text))
        return out
