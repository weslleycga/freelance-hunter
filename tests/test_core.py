import html
import json
from dataclasses import replace

import pytest

from freelance_hunter.agenda import render_agenda
from freelance_hunter.config import ROOT, load_settings
from freelance_hunter.db import DB
from freelance_hunter.matcher import heuristic_score
from freelance_hunter.models import Job
from freelance_hunter.sources.base import parse_budget
from freelance_hunter.sources.freelancer import parse_freelancer
from freelance_hunter.sources.noventa_nove import parse_99freelas
from freelance_hunter.sources.workana import parse_workana

CAMBIO = {"BRL": 1.0, "USD": 5.0}


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)
    s = load_settings(env_file=tmp_path / "nao-existe.env", perfil_file=ROOT / "config" / "perfil.yaml")
    return replace(s, agenda_dir=tmp_path / "agenda", db_path=tmp_path / "t.db",
                   valor_minimo_projeto=300, valor_hora_minimo=60)


@pytest.mark.parametrize("raw,esperado", [
    ("USD 100 - 250", (500.0, 1250.0)),
    ("R$ 1.500,00 - R$ 3.000,00", (1500.0, 3000.0)),
    ("Menos de USD 50", (None, 250.0)),
    ("Mais de R$ 5.000", (5000.0, None)),
    ("", (None, None)),
])
def test_parse_budget(raw, esperado):
    assert parse_budget(raw, CAMBIO) == esperado


def _job(title, desc, **kw):
    return Job(platform="t", external_id=title, title=title, description=desc, url="https://x", **kw)


def test_exclusao_pelo_titulo_zera(settings):
    assert heuristic_score(_job("Criar logotipo para loja", "design"), settings).total == 0


def test_vaga_aderente_passa_do_corte(settings):
    desc = ("Preciso de um bot no Telegram em Python que faça scraping de preços e envie alertas.\n"
            "- Coletar 3 sites\n- Salvar em banco de dados\n- Webhook para notificar\n" + "Detalhes. " * 60)
    sc = heuristic_score(_job("Bot Telegram com web scraping em Python", desc,
                              budget_min=1500, budget_max=3000), settings)
    assert sc.total >= 75, sc


def test_orcamento_baixo_penaliza(settings):
    alto = heuristic_score(_job("API REST em Node", "x" * 500, budget_max=2000), settings)
    baixo = heuristic_score(_job("API REST em Node", "x" * 500, budget_max=100), settings)
    assert baixo.orcamento == 0 and alto.orcamento > baixo.orcamento


def test_parse_workana():
    data = {"results": [{"slug": "bot-whatsapp", "title": '<a href="/job/bot-whatsapp"><span>Bot WhatsApp</span></a>',
                         "description": "Quero um bot<br />Categoria: <strong>TI</strong>",
                         "budget": "USD 100 - 250", "isHourly": False, "totalBids": "Propostas: 6",
                         "skills": [{"anchorText": "Chatbot"}]}]}
    page = f"<div results-initials='{html.escape(json.dumps(data), quote=True)}'></div>"
    [j] = parse_workana(page, CAMBIO)
    assert (j.title, j.url, j.budget_max, j.bids, j.skills) == (
        "Bot WhatsApp", "https://www.workana.com/job/bot-whatsapp", 1250.0, 6, ["Chatbot"])


def test_parse_99freelas():
    page = """<ul class="result-list"><li class="result-item" data-id="42">
      <h1 class="title"><a href="/project/site-42?fs=t">Site institucional</a></h1>
      <p class="item-text information">Desenvolvimento Web | Intermediário | Propostas: <b>7</b></p>
      <div class="item-text description" data-content="Preciso de um site&lt;br/&gt;responsivo"></div>
    </li></ul>"""
    [j] = parse_99freelas(page)
    assert (j.external_id, j.url, j.bids, j.description) == (
        "42", "https://www.99freelas.com.br/project/site-42", 7, "Preciso de um site\nresponsivo")


def test_parse_freelancer():
    data = {"result": {"projects": [{"id": 1, "title": "Scraper", "seo_url": "python/scraper",
                                     "currency": {"code": "USD", "exchange_rate": 1.0},
                                     "budget": {"minimum": 30, "maximum": 250}, "type": "fixed",
                                     "jobs": [{"name": "Python"}], "bid_stats": {"bid_count": 12},
                                     "description": "desc"}]}}
    restrito = dict(data["result"]["projects"][0], id=2, upgrades={"pf_only": True})
    data["result"]["projects"].append(restrito)
    [j] = parse_freelancer(data, CAMBIO)
    assert (j.budget_min, j.budget_max, j.url) == (150.0, 1250.0, "https://www.freelancer.com/projects/python/scraper")


def test_agenda_preserva_edicoes_da_nota(settings):
    db = DB(settings.db_path)
    job = _job("Bot Telegram com scraping em Python", "- item\n" + "y" * 900, budget_max=3000)
    sc = heuristic_score(job, settings)
    sc.total = 90
    db.insert_job(job, sc)
    db.update_job(job.key, proposta="Olá", checklist={"entregaveis": ["Bot"], "perguntas": ["Token?"]})

    agenda = render_agenda(settings, db)
    texto = agenda.read_text()
    assert "kanban-plugin: basic" in texto and "## 🎯 Vagas para candidatar" in texto
    assert "[[projetos/t-bot-telegram-com-scraping-em-python|" in texto

    nota = settings.agenda_dir / "projetos" / "t-bot-telegram-com-scraping-em-python.md"
    nota.write_text(nota.read_text().replace("- [ ] Bot", "- [x] Bot (feito)"))
    db.update_job(job.key, status="pronto", valor_fechado=1500, prazo="2026-10-30")
    render_agenda(settings, db)
    conteudo = nota.read_text()
    assert "status: pronto" in conteudo and '"R$ 1.500"' in conteudo
    assert "- [x] Bot (feito)" in conteudo
    assert "## 🔥 Prontos para Executar (Escopo Fechado)\n\n- [ ] [[projetos/" in agenda.read_text()
