"""Screenshot 5 of 6 — crop everything below the STUBS banner."""

from contextlib import AsyncExitStack, asynccontextmanager

# ── 5. AsyncExitStack — the same discipline once coroutines are involved ────


@asynccontextmanager
async def channel(broker, topic: str):
    handle = await broker.open(topic)
    try:
        yield handle
    finally:
        await broker.close(handle)  # awaited teardown, guaranteed


async def fan_out(broker, topics: list[str], metrics) -> list[str]:
    async with AsyncExitStack() as stack:
        channels = [await stack.enter_async_context(channel(broker, t)) for t in topics]

        stack.push_async_callback(broker.flush)  # awaited on the way out
        stack.callback(metrics.close)  # plain callables still welcome

        return [await handle.send("ping") for handle in channels]


# One stack, mixed sync and async cleanup, unwound in reverse.
# The alternative is try/finally nested four deep, with awaits inside finally
# that swallow whatever went wrong first.


# ── STUBS — not part of the screenshot ──────────────────────────────────────

if __name__ == "__main__":
    import asyncio

    events: list[str] = []

    class Handle:
        def __init__(self, topic: str) -> None:
            self.topic = topic

        async def send(self, payload: str) -> str:
            return f"{self.topic}:{payload}"

    class Broker:
        async def open(self, topic: str) -> Handle:
            events.append(f"open {topic}")
            return Handle(topic)

        async def close(self, handle: Handle) -> None:
            events.append(f"close {handle.topic}")

        async def flush(self) -> None:
            events.append("flush")

    class Metrics:
        def close(self) -> None:
            events.append("metrics closed")

    print(asyncio.run(fan_out(Broker(), ["orders", "refunds"], Metrics())))
    # → ['orders:ping', 'refunds:ping']
    print(events)
    # → ['open orders', 'open refunds', 'metrics closed', 'flush',
    #    'close refunds', 'close orders']
