# Message Loop Prompts After Extensions DOX

## Purpose

- Own prompt protocol and extras appended around primary message-loop prompt construction.

## Ownership

- Ordered Python files own current datetime, skill recall/load context, agent info, parallel job status, and workdir extras injection.
- Loaded and active skill instructions belong in prompt protocol, not prompt extras.

## Local Contracts

- Keep injected content bounded and clearly attributed.
- Preserve ordering where later prompt extras depend on earlier recall or load results.
- Do not expose secrets or private files from workdir extras.

## Work Guidance

- Coordinate prompt protocol and prompt-extra changes with skill, workdir, and profile contracts.

## Verification

- Inspect rendered prompt protocol/extras or run prompt-construction tests after changes.

## Child DOX Index

No child DOX files.
