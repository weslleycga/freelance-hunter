"""Módulo 4b — Bot do Telegram: notificações, comandos e agendamento das buscas.

O bot só responde ao seu chat (TELEGRAM_CHAT_ID). Ele NÃO envia nada para clientes:
você copia o rascunho, envia na plataforma e marca a etapa aqui.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import logging
import re
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, filters

from .agenda import render_agenda
from .config import Settings
from .db import DB
from .http import PoliteClient
from .llm import LLM
from .models import STATUS
from .pipeline import run_scan
from .profile_report import SEMANA, weekly_report

log = logging.getLogger(__name__)
LIMITE_TG = 4000
e = html.escape


def _brl(v) -> str:
    return f"R$ {v:,.0f}".replace(",", ".") if v else "—"


def _parse_prazo(txt: str) -> str:
    """'2026-10-30' | '30/10' | '10d' | '10' (dias a partir de hoje) -> 'AAAA-MM-DD'."""
    hoje = dt.date.today()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", txt):
        return dt.date.fromisoformat(txt).isoformat()
    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{4}))?", txt):
        d, mth, y = int(m[1]), int(m[2]), int(m[3] or hoje.year)
        return dt.date(y, mth, d).isoformat()
    if m := re.fullmatch(r"(\d+)d?", txt):
        return (hoje + dt.timedelta(days=int(m[1]))).isoformat()
    raise ValueError(f"prazo inválido: {txt}")


def _parse_valor(txt: str) -> float:
    txt = txt.lower().replace("r$", "").replace(".", "").replace(",", ".").strip()
    if txt.endswith("k"):
        return float(txt[:-1]) * 1000
    return float(txt)


class Bot:
    def __init__(self, s: Settings, db: DB, llm: LLM | None):
        if not s.telegram_token or not s.telegram_chat_id:
            raise SystemExit("Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env")
        self.s, self.db, self.llm = s, db, llm
        self.client = PoliteClient()
        self.app = Application.builder().token(s.telegram_token).post_shutdown(self._shutdown).build()
        dono = filters.Chat(chat_id=s.telegram_chat_id)
        for nome, fn in [
            ("start", self.cmd_ajuda), ("ajuda", self.cmd_ajuda), ("status", self.cmd_status),
            ("agenda", self.cmd_agenda), ("pausar", self.cmd_pausar), ("retomar", self.cmd_retomar),
            ("buscar", self.cmd_buscar), ("vaga", self.cmd_vaga), ("relatorio", self.cmd_relatorio),
            ("candidatei", self.cmd_mover("candidatado")), ("negociando", self.cmd_mover("negociando")),
            ("descartar", self.cmd_mover("descartada")), ("concluido", self.cmd_mover("concluido")),
            ("fechado", self.cmd_fechado),
        ]:
            self.app.add_handler(CommandHandler(nome, fn, filters=dono))
        self.app.add_handler(CallbackQueryHandler(self.on_button, pattern=r"^(ver|cand|desc):\d+$"))
        self.app.add_error_handler(self.on_error)
        self.app.job_queue.run_repeating(self.job_scan, interval=s.intervalo_busca_min * 60, first=15)

    def run(self) -> None:
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)

    async def _shutdown(self, _app) -> None:
        await self.client.aclose()

    async def _send(self, texto: str, markup=None) -> None:
        await self.app.bot.send_message(self.s.telegram_chat_id, texto[:LIMITE_TG], parse_mode=ParseMode.HTML,
                                        reply_markup=markup, disable_web_page_preview=True)

    def _refresh_agenda(self) -> None:
        try:
            render_agenda(self.s, self.db)
        except Exception:
            log.exception("Falha ao renderizar a agenda")

    # ---------------- jobs agendados ----------------
    async def job_scan(self, _ctx: ContextTypes.DEFAULT_TYPE, forcar: bool = False) -> None:
        if self.db.get_setting("pausado") == "1" and not forcar:
            return
        stats = await run_scan(self.s, self.db, self.llm, self.client)
        for row in self.db.pending_notifications(self.s.match_score_minimo):
            await self._notify_job(row)
            self.db.update_job(row["key"], notificado=1)
        if stats["erros"]:
            await self._send("⚠️ <b>Falha em fonte(s):</b>\n" + e("\n".join(stats["erros"])))
        self._refresh_agenda()
        if time.time() - float(self.db.get_setting("ultimo_relatorio", "0")) > SEMANA:
            texto, _ = await weekly_report(self.s, self.db, self.llm)
            await self._send(f"<pre>{e(texto[:3800])}</pre>")

    async def _notify_job(self, row) -> None:
        sc = json.loads(row["score_json"] or "{}")
        extra = json.loads(row["checklist"] or "{}")
        flags = sc.get("red_flags") or []
        cab = "⚠️ <b>Precisa da sua decisão</b>\n" if flags else ""
        txt = (f"{cab}🎯 <b>#{row['sid']} · {e(row['title'])}</b>\n"
               f"{row['platform']} · score <b>{row['score']}</b> "
               f"(área {sc.get('area')}, orçamento {sc.get('orcamento')}, clareza {sc.get('clareza')})\n"
               f"💰 {e(row['budget_raw'] or 'orçamento não informado')}")
        if isinstance(extra, dict) and extra.get("valor_sugerido"):
            txt += f" · sugerido {_brl(extra['valor_sugerido'])} em {extra.get('prazo_sugerido_dias')} dias"
        txt += f"\n💡 {e(sc.get('motivo', ''))}"
        if flags:
            txt += "\n🚩 " + e("; ".join(flags))
        txt += f"\n🔗 {e(row['url'])}"
        sid = row["sid"]
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📝 Rascunho", callback_data=f"ver:{sid}"),
            InlineKeyboardButton("📨 Candidatei", callback_data=f"cand:{sid}"),
            InlineKeyboardButton("🗑 Descartar", callback_data=f"desc:{sid}"),
        ]])
        await self._send(txt, kb)

    # ---------------- botões ----------------
    async def on_button(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        if q.message.chat.id != self.s.telegram_chat_id:
            await q.answer()
            return
        acao, sid = q.data.split(":")
        row = self.db.find_job(sid)
        if not row:
            await q.answer("Vaga não encontrada")
            return
        if acao == "ver":
            await q.answer()
            await self._send_draft(row)
        else:
            novo = "candidatado" if acao == "cand" else "descartada"
            self.db.update_job(row["key"], status=novo)
            await q.answer(STATUS[novo])
            await q.edit_message_reply_markup(None)
            await q.message.reply_text(f"#{sid} → {STATUS[novo]}")
            self._refresh_agenda()

    async def _send_draft(self, row) -> None:
        extra = json.loads(row["checklist"] or "{}")
        txt = f"📝 <b>Rascunho #{self.db.short_id(row['key'])}</b> — revise e envie você mesmo:\n\n"
        txt += f"<pre>{e(row['proposta'] or '(sem rascunho)')}</pre>"
        if isinstance(extra, dict) and extra.get("perguntas"):
            txt += "\n<b>Pendências com o cliente:</b>\n" + e("\n".join(f"• {p}" for p in extra["perguntas"]))
        await self._send(txt)

    # ---------------- comandos ----------------
    async def cmd_ajuda(self, update: Update, _ctx) -> None:
        await update.message.reply_text(
            "/status — resumo do pipeline\n/agenda — projetos ativos e prazos\n"
            "/buscar — buscar vagas agora\n/vaga N — detalhes e rascunho da vaga #N\n"
            "/candidatei N · /negociando N · /descartar N · /concluido N\n"
            "/fechado N VALOR PRAZO — ex.: /fechado 12 1500 30/10 (ou 10d)\n"
            "/pausar · /retomar — pausa/retoma novas buscas\n/relatorio — palavras-chave e sugestão de perfil")

    async def cmd_status(self, update: Update, _ctx) -> None:
        c = self.db.counts()
        linhas = [f"{'⏸ PAUSADO' if self.db.get_setting('pausado') == '1' else '▶️ Ativo'}"
                  f" · busca a cada {self.s.intervalo_busca_min} min · corte {self.s.match_score_minimo}"]
        for k in ("pronto", "negociando", "candidatado", "nova", "concluido"):
            linhas.append(f"{STATUS[k]}: {c.get(k, 0)}")
        for fonte in ("workana", "99freelas", "freelancer"):
            f = self.db.last_fetch(fonte)
            if f:
                quando = time.strftime("%d/%m %H:%M", time.localtime(f["ts"]))
                linhas.append(f"{'✅' if f['ok'] else '❌'} {fonte}: {quando} — {f['info'][:60]}")
        await update.message.reply_text("\n".join(linhas))

    async def cmd_agenda(self, update: Update, _ctx) -> None:
        linhas = []
        for k in ("pronto", "negociando", "candidatado"):
            rows = self.db.jobs_by_status(k)
            if rows:
                linhas.append(f"\n<b>{STATUS[k]}</b>")
                for r in rows:
                    prazo = f" · 📅 {r['prazo']}" if r["prazo"] else ""
                    valor = f" · {_brl(r['valor_fechado'])}" if r["valor_fechado"] else ""
                    linhas.append(f"#{r['sid']} {e(r['title'][:60])}{valor}{prazo}")
        await self._send("\n".join(linhas) or "Nenhum projeto ativo.")

    async def cmd_pausar(self, update: Update, _ctx) -> None:
        self.db.set_setting("pausado", "1")
        self._refresh_agenda()
        await update.message.reply_text("⏸ Buscas pausadas. Use /retomar quando a agenda liberar.")

    async def cmd_retomar(self, update: Update, _ctx) -> None:
        self.db.set_setting("pausado", "0")
        self._refresh_agenda()
        await update.message.reply_text("▶️ Buscas retomadas.")

    async def cmd_buscar(self, update: Update, ctx) -> None:
        await update.message.reply_text("🔎 Buscando…")
        await self.job_scan(ctx, forcar=True)
        await update.message.reply_text("Busca concluída. /status para o resumo.")

    async def cmd_vaga(self, update: Update, ctx) -> None:
        row = self.db.find_job(ctx.args[0]) if ctx.args else None
        if not row:
            await update.message.reply_text("Uso: /vaga N")
            return
        await self._send(f"<b>{e(row['title'])}</b>\n{STATUS.get(row['status'])} · score {row['score']}\n"
                         f"{e(row['url'])}\n\n{e(row['description'][:1500])}")
        await self._send_draft(row)

    def cmd_mover(self, status: str):
        async def handler(update: Update, ctx) -> None:
            row = self.db.find_job(ctx.args[0]) if ctx.args else None
            if not row:
                await update.message.reply_text(f"Uso: /{update.message.text.split()[0][1:]} N")
                return
            self.db.update_job(row["key"], status=status)
            self._refresh_agenda()
            await update.message.reply_text(f"#{ctx.args[0].lstrip('#')} → {STATUS[status]}")
        return handler

    async def cmd_fechado(self, update: Update, ctx) -> None:
        try:
            ref, valor_txt, prazo_txt = ctx.args[:3]
            valor, prazo = _parse_valor(valor_txt), _parse_prazo(prazo_txt)
        except (ValueError, TypeError):
            await update.message.reply_text("Uso: /fechado N VALOR PRAZO — ex.: /fechado 12 1500 30/10")
            return
        row = self.db.find_job(ref)
        if not row:
            await update.message.reply_text("Vaga não encontrada.")
            return
        avisos = []
        if valor < self.s.valor_minimo_projeto:
            avisos.append(f"valor abaixo do seu mínimo ({_brl(self.s.valor_minimo_projeto)})")
        dias = (dt.date.fromisoformat(prazo) - dt.date.today()).days
        if dias < self.s.prazo_seguranca_dias:
            avisos.append(f"prazo menor que a margem de segurança ({self.s.prazo_seguranca_dias} dias)")
        self.db.update_job(row["key"], status="pronto", valor_fechado=valor, prazo=prazo)
        self._refresh_agenda()
        extra = json.loads(row["checklist"] or "{}")
        itens = extra.get("entregaveis", []) if isinstance(extra, dict) else []
        txt = (f"🔥 <b>Pronto para executar: #{self.db.short_id(row['key'])} {e(row['title'])}</b>\n"
               f"{_brl(valor)} · 📅 {prazo}\n\n<b>Checklist:</b>\n"
               + (e("\n".join(f"☐ {i}" for i in itens)) or "(edite na nota do projeto)"))
        if avisos:
            txt = "⚠️ " + e("; ".join(avisos)) + "\n\n" + txt
        await self._send(txt)

    async def cmd_relatorio(self, update: Update, _ctx) -> None:
        texto, path = await weekly_report(self.s, self.db, self.llm)
        await self._send(f"<pre>{e(texto[:3800])}</pre>\nSalvo em {e(str(path))}")

    async def on_error(self, _update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("Erro no bot", exc_info=ctx.error)
