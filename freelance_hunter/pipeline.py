"""Uma rodada de busca: coleta -> deduplica -> pontua -> rascunha as que passaram no corte."""
from __future__ import annotations

import logging

from .config import Settings
from .db import DB
from .drafter import draft_proposal
from .llm import LLM
from .matcher import score_job
from .models import Job
from .sources import build_sources

log = logging.getLogger(__name__)

# Teto de rascunhos via LLM por rodada (controle de custo).
MAX_RASCUNHOS_POR_RODADA = 10


async def run_scan(s: Settings, db: DB, llm: LLM | None, client) -> dict:
    stats = {"coletadas": 0, "novas": 0, "aprovadas": 0, "erros": []}
    rascunhos = 0
    for source in build_sources(s.perfil, client):
        try:
            jobs: list[Job] = await source.fetch()
        except Exception as e:  # uma fonte quebrada não derruba as outras
            log.exception("Fonte %s falhou", source.name)
            db.log_fetch(source.name, False, repr(e))
            stats["erros"].append(f"{source.name}: {e}")
            continue
        db.log_fetch(source.name, True, f"{len(jobs)} vagas")
        stats["coletadas"] += len(jobs)

        for job in jobs:
            if db.is_known(job.key):
                continue
            score = await score_job(job, s, llm)
            db.insert_job(job, score)
            stats["novas"] += 1
            if score.total < s.match_score_minimo:
                continue
            stats["aprovadas"] += 1
            if rascunhos >= MAX_RASCUNHOS_POR_RODADA:
                continue
            draft = await draft_proposal(job, s, llm)
            rascunhos += 1
            db.update_job(
                job.key,
                proposta=draft.proposta,
                checklist={"entregaveis": draft.checklist, "perguntas": draft.perguntas,
                           "horas": draft.horas, "valor_sugerido": draft.valor,
                           "prazo_sugerido_dias": draft.prazo_dias},
            )
    log.info("Rodada: %s", stats)
    return stats
