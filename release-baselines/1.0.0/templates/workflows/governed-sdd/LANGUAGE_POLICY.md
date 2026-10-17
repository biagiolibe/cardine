# Language Policy

## Persistent conversation language

**Conversation language:** `[Conversation language]`

Use this language for every message to the developer. Do not infer or change it from the language of an individual prompt: a prompt written in another language is not a request to switch languages.

Change this setting only when the developer explicitly asks to change the conversation language. Update the value above in the same change so the preference persists across sessions and agents.

## Repository language — mandatory

All text that remains in the repository must be written in English. This is a non-negotiable project invariant, regardless of the conversation language.

This includes documentation, source code, comments, identifiers, user-facing strings, test names and fixtures, task records, issue templates, commit messages, configuration values, and generated text that is committed to version control.

Before writing or editing a persistent artifact, translate its text to English. A developer prompt in another language never relaxes this rule. If the requested work requires non-English text to be committed, stop and obtain an explicit amendment to this policy before writing it.
