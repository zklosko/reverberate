"""
Echo Integration Interface device logic.

This file mimics the I/O of the EII module.

TODO: finish sequence commands
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Union

REQUEST_PREFIX = "E$"
RESPONSE_PREFIX = "E>"
HELP_TEXT = (
    "Available commands:"
    "E$pst act: spc_num(1-16), pst_num(1-64), time{EOM}"
    "E$off: spc_num(1-16), time{EOM}"
    "E$seq act: spc_num(1-16), seq_num(1-4){EOM}"
    "E$seq dact: spc_num(1-16), seq_num(1-4){EOM}"
    "E$zone int: spc_num(1-16), zn_num(1-16), level(0-255), time{EOM}"
    "E$pst get: spc_num(1-16){EOM}"
    "E$off get: spc_num(1-16){EOM}"
    "E$seq get: spc_num(1-16){EOM}"
    "E$sync get: spc_num(0-16){EOM}"
    "E$zone int get: spc_num(1-16){EOM}"
    "E$help{EOM}"
)
SYNC_ACK = f"{RESPONSE_PREFIX}lok"

class MalformedPacketError(Exception):
    """Raise this when incoming bytes don't match the expected format."""

@dataclass
class ArgSpec:
    name: str
    type: type  # can be int or float
    min: Union[int, float]
    max: Union[int, float]

COMMAND_SCHEMAS: Dict[str, list[ArgSpec]] = {
    "pst act":      [ArgSpec("space", int, 1, 16), ArgSpec("preset", int, 1, 64), ArgSpec("fade_time", float, 0.0, 25.4)],
    "off":          [ArgSpec("space", int, 1, 16), ArgSpec("fade_time", float, 0.0, 25.4)],
    "seq act":      [ArgSpec("space", int, 1, 16), ArgSpec("seq_num", int, 1, 4)],
    "seq dact":     [ArgSpec("space", int, 1, 16), ArgSpec("seq_num", int, 1, 4)],
    "zone int":     [ArgSpec("space", int, 1, 16), ArgSpec("zone", int, 1, 16), ArgSpec("level", int, 0, 255), ArgSpec("fade_time", float, 0.0, 25.4)],
    "pst get":      [ArgSpec("space", int, 1, 16)],
    "off get":      [ArgSpec("space", int, 1, 16)],
    "seq get":      [ArgSpec("space", int, 1, 16)],
    "sync get":     [ArgSpec("space", int, 0, 16)],  # 0 = all spaces
    "zone int get": [ArgSpec("space", int, 1, 16)],
    "help":         [],
}

@dataclass
class ParsedCommand:
    command: str
    args: Dict[str, Any]
    raw_len: int


def parse_packet(data: bytes, state) -> ParsedCommand:
    """
    Decode raw bytes from the plugin into a structured command.
    """
    text = data.decode('ascii')
    text = text.replace(state.eom.value, "") # remove EOL character

    if text[0:2] != REQUEST_PREFIX:
        raise MalformedPacketError("Packet does not include correct request prefix")
    
    text = text[len(REQUEST_PREFIX):]

    if ":" in text:
        cmd, raw_arg_str = text.split(":", 1)  # returns string after ":"
        raw_args = [a.strip() for a in raw_arg_str.split(",")]  # split at ","/remove whitespace
    else:  # help command sent
        cmd = text
        raw_args = []
    
    cmd_schema = COMMAND_SCHEMAS.get(cmd)  # get correct schema to iterate through
    if cmd_schema is None:
        raise MalformedPacketError(f"Unknown command: {cmd}")

    if len(raw_args) != len(cmd_schema):  # length mismatch check
        raise MalformedPacketError(
            f"Expected {len(cmd_schema)} args for '{cmd}', got {len(raw_args)}"
        )

    args = {}
    for spec, raw_arg in zip(cmd_schema, raw_args):
        try:
            value = spec.type(raw_arg)  # cast using the spec stored on type
        except ValueError:
            raise MalformedPacketError(f"{spec.name} must be a {spec.type.__name__}, got {raw_arg!r}")
        if not (spec.min <= value <= spec.max):
            raise MalformedPacketError(f"{spec.name} out of range: {value}")
        args[spec.name] = value

    return ParsedCommand(
        command=cmd,
        args=args,
        raw_len=len(data),
    )

def format_echo_reply(cmd: ParsedCommand, state) -> bytes:
    """
    Default reply shape: echo the command name + its args back,
    prefixed with E> instead of E$.

    TODO: confirm this matches your controller's exact echo format —
    e.g. does it reformat args (spacing, decimal places on fade_time)
    or send back the literal string that was sent?
    """
    arg_str = ", ".join(str(v) for v in cmd.args.values())
    return f"{RESPONSE_PREFIX}{cmd.command}: {arg_str}{state.eom.value}".encode("ascii")

async def build_reply(cmd: ParsedCommand, state) -> Optional[bytes]:
    """
    Returns the PRIMARY/immediate reply for a command.

    NOTE: "sync get" is special — the real controller sends an immediate
    ack (SYNC_ACK) and then a SEPARATE follow-up packet with the actual
    space data. That second packet can't come from this function alone;
    udp_server.py's _handle() will need a branch that, after sending
    this function's return value, also sends a second packet for
    "sync get" specifically.
    """
    if cmd.command == "help":
        return f"{HELP_TEXT}{state.eom.value}".encode("ascii")

    if cmd.command == "sync get":
        return f"{SYNC_ACK}{state.eom.value}".encode("ascii")
        # TODO: the follow-up data packet is built/sent separately —
        # see build_sync_data_reply() below and udp_server.py

    if cmd.command == "pst get":
        return await build_pst_get_reply(cmd.args["space"], state)
    elif cmd.command == "zone int get":
        return await build_zone_int_get_reply(cmd.args["space"], state)
    elif cmd.command == "off get":
        return await build_off_get_reply(cmd.args["space"], state)
    # else:
    #     return format_echo_reply(cmd, state)  # reply as is for now if not implemented

async def build_sync_data_reply(space_num: int, state) -> bytes:
    """
    Builds the follow-up packet for "sync get" — all data for
    the given space, or all spaces if space_num == 0.
    Needs a format for how multiple spaces/zones get serialized into
    one reply string.

    Sequence status is not included yet.

    All lines are concetenated into a SINGLE UDP payload, but with multiple EOM characters.
    """
    space_nums = range(1, 17) if space_num == 0 else [space_num]

    lines = []
    async with state.lock:
        for num in space_nums:
            space = state.spaces[num]
            lines.append(f"{RESPONSE_PREFIX}pst act: {num}, {space.active_preset}{state.eom.value}")
            for zone_num, level in space.zones.items():
                lines.append(f"{RESPONSE_PREFIX}zone int: {num}, {zone_num}, {level}{state.eom.value}")
            # TODO: sequence status lines go here later

    return "".join(lines).encode("ascii")

async def build_pst_get_reply(space_num: int, state) -> bytes:
    """Replies with the real active preset for the given space"""
    async with state.lock:
        if space_num not in state.spaces:
            raise ValueError(f"Invalid space number: {space_num}")
        preset = state.spaces[space_num].active_preset

    return f"{RESPONSE_PREFIX}pst get: {space_num}, {preset}{state.eom.value}".encode("ascii")

async def build_zone_int_get_reply(space_num: int, state) -> bytes:
    """Replies with zone data for a specific space"""
    async with state.lock:
        if space_num not in state.spaces:
            raise ValueError(f"Invalid space number: {space_num}")
        space = state.spaces[space_num]
        lines = []
        for zone_num, level in space.zones.items():
            lines.append(f"{RESPONSE_PREFIX}zone int: {space_num}, {zone_num}, {level}{state.eom.value}")
    
    return "".join(lines).encode("ascii")

async def build_off_get_reply(space_num: int, state) -> bytes:
    """Replies whether a space is 'off' — defined as all zones being 0."""
    async with state.lock:
        if space_num not in state.spaces:
            raise ValueError(f"Invalid space number: {space_num}")
        space = state.spaces[space_num]
        is_off = all(level == 0 for level in space.zones.values())

    bool_char = "1" if is_off else "0"
    return f"{RESPONSE_PREFIX}space off: {space_num}, {bool_char}{state.eom.value}".encode("ascii")

async def apply_to_state(cmd: ParsedCommand, state) -> None:
    """
    Commits changes to internal state. Executed by command building in udp_server.py
    """
    if cmd.command == "pst act":
        await state.set_active_preset(cmd.args["space"], cmd.args["preset"])
    elif cmd.command == "zone int":
        await state.set_zone_int(cmd.args["space"], cmd.args["zone"], cmd.args["level"])
    elif cmd.command == "seq act":
        await state.set_seq(cmd.args["space"], cmd.args["seq_num"], True)
    elif cmd.command == "seq dact":
        await state.set_seq(cmd.args["space"], cmd.args["seq_num"], False)
    elif cmd.command == "off":
        await state.set_space_off(cmd.args["space"])
    # get-commands and "help" don't mutate anything — no-op for those
