# Security policy

## Supported versions

Security fixes follow the [support policy](CONTRIBUTING.md#support-policy):
fixes land only in the newest release, without backports. Upgrade to the newest
release before checking whether a suspected vulnerability still applies.
The support policy also defines the upgrade window and unsupported installations.

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/biagiolibe/meridian/security/advisories/new)
to report suspected vulnerabilities privately to the maintainers. Do not open a
public issue or pull request with exploit details.

Include, when available:

- The Meridian version (`meridian --version`) and installation method.
- The workflow mode, agent host, operating system, and relevant configuration.
- Affected commands, hooks, files, and versions.
- Reproduction steps or a minimal proof of concept, expected and actual behavior,
  and the potential impact (such as unintended Git operations or code execution).
- Relevant logs, including any exact `BLOCKED` line, with credentials, tokens,
  personal information, and private project content removed.
- Any mitigation or proposed fix, and your preference for public credit.

Maintainers aim to acknowledge a report within seven calendar days, assess its
impact, and agree on next steps through the private report. This is a response
target, not a guaranteed resolution deadline. Updates and coordinated disclosure
timing depend on reproducibility and severity; keep details private until a fix
or disclosure plan is agreed.

For ordinary bugs and feature requests, use the repository's issue templates.
Community conduct reports use the same private channel as described in the
[code of conduct](CODE_OF_CONDUCT.md).
