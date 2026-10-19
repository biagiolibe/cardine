# Technical Design Document — [Project Name]

This document describes the project technical architecture and implementation choices.

## 1. Technology Stack

- **Language/Runtime**: [e.g. TypeScript / Python / Rust]
- **Primary framework**: [e.g. Express / FastAPI / none]
- **Database**: [e.g. PostgreSQL / SQLite / none]
- **Key libraries**: [list the primary dependencies]
- **Testing**: [e.g. Jest / pytest / cargo test]

---

## 2. Project Structure

```
src/
  [describe the directory structure]
```

---

## 3. Architecture & Patterns

### General approach
[Describe the architecture pattern: MVC, Clean Architecture, separate modules, etc.]

### Module structure
Every module must be self-contained and expose well-defined interfaces.

- `module-a`: [responsibility]
- `module-b`: [responsibility]

---

## 4. Development Conventions

### Naming
- File: [kebab-case / snake_case / PascalCase]
- Funzioni: [camelCase / snake_case]
- Costanti: [SCREAMING_SNAKE_CASE]

### Error handling
[Describe how errors are handled: exceptions, Result types, error codes, etc.]

### Testing
[Test strategy: unit, integration, e2e. Where tests belong.]

---

## 5. Architecture Decisions

### [Decision A]
**Context**: [Why a choice was necessary]
**Decision**: [What was chosen]
**Rationale**: [Why this choice]

---

*Last reviewed: [Date]*
