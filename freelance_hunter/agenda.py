"""Módulo 4a — agenda_freelance.md (quadro Kanban do Obsidian) + uma nota por projeto em projetos/."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from string import Template

from .config import ROOT, Settings
from .db import DB

MAX_NOVAS_NO_QUADRO = 15
_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.S)


def _slug(row) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", f"{row['platform']}-{row['external_id']}".lower()).strip("-")
    return base[:80]


def _brl(v) -> str:
    return f"R$ {v:,.0f}".replace(",", ".") if v else "—"


def _yaml_str(v) -> str:
    return json.dumps(str(v), ensure_ascii=False) if v not in (None, "") else '""'


def _card(row) -> str:
    box = "x" if row["status"] == "concluido" else " "
    titulo = row["title"].replace("|", "/").replace("[", "(").replace("]", ")")
    partes = [f"[[projetos/{_slug(row)}|{titulo}]]", row["platform"]]
    if row["valor_fechado"]:
        partes.append(_brl(row["valor_fechado"]))
    elif row["budget_max"]:
        partes.append(f"até {_brl(row['budget_max'])}")
    if row["prazo"]:
        partes.append(f"📅 {row['prazo']}")
    partes.append(f"score {row['score']}")
    return f"- [{box}] " + " · ".join(partes)


def _frontmatter(row) -> dict:
    return {
        "status": row["status"],
        "plataforma": row["platform"],
        "valor": _yaml_str(_brl(row["valor_fechado"]) if row["valor_fechado"] else ""),
        "prazo": _yaml_str(row["prazo"] or ""),
        "link": row["url"],
        "score": row["score"],
        "sid": row["sid"],
    }


def write_project_note(s: Settings, row) -> Path:
    """Cria a nota na primeira vez; depois só atualiza o frontmatter (preserva suas edições)."""
    pasta = s.agenda_dir / "projetos"
    pasta.mkdir(parents=True, exist_ok=True)
    path = pasta / f"{_slug(row)}.md"
    fm = _frontmatter(row)
    tpl = Template((ROOT / "templates" / "projeto.md").read_text(encoding="utf-8"))
    if path.exists():
        novo_fm = _FRONTMATTER.match(tpl.safe_substitute(fm)).group(0)
        atual = path.read_text(encoding="utf-8")
        path.write_text(_FRONTMATTER.sub(lambda _: novo_fm, atual, count=1), encoding="utf-8")
        return path
    dados = json.loads(row["checklist"] or "{}")
    checklist = dados.get("entregaveis", []) if isinstance(dados, dict) else dados
    perguntas = dados.get("perguntas", []) if isinstance(dados, dict) else []
    path.write_text(tpl.safe_substitute(
        fm,
        titulo=row["title"],
        orcamento=row["budget_raw"] or "não informado",
        checklist="\n".join(f"- [ ] {c}" for c in checklist) or "- [ ] (preencher após conversar com o cliente)",
        perguntas="\n".join(f"- [ ] {p}" for p in perguntas) or "- [ ] Acessos / credenciais necessários?",
        proposta=row["proposta"] or "(sem rascunho)",
        descricao=row["description"],
    ), encoding="utf-8")
    return path


def render_agenda(s: Settings, db: DB) -> Path:
    s.agenda_dir.mkdir(parents=True, exist_ok=True)
    lanes: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for status in ("pronto", "negociando", "candidatado", "nova", "concluido"):
        rows = db.jobs_by_status(status)
        if status == "nova":
            rows = [r for r in rows if r["score"] >= s.match_score_minimo][:MAX_NOVAS_NO_QUADRO]
        counts[status] = len(rows)
        for r in rows:
            write_project_note(s, r)
        lanes[status] = [_card(r) for r in rows]

    tpl = Template((ROOT / "templates" / "agenda_freelance.md").read_text(encoding="utf-8"))
    out = tpl.substitute(
        atualizado=time.strftime("%Y-%m-%d %H:%M"),
        pausado=str(db.get_setting("pausado") == "1").lower(),
        **{f"n_{k}": v for k, v in counts.items()},
        **{k: "\n".join(v) for k, v in lanes.items()},
    )
    path = s.agenda_dir / "agenda_freelance.md"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(out, encoding="utf-8")
    tmp.replace(path)  # escrita atômica: o Obsidian nunca lê o arquivo pela metade
    return path
