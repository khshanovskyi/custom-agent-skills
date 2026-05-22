import asyncio
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

from agent_demo.agent_claude import ClaudeAgent
from agent_demo.models.message import Message
from agent_demo.models.role import Role
from agent_demo.models.skill import load_skills
from agent_demo.prompt_utils import build_system_prompt
from agent_demo.tools.base import BaseTool
from agent_demo.tools.container.docker_code_interpreter_tool import DockerCodeInterpreterTool
from agent_demo.tools.skills.read_skill_tool import ReadSkillTool

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

SKILLS_DIR = Path(__file__).parent / "_skills"
# Pinned to a specific digest to prevent supply-chain risk from floating tags.
# To update: docker inspect --format='{{index .RepoDigests 0}}' python:3.11-slim
DOCKER_IMAGE = "python@sha256:2c285c669cc837aa3bcf1af23ea1932b7b5214f9c9d3aad22417446ad91cb4fb"
MODEL = "claude-sonnet-4-6"


async def main():
    skills = load_skills(SKILLS_DIR)
    if not skills:
        print(f"ERROR: no valid skills found in {SKILLS_DIR}")
        return
    print(f"Loaded {len(skills)} skill(s): {[s.name for s in skills]}")

    system_prompt = build_system_prompt(skills)
    print(f"📄 System prompt: \n {system_prompt}")
    messages: list[Message] = []

    known_skills = frozenset(s.name for s in skills)
    code_interpreter = DockerCodeInterpreterTool(
        skills_dir=SKILLS_DIR,
        image=DOCKER_IMAGE,
        known_skills=known_skills,
    )
    tools: list[BaseTool] = [
        ReadSkillTool(skills_dir=SKILLS_DIR),
        code_interpreter,
    ]

    agent = ClaudeAgent(
        client=anthropic.Anthropic(api_key=ANTHROPIC_API_KEY),
        model=MODEL,
        instructions=system_prompt,
        tools=tools,
    )

    try:
        while True:
            user_input = input("➡️: ").strip()
            if not user_input:
                continue
            if user_input.lower() == "exit":
                break

            messages.append(Message(role=Role.USER, content=user_input))

            assistant_message = await agent.chat_completion(
                messages=messages,
                log_messages=True,
            )
            messages.append(assistant_message)
            await code_interpreter.reset_all()
    finally:
        await code_interpreter.close()


if __name__ == "__main__":
    asyncio.run(main())
