"""Subscription orchestration with a mandatory benchmark anchor."""

from collections.abc import Iterable

from app.analytics.constants import BENCHMARK_ANCHOR_SYMBOL
from app.analytics.quotes.protocol import QuoteSource


class QuoteSubscriptionManager:
    """Keep requested symbols and the benchmark anchor subscribed."""

    def __init__(
        self, source: QuoteSource, initial_symbols: Iterable[str] = ()
    ) -> None:
        self._source = source
        self._symbols = {
            symbol.strip().upper() for symbol in initial_symbols if symbol.strip()
        }
        self._symbols.add(BENCHMARK_ANCHOR_SYMBOL)

    @property
    def active_symbols(self) -> frozenset[str]:
        return frozenset(self._symbols)

    async def start(self) -> None:
        await self._source.subscribe(self._symbols)

    async def subscribe(self, symbols: Iterable[str]) -> None:
        additions = {
            symbol.strip().upper() for symbol in symbols if symbol.strip()
        }
        additions.add(BENCHMARK_ANCHOR_SYMBOL)
        new_symbols = additions - self._symbols
        self._symbols.update(additions)
        if new_symbols:
            await self._source.subscribe(new_symbols)

    async def unsubscribe(self, symbols: Iterable[str]) -> None:
        removals = {
            symbol.strip().upper() for symbol in symbols if symbol.strip()
        }
        removals.discard(BENCHMARK_ANCHOR_SYMBOL)
        removed = self._symbols & removals
        self._symbols.difference_update(removals)
        if removed:
            await self._source.unsubscribe(removed)
