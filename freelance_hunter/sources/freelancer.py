"""Freelancer.com: API pública oficial de projetos ativos (leitura, sem login)."""
from __future__ import annotations

from ..models import Job
from .base import Source

API = "https://www.freelancer.com/api/projects/0.1/projects/active/"


def parse_freelancer(data: dict, cambio: dict[str, float]) -> list[Job]:
    jobs = []
    for p in data.get("result", {}).get("projects", []):
        # "Este projeto está aberto apenas a freelancers selecionados" — só Preferred Freelancers podem dar lance.
        if (p.get("upgrades") or {}).get("pf_only"):
            continue
        cur = p.get("currency") or {}
        # exchange_rate da API converte para USD; depois USD -> BRL pela tabela do perfil.
        to_brl = (cur.get("exchange_rate") or 1.0) * cambio.get("USD", 5.4)
        if cur.get("code") == "BRL":
            to_brl = 1.0
        b = p.get("budget") or {}
        bmin = b.get("minimum")
        bmax = b.get("maximum")
        jobs.append(Job(
            platform="freelancer",
            external_id=str(p["id"]),
            title=p.get("title", ""),
            description=p.get("description") or p.get("preview_description", ""),
            url=f"https://www.freelancer.com/projects/{p.get('seo_url', p['id'])}",
            budget_min=bmin * to_brl if bmin else None,
            budget_max=bmax * to_brl if bmax else None,
            budget_raw=f"{cur.get('code', '')} {bmin or '?'} - {bmax or '?'}",
            is_hourly=p.get("type") == "hourly",
            skills=[j.get("name", "") for j in p.get("jobs") or []],
            bids=(p.get("bid_stats") or {}).get("bid_count"),
        ))
    return jobs


class FreelancerSource(Source):
    name = "freelancer"

    def __init__(self, client, buscas: list[str], cambio):
        super().__init__(client, cambio)
        self.buscas = buscas

    async def fetch(self) -> list[Job]:
        seen: dict[str, Job] = {}
        for q in self.buscas:
            resp = await self.client.get(API, params={
                "query": q, "limit": 20, "full_description": "true", "job_details": "true",
                "sort_field": "time_updated",
            })
            for job in parse_freelancer(resp.json(), self.cambio):
                seen.setdefault(job.key, job)
        return list(seen.values())
