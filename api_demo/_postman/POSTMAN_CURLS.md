# Postman / cURL — Skills API

Raw HTTP equivalents for working with the OpenAI and Anthropic **Skills** APIs from Postman.

> **Tip:** In Postman, use **Import → Raw text** and paste any of the `curl` blocks below — Postman will reconstruct the
> full request (headers, body, form-data) automatically.

## Resources

- **Postman collection:** [Skills webinar.postman_collection.json](/api_demo/_postman/Skills%20webinar.postman_collection.json) —
  import this directly into Postman to get all requests pre-configured.
- **Calculator skill ZIP:** [calculator.zip](/api_demo/_postman/calculator.zip) — the example skill bundle used in every upload request
  below.

## Environment variables

Configure these in a Postman **Environment**:

| Variable             | How to obtain                                                                                                   |
|----------------------|-----------------------------------------------------------------------------------------------------------------|
| `OPENAI_API_KEY`     | Your OpenAI API key (`sk-proj-...`).                                                                            |
| `ANTHROPIC_API_KEY`  | Your Anthropic API key (`sk-ant-...`).                                                                          |

References:

- OpenAI Skills guide — https://developers.openai.com/api/docs/guides/tools-skills
- Anthropic Skills guide — https://platform.claude.com/docs/en/build-with-claude/skills-guide

---

# OpenAI — Skills + Responses API

OpenAI uploads a single **ZIP archive** of the skill directory, then references the resulting `skill_id` from a
`container_auto` environment on every `responses.create` call. Multi-turn chat is preserved via `previous_response_id`.

## 1. List skills (initial check)

```bash
curl --location "https://api.openai.com/v1/skills" \
  --header "Authorization: Bearer {{OPENAI_API_KEY}}"
```

## 2. Upload (create) a skill

```bash
curl --location "https://api.openai.com/v1/skills" \
  --header "Authorization: Bearer {{OPENAI_API_KEY}}" \
  --form "files=@calculator.zip;type=application/zip"
```

The response contains `id` (e.g. `skill_abc123`) — copy it into the **`OPENAI_SKILL_ID`** environment variable.

## 3. Send the first user turn (no previous_response_id)

```bash
curl --location "https://api.openai.com/v1/responses" \
  --header "Authorization: Bearer {{OPENAI_API_KEY}}" \
  --header "Content-Type: application/json" \
  --data '{
    "model": "gpt-5.2",
    "input": [
      {
        "role": "user",
        "content": "What is 2^10 + sqrt(144)?"
      }
    ],
    "tools": [
      {
        "type": "shell",
        "environment": {
          "type": "container_auto",
          "skills": [
            { "type": "skill_reference", "skill_id": "{{OPENAI_SKILL_ID}}" }
          ]
        }
      }
    ]
  }'
```

Save the returned `id` (e.g. `resp_01H...`) as **`<OPENAI_PREV_RESPONSE_ID>`** — it is the chain pointer for the next
turn (the container is reused server-side, so state is preserved).

## 4. Continue the chat (subsequent turns)

```bash
curl --location "https://api.openai.com/v1/responses" \
  --header "Authorization: Bearer {{OPENAI_API_KEY}}" \
  --header "Content-Type: application/json" \
  --data '{
    "model": "gpt-5.2",
    "previous_response_id": "<OPENAI_PREV_RESPONSE_ID>",
    "input": [
      {
        "role": "user",
        "content": "Now compute sin(pi / 2) + cos(0)."
      }
    ],
    "tools": [
      {
        "type": "shell",
        "environment": {
          "type": "container_auto",
          "skills": [
            { "type": "skill_reference", "skill_id": "{{OPENAI_SKILL_ID}}" }
          ]
        }
      }
    ]
  }'
```

Update `<OPENAI_PREV_RESPONSE_ID>` after each turn (its value is the new `response.id`).

## 5. List all available skills (verify before delete)

Same endpoint as step 1 — run it again to confirm your uploaded skill is in the list and to grab any ID you need to
delete.

```bash
curl --location "https://api.openai.com/v1/skills" \
  --header "Authorization: Bearer {{OPENAI_API_KEY}}"
```

The response shape is:

```json
{
  "object": "list",
  "data": [
    {
      "id": "skill_abc123",
      "name": "calculator",
      "object": "skill",
      "created_at": 1731000000
    }
  ]
}
```

Pick the `id` of the skill to remove and use it in step 6.

## 6. Delete a skill

```bash
curl --location --request DELETE "https://api.openai.com/v1/skills/{{OPENAI_SKILL_ID}}" \
  --header "Authorization: Bearer {{OPENAI_API_KEY}}"
```

---

# Anthropic — Skills (beta) + Messages API

Anthropic uploads a **single ZIP archive** of the skill via multipart form-data. The skill ID stays stable across edits;
each upload creates a new **version**, and the message API references `"version": "latest"` (or a fixed version number).
Multi-turn state is preserved by reusing `container.id`.

This section uses the **calculator** skill end-to-end.

All skill endpoints require:

```
x-api-key: {{ANTHROPIC_API_KEY}}
anthropic-version: 2023-06-01
anthropic-beta: skills-2025-10-02
```

The `messages` call additionally requires `anthropic-beta: code-execution-2025-08-25,skills-2025-10-02`.

## 1. List custom skills

```bash
curl --location "https://api.anthropic.com/v1/skills?source=custom" \
  --header "x-api-key: {{ANTHROPIC_API_KEY}}" \
  --header "anthropic-version: 2023-06-01" \
  --header "anthropic-beta: skills-2025-10-02"
```

Find the entry whose `display_title` matches `calculator` and use its `id` as the **`ANTHROPIC_SKILL_ID`** environment
variable.

## 2. Upload (create) the calculator skill from ZIP

Single `files[]` form field pointing at the calculator zip.

```bash
curl --location "https://api.anthropic.com/v1/skills" \
  --header "x-api-key: {{ANTHROPIC_API_KEY}}" \
  --header "anthropic-version: 2023-06-01" \
  --header "anthropic-beta: skills-2025-10-02" \
  --form "display_title=calculator" \
  --form "files[]=@calculator.zip;type=application/zip"
```

Copy the returned `id` into the **`ANTHROPIC_SKILL_ID`** environment variable and `latest_version` as
**`<ANTHROPIC_SKILL_VERSION>`** (defaults to `1`).

## 3. Send the first user turn (no container id yet)

```bash
curl --location "https://api.anthropic.com/v1/messages" \
  --header "x-api-key: {{ANTHROPIC_API_KEY}}" \
  --header "anthropic-version: 2023-06-01" \
  --header "anthropic-beta: code-execution-2025-08-25,skills-2025-10-02" \
  --header "Content-Type: application/json" \
  --data '{
    "model": "claude-sonnet-4-6",
    "max_tokens": 4096,
    "messages": [
      {
        "role": "user",
        "content": "What is 2^10 + sqrt(144)?"
      }
    ],
    "container": {
      "skills": [
        {
          "type": "custom",
          "skill_id": "{{ANTHROPIC_SKILL_ID}}",
          "version": "latest"
        }
      ]
    },
    "tools": [
      { "type": "code_execution_20250825", "name": "code_execution" }
    ]
  }'
```

In the response, save `container.id` as **`<ANTHROPIC_CONTAINER_ID>`**, and capture the assistant's `content` blocks so
you can echo them back on the next turn.

## 4. Continue the chat (reuse container + full message history)

```bash
curl --location "https://api.anthropic.com/v1/messages" \
  --header "x-api-key: {{ANTHROPIC_API_KEY}}" \
  --header "anthropic-version: 2023-06-01" \
  --header "anthropic-beta: code-execution-2025-08-25,skills-2025-10-02" \
  --header "Content-Type: application/json" \
  --data '{
    "model": "claude-sonnet-4-6",
    "max_tokens": 4096,
    "messages": [
      { "role": "user", "content": "What is 2^10 + sqrt(144)?" },
      { "role": "assistant", "content": [ { "type": "text", "text": "<previous reply>" } ] },
      { "role": "user", "content": "Now compute (144 * 3) + sqrt(256) - 2^8." }
    ],
    "container": {
      "id": "{{ANTHROPIC_CONTAINER_ID}}",
      "skills": [
        {
          "type": "custom",
          "skill_id": "{{ANTHROPIC_SKILL_ID}}",
          "version": "latest"
        }
      ]
    },
    "tools": [
      { "type": "code_execution_20250825", "name": "code_execution" }
    ]
  }'
```

> **Note:** unlike OpenAI's `previous_response_id` shortcut, Anthropic requires you to resend the whole `messages[]`
> array each turn. The container id only carries the **execution environment** (loaded files, kernel state), not the
> chat history.

## 5. List versions of the skill

```bash
curl --location "https://api.anthropic.com/v1/skills/{{ANTHROPIC_SKILL_ID}}/versions" \
  --header "x-api-key: {{ANTHROPIC_API_KEY}}" \
  --header "anthropic-version: 2023-06-01" \
  --header "anthropic-beta: skills-2025-10-02"
```

## 6. Delete a specific version

```bash
curl --location --request DELETE \
  "https://api.anthropic.com/v1/skills/{{ANTHROPIC_SKILL_ID}}/versions/<ANTHROPIC_SKILL_VERSION>" \
  --header "x-api-key: {{ANTHROPIC_API_KEY}}" \
  --header "anthropic-version: 2023-06-01" \
  --header "anthropic-beta: skills-2025-10-02"
```

## 7. Delete the skill itself (after deleting every version)

```bash
curl --location --request DELETE "https://api.anthropic.com/v1/skills/{{ANTHROPIC_SKILL_ID}}" \
  --header "x-api-key: {{ANTHROPIC_API_KEY}}" \
  --header "anthropic-version: 2023-06-01" \
  --header "anthropic-beta: skills-2025-10-02"
```

> Deletion order matters: list versions → delete each version → delete the skill.
