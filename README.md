# Freelance Hunter

Caça vagas de **Web e Automação**, pontua cada uma (Match Score 0–100), escreve um rascunho de proposta
e o checklist técnico, e organiza tudo num quadro Kanban do Obsidian, com avisos no Telegram.
**Ele não envia nada em seu nome:** você revisa o rascunho, envia na plataforma e marca a etapa no bot.

## Instalação

```bash
cd ~/freelance-hunter
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # preencha Telegram e (opcional) ANTHROPIC_API_KEY
$EDITOR config/perfil.yaml  # portfólio, palavras-chave, exclusões
.venv/bin/python -m pytest -q
.venv/bin/python -m freelance_hunter scan   # teste: uma busca e gera a agenda
.venv/bin/python -m freelance_hunter run    # bot + busca a cada INTERVALO_BUSCA_MIN
```

Para rodar em background no boot, use um serviço systemd de usuário (`~/.config/systemd/user/freelance-hunter.service`
com `ExecStart=%h/freelance-hunter/.venv/bin/python -m freelance_hunter run` e `WorkingDirectory=%h/freelance-hunter`).

## Estrutura

```
freelance-hunter/
├── SKILL.md                    # manifesto da skill para o Claude Code
├── .env.example                # segredos e parâmetros (VALOR_HORA_MINIMO, PRAZO_SEGURANCA_DIAS…)
├── config/perfil.yaml          # seu perfil, portfólio, palavras por área, exclusões, câmbio
├── prompts/proposta.md         # system prompt dos rascunhos de proposta
├── templates/
│   ├── agenda_freelance.md     # template do quadro Kanban
│   └── projeto.md              # template da nota de cada projeto (frontmatter + checklist)
├── freelance_hunter/
│   ├── sources/                # Módulo 1 — coletores (workana, noventa_nove, freelancer)
│   ├── matcher.py              # Módulo 1 — Match Score (heurística + Claude opcional)
│   ├── profile_report.py       # Módulo 2 — palavras-chave da semana + sugestão de perfil
│   ├── drafter.py              # rascunho de proposta + checklist + guardrails de valor/prazo
│   ├── agenda.py               # Módulo 4 — agenda_freelance.md + projetos/*.md
│   ├── telegram_bot.py         # Módulo 4 — notificações, comandos e agendamento
│   ├── pipeline.py             # uma rodada: coleta → deduplica → pontua → rascunha
│   ├── db.py                   # SQLite (deduplicação e estado do pipeline)
│   ├── http.py                 # rate limit por domínio, jitter, backoff em 429/5xx
│   └── llm.py                  # Claude API com saída estruturada
└── tests/test_core.py
```

## Fontes

| Plataforma | Como | Observação |
|---|---|---|
| Workana | página pública `/jobs` (JSON embutido) | permitido pelo robots.txt; sem login |
| 99Freelas | página pública `/projects` (HTML) | a listagem não mostra orçamento (score neutro) |
| Freelancer.com | API pública oficial `projects/active` | só leitura, sem token |
| Upwork | — | não incluída: RSS descontinuado e API exige aprovação |

Intervalo mínimo de ~8–11 s entre requisições ao mesmo domínio e backoff exponencial. Se o layout de uma
plataforma mudar, o coletor gera um erro explícito (avisado no Telegram) em vez de falhar em silêncio.

## Match Score

`área (0–50) + orçamento (0–25) + clareza (0–25)`. A heurística usa `config/perfil.yaml`. Título com termo de
exclusão → 0. Com `ANTHROPIC_API_KEY`, vagas com heurística ≥ 45 são reavaliadas pelo Claude e o score final é
`0,4 × heurística + 0,6 × Claude`. Corte padrão: 75.

## Bot do Telegram

Só responde ao `TELEGRAM_CHAT_ID`. Notifica cada vaga ≥ 75 com os botões **📝 Rascunho · 📨 Candidatei · 🗑 Descartar**
(vagas com red flags chegam marcadas "⚠️ Precisa da sua decisão") e avisa quando um projeto fica pronto para executar.

`/status` `/agenda` `/pausar` `/retomar` `/buscar` `/vaga N` `/candidatei N` `/negociando N`
`/fechado N VALOR PRAZO` (ex.: `/fechado 12 1500 30/10`, alerta se estiver abaixo do mínimo ou da margem de prazo)
`/concluido N` `/descartar N` `/relatorio`

## Agenda (Obsidian)

`agenda_freelance.md` é um quadro do plugin **Kanban** (raias: 🔥 Prontos · 💬 Em Negociação · ⏳ Aguardando ·
🎯 Vagas · ✅ Concluídos). Cada cartão aponta para `projetos/<id>.md`, que tem frontmatter
(status, plataforma, valor, prazo, link_chat, score), checklist técnico e pendências com o cliente.
O sistema cria a nota uma vez e depois **só atualiza o frontmatter**, então pode editar o checklist à vontade.
