from __future__ import annotations

import html
import re
from abc import ABC, abstractmethod

from ..models import Job

_NUM = re.compile(r"\d[\d.,]*")
_TAG = re.compile(r"<[^>]+>")
_CURRENCY = {"R$": "BRL", "BRL": "BRL", "USD": "USD", "US$": "USD", "$": "USD", "EUR": "EUR", "€": "EUR"}


def strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.I)
    return html.unescape(_TAG.sub("", text)).strip()


def _to_float(s: str) -> float:
    # "1.500,00" -> 1500.0 ; "1,500" -> 1500.0 ; "250" -> 250.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if len(s.split(",")[-1]) == 2 else s.replace(",", "")
    elif s.count(".") >= 1 and len(s.split(".")[-1]) == 3:
        s = s.replace(".", "")
    return float(s)


def parse_budget(raw: str, cambio: dict[str, float]) -> tuple[float | None, float | None]:
    """'USD 100 - 250' -> (540.0, 1350.0) em BRL. 'Menos de R$ 500' -> (None, 500)."""
    if not raw:
        return None, None
    moeda = "BRL"
    for sym, code in _CURRENCY.items():
        if sym in raw:
            moeda = code
            break
    taxa = cambio.get(moeda, 1.0)
    nums = [_to_float(n.rstrip(".,")) * taxa for n in _NUM.findall(raw)]
    if not nums:
        return None, None
    low = raw.lower()
    if "menos de" in low or "até" in low or "less than" in low:
        return None, nums[0]
    if "mais de" in low or "more than" in low or "over" in low:
        return nums[0], None
    return min(nums), max(nums)


class Source(ABC):
    name: str

    def __init__(self, client, cambio: dict[str, float]):
        self.client = client
        self.cambio = cambio

    @abstractmethod
    async def fetch(self) -> list[Job]: ...
