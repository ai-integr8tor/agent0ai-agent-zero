---
name: uv-manager
description: High-performance Python package management using 'uv'. Handles environment setup, dependency resolution, and tool management with extreme speed. Replacement for traditional pip-based workflows.
version: 1.1.0
author: Mustafa Bozkaya & Gemini CLI
license: "MIT"
tags: ["uv", "python", "dependencies", "pip", "performance", "devops"]
triggers:
  - "install python packages"
  - "manage virtual environments"
  - "setup uv"
  - "use uv for dependencies"
allowed_tools:
  - code_execution_tool
metadata:
  complexity: "intermediate"
  category: "devops"
---

# UV Package Manager

This skill optimizes Python dependency management using **uv**, ensuring fast, isolated, and reproducible environments.

## When to Use
- When setting up a new project or virtual environment.
- To install or sync Python dependencies faster than `pip`.
- To manage project-specific toolchains.

## Instructions

### Step 1: Environment Setup
- Create venv: `uv venv`
- Activate (Linux/Mac): `source .venv/bin/activate`
- Activate (Windows): `.venv\Scripts\activate`

### Step 2: Dependency Installation
- Install from file: `uv pip install -r requirements.txt`
- Install package: `uv pip install <package_name>`
- Sync environment: `uv pip sync requirements.txt`

## Examples

### Example 1: Installing a New Tool
**User:** "Install flask using uv."
**Agent (Action):** `uv pip install flask`

### Example 2: Synchronizing Repos
**User:** "Setup the development environment for this repo."
**Agent (Action):** `uv venv && source .venv/bin/activate && uv pip install -r requirements.txt`

## Boundaries
- **Always:** Verify `uv` installation with `which uv`.
- **Never:** Use `--break-system-packages` on host machines unless explicitly commanded.
