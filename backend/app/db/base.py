from abc import ABC, abstractmethod
from datetime import date
from typing import Optional


class KeywordRepository(ABC):
    @abstractmethod
    async def save_keywords(self, keywords: list[dict]) -> None:
        ...

    @abstractmethod
    async def get_keywords(self, lookup_date: Optional[date] = None) -> list[dict]:
        ...

    @abstractmethod
    async def delete_keyword(self, keyword_id: int) -> None:
        ...

    @abstractmethod
    async def save_volume_history(self, records: list[dict]) -> None:
        ...

    @abstractmethod
    async def get_volume_history(self, keyword_jp: Optional[str] = None) -> list[dict]:
        ...


class BidRepository(ABC):
    @abstractmethod
    async def save_bid_history(self, records: list[dict]) -> None:
        ...

    @abstractmethod
    async def get_bid_history(self, keyword_jp: Optional[str] = None) -> list[dict]:
        ...


class ProductRepository(ABC):
    @abstractmethod
    async def save_qoo10_products(self, products: list[dict]) -> None:
        ...

    @abstractmethod
    async def get_qoo10_products(self, search_keyword: Optional[str] = None) -> list[dict]:
        ...

    @abstractmethod
    async def save_domestic_products(self, products: list[dict]) -> None:
        ...

    @abstractmethod
    async def get_domestic_products(self, source: Optional[str] = None) -> list[dict]:
        ...


class TrackingRepository(ABC):
    @abstractmethod
    async def save_tracking_item(self, item: dict) -> int:
        ...

    @abstractmethod
    async def get_tracking_items(self) -> list[dict]:
        ...

    @abstractmethod
    async def save_tracking_history(self, records: list[dict]) -> None:
        ...

    @abstractmethod
    async def get_tracking_history(self, tracking_item_id: int) -> list[dict]:
        ...


class BestsellerRepository(ABC):
    @abstractmethod
    async def save_bestseller_items(self, items: list[dict]) -> None:
        ...

    @abstractmethod
    async def get_bestseller_items(self, category: Optional[str] = None) -> list[dict]:
        ...
