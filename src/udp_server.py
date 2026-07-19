"""
The actual "fake fixture" — an asyncio UDP endpoint that receives packets
from your plugin, parses them, updates state, and replies.
"""

import asyncio
import logging
import time

from src.protocol import parse_packet, build_reply, apply_to_state, build_sync_data_reply, MalformedPacketError
from src.state import fixture_state, PacketLogEntry

logger = logging.getLogger("udp_server")


class LightingControllerProtocol(asyncio.DatagramProtocol):
    def __init__(self, state=fixture_state):
        self.state = state
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport
        logger.info("UDP listener ready")

    def datagram_received(self, data: bytes, addr) -> None:
        # Schedule as a task so we can use await (asyncio.sleep for delay,
        # state locks, etc) — datagram_received itself must stay sync.
        asyncio.create_task(self._handle(data, addr))

    def error_received(self, exc: Exception) -> None:
        logger.warning(f"UDP error: {exc}")

    async def _handle(self, data: bytes, addr) -> None:
        addr_str = f"{addr[0]}:{addr[1]}"

        # Step 1. Parse packet and catch error
        try:
            cmd = parse_packet(data, self.state)
        except MalformedPacketError as e:
            # note = f"malformed: {e}"
            await self.state.record(PacketLogEntry(
                direction="rx", timestamp=time.time(), addr=addr_str,
                raw=data, parsed=None,
            ))
            logger.warning(f"Malformed packet from {addr_str}: {e}")
            return

        await self.state.record(PacketLogEntry(
            direction="rx", timestamp=time.time(), addr=addr_str,
            raw=data, parsed={"command": cmd.command, "args": cmd.args},
        ))

        # Step 2. Apply to state
        try:
            await apply_to_state(cmd, self.state)
        except ValueError as e:
            logger.warning(f"State error handling {cmd.command} from {addr_str}: {e}")
            return

        # Step 3. Build reply
        reply = await build_reply(cmd, self.state)

        if reply is None:
            return

        # Step 4. Send it.
        assert self.transport is not None
        self.transport.sendto(reply, addr)
        await self.state.record(PacketLogEntry(
            direction="tx", timestamp=time.time(), addr=addr_str,
            raw=reply, parsed={"command": cmd.command, "args": cmd.args},
        ))

        # Step 5. "sync get" gets a separate follow-up packet
        if cmd.command == "sync get":
            sync_data = await build_sync_data_reply(cmd.args["space"], self.state)
            self.transport.sendto(sync_data, addr)
            await self.state.record(PacketLogEntry(
                direction="tx", timestamp=time.time(), addr=addr_str,
                raw=sync_data, parsed={"command": cmd.command, "args": cmd.args}
            ))


async def start_udp_server(host: str, port: int):
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: LightingControllerProtocol(fixture_state),
        local_addr=(host, port),
    )
    logger.info(f"Mock lighting controller UDP listener on {host}:{port}")
    return transport, protocol
