from dataclasses import dataclass
from typing import Any

from agent_demo.models.role import Role


@dataclass
class Message:
    role: Role
    content: str
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    def to_input_items(self) -> list[dict[str, Any]]:
        if self.role == Role.TOOL:
            return [{
                "type": "function_call_output",
                "call_id": self.tool_call_id,
                "output": self.content,
            }]

        if self.role == Role.ASSISTANT:
            items: list[dict[str, Any]] = []
            if self.content:
                items.append({
                    "role": "assistant",
                    "content": self.content,
                })
            if self.tool_calls:
                for tc in self.tool_calls:
                    items.append({
                        "type": "function_call",
                        "call_id": tc["call_id"],
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                    })
            return items

        return [{
            "role": self.role.value,
            "content": self.content,
        }]
