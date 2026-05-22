import json
import time

import anthropic

from agent_demo.models.message import Message
from agent_demo.models.role import Role
from agent_demo.tools.base import BaseTool


class ClaudeAgent:

    def __init__(
        self,
        client: anthropic.Anthropic,
        model: str,
        instructions: str,
        tools: list[BaseTool] | None = None,
    ):
        self._client = client
        self._model = model
        self._instructions = instructions
        self._tools: dict[str, BaseTool] = {tool.name: tool for tool in (tools or [])}
        self._tools_schemas = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in (tools or [])
        ]
        print(json.dumps(self._tools_schemas, indent=4))

    async def chat_completion(self, messages: list[Message], log_messages: bool = False) -> Message:
        anthropic_messages = []
        for msg in messages:
            if msg.role == Role.USER:
                anthropic_messages.append({"role": "user", "content": msg.content})
            elif msg.role == Role.ASSISTANT:
                anthropic_messages.append({"role": "assistant", "content": msg.content})

        if log_messages:
            print("\n--- REQUEST ---")
            print(json.dumps(anthropic_messages, indent=2, default=str))

        return await self._chat_completion(anthropic_messages, log_messages)

    async def _chat_completion(self, messages: list[dict], log_messages: bool = False) -> Message:
        kwargs = {
            "model": self._model,
            "max_tokens": 4096,
            "system": self._instructions,
            "messages": messages,
        }
        if self._tools_schemas:
            kwargs["tools"] = self._tools_schemas

        t0 = time.perf_counter()
        response = self._client.messages.create(**kwargs)
        print(f"⏱️  Claude API: {(time.perf_counter() - t0) * 1000:.0f} ms")

        text_parts: list[str] = []
        tool_calls: list[dict] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({
                    "call_id": block.id,
                    "name": block.name,
                    "arguments": json.dumps(block.input),
                })

        if tool_calls:
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for tc in tool_calls:
                tool = self._tools.get(tc["name"])
                if tool is None:
                    content = f"ERROR: unknown tool '{tc['name']}'"
                else:
                    result_msg = await tool.execute(tc["call_id"], json.loads(tc["arguments"]))
                    content = result_msg.content

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc["call_id"],
                    "content": content,
                })

            messages.append({"role": "user", "content": tool_results})

            if log_messages:
                print(json.dumps(messages[-2:], indent=2, default=str))

            return await self._chat_completion(messages, log_messages)

        if log_messages:
            print("---------------\n")

        text = "".join(text_parts)
        print(f"🤖: {text}")
        print()

        return Message(role=Role.ASSISTANT, content=text)
