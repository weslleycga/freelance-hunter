from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def _path(value: str) -> Path:
    return Path(os.path.expanduser(value)).resolve()


@dataclass
class Settings:
    anthropic_api_key: str
    claude_model: str
    telegram_token: str
    telegram_chat_id: int | None
    valor_hora_minimo: float
    valor_minimo_projeto: float
    prazo_seguranca_dias: int
    match_score_minimo: int
    intervalo_busca_min: int
    agenda_dir: Path
    db_path: Path
    perfil: dict = field(default_factory=dict)

    @property
    def llm_ativo(self) -> bool:
        return bool(self.anthropic_api_key)


def load_settings(env_file: Path | None = None, perfil_file: Path | None = None) -> Settings:
    load_dotenv(env_file or ROOT / ".env")
    perfil_path = perfil_file or ROOT / "config" / "perfil.yaml"
    with open(perfil_path, encoding="utf-8") as f:
        perfil = yaml.safe_load(f)

    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    return Settings(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        claude_model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=int(chat_id) if chat_id else None,
        valor_hora_minimo=float(os.getenv("VALOR_HORA_MINIMO", "60")),
        valor_minimo_projeto=float(os.getenv("VALOR_MINIMO_PROJETO", "300")),
        prazo_seguranca_dias=int(os.getenv("PRAZO_SEGURANCA_DIAS", "2")),
        match_score_minimo=int(os.getenv("MATCH_SCORE_MINIMO", "75")),
        intervalo_busca_min=int(os.getenv("INTERVALO_BUSCA_MIN", "30")),
        agenda_dir=_path(os.getenv("AGENDA_DIR", str(ROOT / "agenda"))),
        db_path=_path(os.getenv("DB_PATH", str(ROOT / "data" / "hunter.db"))),
        perfil=perfil,
    )
