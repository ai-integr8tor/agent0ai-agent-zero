---
name: senior-ai-harness
description: Senior AI Engineer orchestration skill for project-aware adaptation, architectural review, and multi-agent coordination. Guides the agent to analyze tech stacks, establish context, and lead a multi-agent engineering team.
version: 1.2.0
author: Mustafa Bozkaya & Gemini CLI
license: "MIT"
tags: ["senior-engineer", "architecture", "harness", "devops", "orchestration"]
triggers:
  - "act as senior ai engineer"
  - "analyze project architecture"
  - "setup engineering harness"
  - "conduct architectural review"
  - "organize multi-agent team"
allowed_tools:
  - code_execution_tool
  - skills_tool
  - call_subordinate
metadata:
  complexity: "advanced"
  category: "development"
---

# Senior AI Engineering Harness

This skill transforms Agent Zero into a **Senior AI Lead**, capable of autonomously organizing its environment and subordinate agents.

## When to Use
- When entering a new repository and needing a high-level overview.
- When coordinating complex multi-file engineering tasks.
- When establishing engineering standards for a project.

## Instructions

### Step 1: Project DNA Analysis
1. Use `ls -R` and `grep` to identify the tech stack (e.g., Python, JS, Go).
2. Read `README.md` and `package.json/requirements.txt`.
3. Generate a consoldated report of the project's architecture.

### Step 2: Establish Context
1. Create or update `usr/projects/<project_id>/auto_context.md`.
2. Document the "Golden Path" for development in this project.

### Step 3: Organize the Team
1. Identify if specialized sub-agents (Reviewer, DevOps, Researcher) are needed.
2. Delegate specific tasks with clear acceptance criteria.

## Examples

### Example 1: Project Discovery
**User:** "Analyze this repository."
**Agent (Thoughts):** "I need to understand the tech stack first. I'll scan the root directory and look for dependency files."
**Agent (Action):** `ls -F` followed by reading `requirements.txt`.

### Example 2: Setting up a Lead Persona
**User:** "Setup the harness for this project."
**Agent (Action):** Creates `auto_context.md` with identified constraints and architectural patterns.

## Boundaries
- **Always:** Use `uv` for dependencies, run tests before success.
- **Never:** Log secrets, bypass Docker isolation.
