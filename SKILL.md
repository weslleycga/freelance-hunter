---
name: freelance-hunter
description: Busca vagas de Web/Automação no Workana, 99Freelas e Freelancer.com, calcula o Match Score, gera rascunhos de proposta e checklist técnico, mantém o agenda_freelance.md (Kanban do Obsidian) e notifica pelo Telegram. Não envia nada em nome do usuário. Use quando o usuário pedir para buscar vagas, ver o pipeline de freelas, regenerar a agenda ou o relatório de perfil.
---

# Freelance Hunter

Projeto em `~/freelance-hunter` (venv em `.venv`). Comandos:

| Pedido do usuário | Comando |
|---|---|
| "busca vagas agora" | `.venv/bin/python -m freelance_hunter scan` |
| "atualiza a agenda" | `.venv/bin/python -m freelance_hunter agenda` |
| "relatório de perfil / palavras-chave" | `.venv/bin/python -m freelance_hunter relatorio` |
| "liga o bot" | `.venv/bin/python -m freelance_hunter run` (processo contínuo) |

Regras:
- Nunca enviar propostas ou mensagens a clientes, nem alterar perfis nas plataformas. O sistema produz
  rascunhos; o usuário revisa e envia.
- Ajustes de score: editar `config/perfil.yaml` (palavras, pesos, exclusões) e rodar `pytest`.
- Estado em `data/hunter.db` (SQLite). Agenda em `$AGENDA_DIR/agenda_freelance.md` + `projetos/*.md`.
