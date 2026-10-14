"""Módulo 2 — relatório semanal de palavras-chave e SUGESTÕES de perfil (você aplica manualmente)."""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

from .config import Settings
from .db import DB
from .llm import LLM
from .matcher import _hits

SEMANA = 7 * 24 * 3600
RELEVANTE = 50  # score mínimo para a vaga entrar na estatística

SUGESTAO_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "Até 80 caracteres"},
        "resumo": {"type": "string", "description": "3 a 5 frases, 1ª pessoa"},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "Até 15 skills, mais relevantes primeiro"},
        "justificativa": {"type": "string"},
    },
    "required": ["headline", "resumo", "tags", "justificativa"],
}


def keyword_stats(s: Settings, db: DB, desde: float) -> dict:
    rows = [r for r in db.jobs_since(desde) if (r["score"] or 0) >= RELEVANTE]
    skills = Counter()
    termos = Counter()
    todos = [t for a in s.perfil.get("areas", {}).values() for t in a["palavras"]]
    for r in rows:
        skills.update(k.strip().lower() for k in json.loads(r["skills"] or "[]") if k.strip())
        termos.update(_hits(f"{r['title']} {r['description']}", todos))
    conhecidos = {t.lower() for t in todos}
    fora_do_perfil = [(k, n) for k, n in skills.most_common(40) if k not in conhecidos][:10]
    return {"vagas": len(rows), "skills": skills.most_common(15), "termos": termos.most_common(15),
            "fora_do_perfil": fora_do_perfil}


async def weekly_report(s: Settings, db: DB, llm: LLM | None) -> tuple[str, Path]:
    st = keyword_stats(s, db, time.time() - SEMANA)
    linhas = [f"# Relatório de perfil — {time.strftime('%Y-%m-%d')}", "",
              f"Vagas relevantes (score ≥ {RELEVANTE}) nos últimos 7 dias: **{st['vagas']}**", "",
              "## Skills mais pedidas", *[f"- {k} — {n}" for k, n in st["skills"]], "",
              "## Seus termos que mais apareceram", *[f"- {k} — {n}" for k, n in st["termos"]], "",
              "## Skills pedidas que NÃO estão no seu perfil.yaml",
              *([f"- {k} — {n}" for k, n in st["fora_do_perfil"]] or ["- (nenhuma)"]), ""]

    if llm and st["vagas"]:
        user = (f"Perfil atual: {s.perfil.get('resumo', '')}\n"
                f"Skills mais pedidas: {st['skills']}\nTermos mais frequentes: {st['termos']}")
        r = await llm.structured(
            "Você otimiza perfis de freelancer para Workana/99Freelas/Freelancer. Sugira headline, resumo e "
            "tags em pt-BR que sejam VERDADEIROS para o perfil informado (não invente skills que ele não tem) "
            "e que usem os termos que os clientes mais buscam.",
            user, "sugerir_perfil", SUGESTAO_SCHEMA, max_tokens=1200)
        if r:
            linhas += ["## Sugestão (revise antes de aplicar nas plataformas)", "",
                       f"**Headline:** {r['headline']}", "", f"**Resumo:** {r['resumo']}", "",
                       f"**Tags:** {', '.join(r['tags'])}", "", f"_Por quê:_ {r['justificativa']}", ""]

    texto = "\n".join(linhas)
    s.agenda_dir.mkdir(parents=True, exist_ok=True)
    path = s.agenda_dir / "relatorio_perfil.md"
    path.write_text(texto, encoding="utf-8")
    db.set_setting("ultimo_relatorio", str(time.time()))
    return texto, path
