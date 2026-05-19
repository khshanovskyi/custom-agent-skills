import asyncio
import os
from pathlib import Path

from openai import OpenAI

from agent_demo.agent import Agent
from agent_demo.models.message import Message
from agent_demo.models.role import Role
from agent_demo.models.skill import load_skills
from agent_demo.prompt_utils import build_system_prompt
from agent_demo.tools.base import BaseTool
from agent_demo.tools.container.docker_code_interpreter_tool import DockerCodeInterpreterTool
from agent_demo.tools.skills.read_skill_tool import ReadSkillTool

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

SKILLS_DIR = Path(__file__).parent / "_skills"
DOCKER_IMAGE = "python:3.11-slim"


async def main():
    skills = load_skills(SKILLS_DIR)
    if not skills:
        print(f"ERROR: no valid skills found in {SKILLS_DIR}")
        return
    print(f"Loaded {len(skills)} skill(s): {[s.name for s in skills]}")

    system_prompt = build_system_prompt(skills)
    print(f"📄 System prompt: \n {system_prompt}")
    messages: list[Message] = []

    code_interpreter = DockerCodeInterpreterTool(
        skills_dir=SKILLS_DIR,
        image=DOCKER_IMAGE,
    )
    tools: list[BaseTool] = [
        ReadSkillTool(skills_dir=SKILLS_DIR),
        code_interpreter,
    ]

    agent = Agent(
        client=OpenAI(api_key=OPENAI_API_KEY),
        model="gpt-5.2",
        instructions=system_prompt,
        tools=tools,
    )

    try:
        while True:
            user_input = input("➡️: ").strip()
            if user_input.lower() == "exit":
                break

            messages.append(
                Message(
                    role=Role.USER,
                    content=user_input
                )
            )

            assistant_message = await agent.chat_completion(
                messages = messages,
                log_messages=True,
            )
            messages.append(assistant_message)
    finally:
        await code_interpreter.close()


if __name__ == "__main__":
    asyncio.run(main())
