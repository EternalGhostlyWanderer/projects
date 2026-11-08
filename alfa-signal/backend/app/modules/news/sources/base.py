from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Protocol


@dataclass(frozen=True)
class RawNewsItem:
    title: str
    url: str
    source: str
    published_at: Optional[datetime] = None
    summary: Optional[str] = None


class NewsSource(Protocol):
    name: str

    def fetch(self) -> List[RawNewsItem]:
        ...