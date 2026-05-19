import json

from openai import OpenAI

from agent_demo.models.message import Message
from agent_demo.models.role import Role
from agent_demo.tools.base import BaseTool


class Agent:

    def __init__(
        self,
        client: OpenAI,
        model: str,
        instructions: str,
        tools: list[BaseTool] | None = None,
    ):
        self._client = client
        self._model = model
        self._instructions = instructions
        self._tools: dict[str, BaseTool] = {tool.name: tool for tool in (tools or [])}
        self._tools_schemas = [tool.schema for tool in tools] if tools else []
        print(json.dumps(self._tools_schemas, indent=4))

    async def chat_completion(self, messages: list[Message], log_messages: bool = False) -> Message:
        if log_messages:
            print("\n--- REQUEST ---")
            print(json.dumps(self._to_input(messages), indent=2, default=str))

        return await self._chat_completion(messages, log_messages)

    async def _chat_completion(self, messages: list[Message], log_messages: bool = False) -> Message:
        request = {
            "model": self._model,
            "instructions": self._instructions,
            "input": self._to_input(messages),
            "tools": self._tools_schemas,
        }

        response = self._client.responses.create(**request)

        text_parts: list[str] = []
        tool_calls: list[dict[str, str]] = []
        for item in response.output:
            if item.type == "message":
                for chunk in item.content:
                    text = getattr(chunk, "text", None)
                    if text:
                        text_parts.append(text)
            elif item.type == "function_call":
                tool_calls.append({
                    "call_id": item.call_id,
                    "name": item.name,
                    "arguments": item.arguments,
                })

        assistant_msg = Message(
            role=Role.ASSISTANT,
            content="".join(text_parts),
            tool_calls=tool_calls or None,
        )

        if tool_calls:
            messages.append(assistant_msg)
            tool_messages = await self._dispatch_tool_calls(tool_calls)
            messages.extend(tool_messages)

            if log_messages:
                print(json.dumps(assistant_msg.to_input_items(), indent=2, default=str))
                print(json.dumps(
                    [item for m in tool_messages for item in m.to_input_items()],
                    indent=2,
                    default=str,
                ))
            return await self._chat_completion(messages, log_messages)

        if log_messages:
            print("---------------\n")

        print(f"🤖: {assistant_msg.content}")
        print()

        return assistant_msg

    async def _dispatch_tool_calls(self, tool_calls: list[dict[str, str]]) -> list[Message]:
        tool_messages: list[Message] = []
        for tc in tool_calls:
            tool = self._tools.get(tc["name"])
            if tool is None:
                content = f"ERROR: unknown tool '{tc['name']}'"
            else:
                result_msg = await tool.execute(tc["call_id"], json.loads(tc["arguments"]))
                content = result_msg.content

            tool_messages.append(
                Message(
                    role=Role.TOOL,
                    tool_call_id=tc["call_id"],
                    name=tc["name"],
                    content=content,
                )
            )
        return tool_messages

    @staticmethod
    def _to_input(messages: list[Message]) -> list[dict]:
        return [item for msg in messages for item in msg.to_input_items()]
