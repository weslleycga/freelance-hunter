"""Módulo 1 — Match Score (0–100) = área (0–50) + orçamento (0–25) + clareza do escopo (0–25)."""
from __future__ import annotations

import re
from functools import lru_cache

from .config import Settings
from .llm import LLM
from .models import Job, Score

# Só chamamos a LLM para vagas que a heurística já considera plausíveis (economiza tokens).
LLM_GATE = 45


@lru_cache(maxsize=512)
def _pattern(term: str) -> re.Pattern:
    return re.compile(r"(?<![\w])" + re.escape(term.lower()) + r"(?![\w])")


def _hits(text: str, terms: list[str]) -> set[str]:
    text = text.lower()
    return {t for t in terms if _pattern(t).search(text)}


def heuristic_score(job: Job, s: Settings) -> Score:
    perfil = s.perfil
    excl = _hits(job.title, perfil.get("exclusoes_titulo", []))
    if excl:
        return Score(0, 0, 0, 0, motivo=f"Excluída pelo título: {', '.join(sorted(excl))}")

    corpo = f"{job.description} {' '.join(job.skills)}"
    area = 0.0
    achados: list[str] = []
    for nome, cfg in perfil.get("areas", {}).items():
        w = cfg.get("peso", 1.0)
        no_titulo = _hits(job.title, cfg["palavras"])
        no_corpo = _hits(corpo, cfg["palavras"]) - no_titulo
        area += w * (10 * len(no_titulo) + 4 * len(no_corpo))
        achados += sorted(no_titulo | no_corpo)
    penal = _hits(job.description, perfil.get("penalidades_descricao", []))
    area = max(0, min(50, round(area - 10 * len(penal))))

    # Orçamento (em BRL)
    if job.budget_max is None and job.budget_min is None:
        orc = 12  # desconhecido: neutro
    elif job.is_hourly:
        ref = job.budget_max or job.budget_min
        orc = 25 if ref >= s.valor_hora_minimo else 12 if ref >= 0.7 * s.valor_hora_minimo else 0
    else:
        ref = job.budget_max or job.budget_min
        m = s.valor_minimo_projeto
        orc = 0 if ref < m else 12 if ref < 2 * m else 20 if ref < 5 * m else 25

    # Clareza do escopo
    n = len(job.description)
    clareza = 5 if n < 150 else 12 if n < 400 else 18 if n < 1000 else 22
    if re.search(r"(^|\n)\s*([-•*]|\d+[.)])\s+\S", job.description):
        clareza = min(25, clareza + 3)

    flags = []
    if job.bids and job.bids > 50:
        flags.append(f"{job.bids} propostas já enviadas")
    if penal:
        flags.append(f"Fora do foco: {', '.join(sorted(penal))}")
    total = area + orc + clareza
    motivo = f"Palavras: {', '.join(achados[:8]) or 'nenhuma'}"
    return Score(total, area, orc, clareza, motivo=motivo, red_flags=flags)


SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "area": {"type": "integer", "minimum": 0, "maximum": 50,
                 "description": "Aderência a Web/Automação do freelancer"},
        "orcamento": {"type": "integer", "minimum": 0, "maximum": 25},
        "clareza": {"type": "integer", "minimum": 0, "maximum": 25},
        "motivo": {"type": "string", "description": "1 frase em pt-BR"},
        "red_flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["area", "orcamento", "clareza", "motivo", "red_flags"],
}

SCORE_SYSTEM = """Você avalia vagas de freelance para um desenvolvedor brasileiro (ADS).
Áreas-alvo: desenvolvimento web (landing pages, full-stack, APIs REST, pagamentos, bugs) e
automação (scraping, RPA, scripts Python/JS, bots Telegram/Discord/WhatsApp, integrações via API/webhook).
Fora do escopo (área ≈ 0): design gráfico, vídeo, redação, suporte N1, apps nativos, jogos.
Pontue com rigor:
- area 0–50: o quanto o trabalho principal é Web/Automação.
- orcamento 0–25: compatível com {minimo}/projeto e {hora}/hora? Desconhecido = 12.
- clareza 0–25: entregáveis e critérios de aceite estão claros?
red_flags: pagamento fora da plataforma, "teste grátis", escopo enorme para orçamento baixo,
pedido de dados pessoais, atividade ilegal ou que viole termos de terceiros."""


async def score_job(job: Job, s: Settings, llm: LLM | None) -> Score:
    h = heuristic_score(job, s)
    if h.total == 0 or h.total < LLM_GATE or llm is None:
        return h
    system = SCORE_SYSTEM.format(minimo=f"R$ {s.valor_minimo_projeto:.0f}", hora=f"R$ {s.valor_hora_minimo:.0f}")
    user = (f"Título: {job.title}\nPlataforma: {job.platform}\nOrçamento: {job.budget_raw or 'não informado'}"
            f"{' (por hora)' if job.is_hourly else ''}\nSkills: {', '.join(job.skills)}\n\n"
            f"Descrição:\n{job.description[:6000]}")
    r = await llm.structured(system, user, "avaliar_vaga", SCORE_SCHEMA, max_tokens=600)
    if not r:
        return h
    llm_total = r["area"] + r["orcamento"] + r["clareza"]
    total = round(0.4 * h.total + 0.6 * llm_total)
    return Score(total, r["area"], r["orcamento"], r["clareza"], motivo=r["motivo"],
                 red_flags=h.red_flags + r["red_flags"], fonte="llm")
