# System Prompt Extensions DOX

## Purpose

- Own construction of core system prompt sections.

## Ownership

- Ordered Python files own main, small-local-model, tools, MCP, secrets, skills, and project prompt sections.

## Local Contracts

- Preserve ordering where sections depend on earlier context.
- Keep secret-related prompt sections masked and scoped.
- Prompt additions must be bounded and compatible with tool-call contracts.

## Work Guidance

- Coordinate broad system prompt changes with profiles, skills, tools, plugins, and prompt tests.

## Verification

- Inspect rendered system prompts or run prompt-construction tests after changes.

## Child DOX Index

No child DOX files.
