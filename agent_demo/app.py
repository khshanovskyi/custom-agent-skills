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
    # 1. Load skills: walk _skills/, parse each SKILL.md's YAML frontmatter, validate it.
    #    Only frontmatter is loaded here — bodies stay on disk and are fetched on demand
    #    via read_skill, which is how we keep the system prompt cheap.
    skills = load_skills(SKILLS_DIR)
    if not skills:
        print(f"ERROR: no valid skills found in {SKILLS_DIR}")
        return
    print(f"Loaded {len(skills)} skill(s): {[s.name for s in skills]}")

    # 2. Build the system prompt: serializes skill frontmatter into an <available_skills>
    #    XML block so the model sees names/descriptions and decides when to activate one.
    #    `messages` is the rolling conversation history for the REPL.
    system_prompt = build_system_prompt(skills)
    print(f"📄 System prompt: \n {system_prompt}")
    messages: list[Message] = []

    # 3. Create tools:
    #    - DockerCodeInterpreterTool lazily starts one network-isolated container per
    #      agent lifetime, bind-mounts _skills/ read-only at /skills, and runs a
    #      persistent Python kernel (state survives across execute_code calls).
    #    - ReadSkillTool lets the model fetch any file under _skills/ by relative path.
    code_interpreter = DockerCodeInterpreterTool(
        skills_dir=SKILLS_DIR,
        image=DOCKER_IMAGE,
    )
    tools: list[BaseTool] = [
        ReadSkillTool(skills_dir=SKILLS_DIR),
        code_interpreter,
    ]

    # 4. Construct the agent: wires the OpenAI client, model, system prompt, and tools
    #    into the recursive chat-completion loop owned by Agent.
    agent = Agent(
        client=OpenAI(api_key=OPENAI_API_KEY),
        model="gpt-5.2",
        instructions=system_prompt,
        tools=tools,
    )

    try:
        # 5. REPL / agent loop: read a user line, append as USER message, call the agent.
        #    Inside chat_completion the loop is recursive — if the response carries
        #    tool_calls, each is dispatched (read_skill / execute_code), tool-role
        #    results are appended, and it recurses until finish_reason != "tool_calls".
        #    Only the final assistant message is appended to the outer history.
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
        # 6. Cleanup: guarantees the Docker sandbox is torn down on exit, Ctrl-C,
        #    or exception — otherwise the container would leak.
        await code_interpreter.close()


if __name__ == "__main__":
    asyncio.run(main())
