"""CLI: python -m freelance_hunter {run|scan|agenda|relatorio}"""
from __future__ import annotations

import argparse
import asyncio
import logging

from .agenda import render_agenda
from .config import load_settings
from .db import DB
from .http import PoliteClient
from .llm import LLM
from .pipeline import run_scan
from .profile_report import weekly_report


async def _scan_once(s, db, llm) -> None:
    client = PoliteClient()
    try:
        stats = await run_scan(s, db, llm, client)
    finally:
        await client.aclose()
    print(f"Coletadas {stats['coletadas']} · novas {stats['novas']} · aprovadas (≥{s.match_score_minimo}) "
          f"{stats['aprovadas']}")
    for err in stats["erros"]:
        print("ERRO:", err)
    for r in db.jobs_by_status("nova")[:15]:
        if r["score"] >= s.match_score_minimo:
            print(f"  #{r['sid']:<4} {r['score']:>3}  {r['platform']:<10} {r['title'][:70]}")
    print("Agenda:", render_agenda(s, db))


def main() -> None:
    ap = argparse.ArgumentParser(prog="freelance_hunter")
    ap.add_argument("comando", choices=["run", "scan", "agenda", "relatorio"],
                    help="run = bot do Telegram + buscas agendadas; scan = uma busca agora; "
                         "agenda = regenera o .md; relatorio = palavras-chave/sugestão de perfil")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    s = load_settings()
    db = DB(s.db_path)
    llm = LLM(s.anthropic_api_key, s.claude_model) if s.llm_ativo else None
    if llm is None:
        logging.warning("ANTHROPIC_API_KEY ausente: score só por heurística e rascunho por template")

    if args.comando == "run":
        from .telegram_bot import Bot
        Bot(s, db, llm).run()
    elif args.comando == "scan":
        asyncio.run(_scan_once(s, db, llm))
    elif args.comando == "agenda":
        print(render_agenda(s, db))
    elif args.comando == "relatorio":
        texto, path = asyncio.run(weekly_report(s, db, llm))
        print(texto, f"\nSalvo em {path}", sep="\n")


if __name__ == "__main__":
    main()
