from __future__ import annotations

from dataclasses import dataclass, field

# Ciclo de vida de uma vaga no pipeline. Você move as etapas pelo Telegram.
STATUS = {
    "nova": "🎯 Vagas para candidatar",
    "candidatado": "⏳ Aguardando Resposta",
    "negociando": "💬 Em Negociação",
    "pronto": "🔥 Prontos para Executar (Escopo Fechado)",
    "concluido": "✅ Concluídos",
    "descartada": "Descartadas",
}
ORDEM_RAIAS = ["pronto", "negociando", "candidatado", "nova", "concluido"]


@dataclass
class Job:
    platform: str
    external_id: str
    title: str
    description: str
    url: str
    budget_min: float | None = None  # já convertido para BRL
    budget_max: float | None = None
    budget_raw: str = ""
    is_hourly: bool = False
    skills: list[str] = field(default_factory=list)
    bids: int | None = None

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.external_id}"


@dataclass
class Score:
    total: int
    area: int
    orcamento: int
    clareza: int
    motivo: str = ""
    red_flags: list[str] = field(default_factory=list)
    fonte: str = "heuristica"  # ou "llm"
