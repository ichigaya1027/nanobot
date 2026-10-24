"""Channel-supplied turn behavior, independent of transport implementations."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import InboundMessage


@dataclass(frozen=True)
class TurnPolicy:
    tools: ToolRegistry
    instructions: str
    tool_only_output: bool = False
    observe_input: Callable[[InboundMessage], None] | None = None
    completed: Callable[[], None] | None = None
    prepare_messages: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None


TurnPolicyProvider = Callable[[InboundMessage, str, ToolRegistry], TurnPolicy | None]
