"""Wrapper mínimo da Claude API com saída estruturada via tool use forçado."""
from __future__ import annotations

import logging

import anthropic

log = logging.getLogger(__name__)


class LLM:
    def __init__(self, api_key: str, model: str):
        self.client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=3)
        self.model = model

    async def structured(self, system: str, user: str, tool_name: str, schema: dict,
                         max_tokens: int = 2000) -> dict | None:
        """Devolve o JSON da ferramenta, ou None se a API falhar (o chamador usa o fallback)."""
        try:
            msg = await self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                tools=[{"name": tool_name, "description": "Registra o resultado.", "input_schema": schema}],
                tool_choice={"type": "tool", "name": tool_name},
            )
        except anthropic.APIError as e:
            log.error("Claude API falhou (%s); usando fallback", e)
            return None
        for block in msg.content:
            if block.type == "tool_use":
                return block.input
        log.error("Claude não retornou tool_use; usando fallback")
        return None
