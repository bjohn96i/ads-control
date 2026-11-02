"""Tools for checking the panel map by hand: run a load and see what moves."""

import asyncio
from collections.abc import Callable

from adscontrol.refoss.client import RefossClient

INCOMING_CHANNELS = (1, 7)
MIN_CHANNEL_MOVE_W = 20.0


def measured_multiplier(delta_incoming_w: float, delta_channel_w: float) -> float:
    if abs(delta_channel_w) < MIN_CHANNEL_MOVE_W:
        raise ValueError("this channel did not move, so it is probably not this load")
    return delta_incoming_w / delta_channel_w


async def watch(
    client: RefossClient, channel: int, echo: Callable[[str], None], interval_s: float = 5
) -> None:
    """Print the channel and the incoming total, relative to where they started."""
    base_channel = base_incoming = None
    while True:
        by_channel = {r.channel: r.power_w for r in await client.read_channels()}
        now_channel = by_channel[channel]
        now_incoming = sum(by_channel[c] for c in INCOMING_CHANNELS)
        if base_channel is None:
            base_channel, base_incoming = now_channel, now_incoming
        delta_channel = now_channel - base_channel
        delta_incoming = now_incoming - base_incoming
        try:
            multiplier = f"{measured_multiplier(delta_incoming, delta_channel):.2f}"
        except ValueError:
            multiplier = "-"
        echo(
            f"channel {now_channel:8.1f} W ({delta_channel:+8.1f})   "
            f"incoming {now_incoming:8.1f} W ({delta_incoming:+8.1f})   multiplier {multiplier}"
        )
        await asyncio.sleep(interval_s)
