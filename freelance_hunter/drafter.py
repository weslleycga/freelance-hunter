"""Rascunho de proposta + checklist técnico. Só gera texto para você revisar e enviar."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .config import ROOT, Settings
from .llm import LLM
from .models import Job

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "proposta": {"type": "string"},
        "checklist": {"type": "array", "items": {"type": "string"},
                      "description": "Entregáveis técnicos verificáveis"},
        "perguntas": {"type": "array", "items": {"type": "string"},
                      "description": "O que falta saber do cliente"},
        "horas_estimadas": {"type": "number"},
        "valor_sugerido_brl": {"type": "number"},
        "prazo_sugerido_dias": {"type": "integer"},
    },
    "required": ["proposta", "checklist", "perguntas", "horas_estimadas",
                 "valor_sugerido_brl", "prazo_sugerido_dias"],
}


@dataclass
class Draft:
    proposta: str
    checklist: list[str] = field(default_factory=list)
    perguntas: list[str] = field(default_factory=list)
    horas: float | None = None
    valor: float | None = None
    prazo_dias: int | None = None


def _portfolio_text(perfil: dict) -> str:
    itens = perfil.get("portfolio") or []
    return "\n".join(f"- {p['titulo']} — {p['url']} (tags: {', '.join(p.get('tags', []))})" for p in itens) \
        or "(nenhum cadastrado)"


def system_prompt(s: Settings) -> str:
    tpl = (ROOT / "prompts" / "proposta.md").read_text(encoding="utf-8")
    p = s.perfil
    return tpl.format(nome=p.get("nome", "o freelancer"), resumo=p.get("resumo", "").strip(),
                      valor_hora=f"{s.valor_hora_minimo:.0f}", prazo_seguranca=s.prazo_seguranca_dias,
                      portfolio=_portfolio_text(p))


def template_draft(job: Job, s: Settings) -> Draft:
    """Fallback sem LLM: um esqueleto para você completar."""
    nome = s.perfil.get("nome", "")
    texto = (
        f"Li sua vaga \"{job.title}\" e entendi que o objetivo é [RESUMIR O PROBLEMA EM 1 FRASE].\n\n"
        "Minha proposta de solução:\n"
        "1. [ETAPA 1 — stack/abordagem]\n2. [ETAPA 2]\n3. Entrega com código-fonte e instruções de uso.\n\n"
        "Para fechar o escopo, preciso confirmar:\n- [PERGUNTA 1]\n- [PERGUNTA 2]\n\n"
        f"Posso começar logo após alinharmos esses pontos.\n{nome}"
    )
    return Draft(proposta=texto)


async def draft_proposal(job: Job, s: Settings, llm: LLM | None) -> Draft:
    if llm is None:
        return template_draft(job, s)
    user = (f"Plataforma: {job.platform}\nTítulo: {job.title}\n"
            f"Orçamento do cliente: {job.budget_raw or 'não informado'}{' (por hora)' if job.is_hourly else ''}\n"
            f"Skills pedidas: {', '.join(job.skills)}\n\nDescrição da vaga:\n{job.description[:8000]}")
    r = await llm.structured(system_prompt(s), user, "registrar_rascunho", DRAFT_SCHEMA, max_tokens=2500)
    if not r:
        return template_draft(job, s)
    horas = max(1.0, float(r["horas_estimadas"]))
    # Guardrails determinísticos: nunca abaixo do seu mínimo, sempre com margem de prazo.
    valor = max(float(r["valor_sugerido_brl"]), horas * s.valor_hora_minimo, s.valor_minimo_projeto)
    prazo = max(int(r["prazo_sugerido_dias"]), math.ceil(horas / 6) + s.prazo_seguranca_dias)
    return Draft(proposta=r["proposta"].strip(), checklist=r["checklist"], perguntas=r["perguntas"],
                 horas=horas, valor=round(valor, -1), prazo_dias=prazo)
