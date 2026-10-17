# Changelog fragments

Each task with a user-visible change adds exactly one file named
`<TASK-ID>.md`, for example `116.md`. A task without a user-visible change adds
no fragment. This README is metadata and is never rendered as a fragment.

Fragments contain only `###` subsections from this fixed list: `Added`,
`Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`, `Documentation`, and
`Upgrade notes`. Every subsection has one or more Markdown bullets; an indented
line may continue its preceding bullet. Do not add prose before, between, or
after subsections, and do not repeat a subsection heading.

At release time `python3 scripts/release.py prepare` renders fragments in task
file-name order, groups their bullets by the fixed heading order, and consumes
the fragment files in the release commit. During the transition it also accepts
an existing non-empty `CHANGELOG.md` `[Unreleased]` body and renders that first.
