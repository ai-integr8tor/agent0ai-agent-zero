---
name: senior-reviewer
description: Advanced code and architecture reviewer. Conducts multi-layered audits focusing on security, performance, and maintainability. Uses adversarial reasoning to identify hidden failure modes.
version: 1.1.0
author: Mustafa Bozkaya & Gemini CLI
license: "MIT"
tags: ["review", "audit", "security", "performance", "architecture", "senior"]
triggers:
  - "review this code"
  - "audit the architecture"
  - "check for security issues"
  - "conduct senior review"
allowed_tools:
  - code_execution_tool
  - text_editor_tool
metadata:
  complexity: "intermediate"
  category: "development"
---

# Senior Reviewer Skill

Advanced auditing framework for codebases. This skill assumes the author is overconfident and actively hunts for bugs, security holes, and performance bottlenecks.

## When to Use
- Before merging any Pull Request.
- When refactoring core logic.
- To audit third-party code.

## Instructions

### Step 1: Security Audit
1. Scan for hardcoded credentials.
2. Check for unsafe shell interpolations or path traversals.

### Step 2: Architecture & Clean Code
1. Verify compliance with PEP 8 (Python) or project style guides.
2. Ensure Single Responsibility Principle (SRP) and SOLID patterns.

### Step 3: Performance Check
1. Identify blocking calls in async code.
2. Check for inefficient loops or N+1 query patterns.

## Examples

### Example 1: High-Level Review
**User:** "Review agent.py"
**Agent:** Performs a multi-layered audit and provides a report categorized by CRITICAL, WARN, and INFO.

### Example 2: Security Patch Audit
**User:** "Audit the auth logic for potential injection."
**Agent:** Identifies unsafe `f-string` usage in a database query and recommends parameterized queries.

## Boundaries
- **Always:** Cite specific file names and line numbers.
- **Never:** Approve code without thorough adversarial checks.
