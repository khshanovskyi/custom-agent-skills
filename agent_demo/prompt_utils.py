import xml.etree.ElementTree as ET

from agent_demo.models.skill import SkillMetadata

CODE_EXECUTION_TOOL_NAME = "execute_code"


def _build_available_skills_xml(skills: list[SkillMetadata]) -> str:
    root = ET.Element("available_skills")
    for skill in skills:
        el = ET.SubElement(root, "skill", attrib={"name": skill.name})
        ET.SubElement(el, "description").text = skill.description
        if skill.license:
            ET.SubElement(el, "license").text = skill.license
        if skill.compatibility:
            ET.SubElement(el, "compatibility").text = skill.compatibility
        if skill.metadata:
            meta = ET.SubElement(el, "metadata")
            for k, v in skill.metadata.items():
                ET.SubElement(meta, k).text = str(v)
        if skill.allowed_tools:
            ET.SubElement(el, "allowed-tools").text = " ".join(skill.allowed_tools)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode")


def build_system_prompt(skills: list[SkillMetadata]) -> str:
    return f"""\
You are a helpful AI assistant that helps users with their tasks.

# Skills

## Available skills
{_build_available_skills_xml(skills)}

## How to use skills

When the user's request matches a skill, activate it:
1. Call `read_skill` with the skill's SKILL.md path (e.g. path="/<skill-name>/SKILL.md") to load
   its description and supporting resources.
2. Read additional skill resources (scripts, references, examples) as needed — either with
   `read_skill`, or from inside `{CODE_EXECUTION_TOOL_NAME}` where the skills directory is
   mounted read-only at `/skills/<skill-name>/...`.
3. If the skill requires running code, execute it with `{CODE_EXECUTION_TOOL_NAME}` (Python by
   default, or pass `language="bash"`). Python state persists across calls in the conversation.

Always read the relevant SKILL.md before performing the task.\
"""
