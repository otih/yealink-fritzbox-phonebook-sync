# Code of Conduct for AI-Assisted Development

This project is developed with AI assistance and expects contributions from
both humans and AI agents. This code of conduct applies to **both**.
If an AI agent contributes to this project, the human operating the agent
remains responsible for ensuring the agent's output complies with these
rules.

## 1. Honesty about provenance

- Do not present AI-generated code as purely human work, and do not present
  human work as if it needed no review because "the AI wrote it".
- AI agents must not fabricate test results, benchmark numbers, library
  APIs, or documentation of code that does not exist. If the agent has not
  verified something, it must say so.

## 2. Verify before claiming

- "It works" is a claim that requires evidence: a passing test, a build
  log, a runtime observation. AI agents must not claim success based on
  plausible-looking output alone.
- Never commit code that has not been executed at least once in an
  environment matching the project's (here: the container build plus the
  unit test suite at minimum).

## 3. Security is not optional

- Every commit from humans and AI agents alike must pass the project's
  security scan (`ruff --select S,B` on production code).
- Every exception to a security finding must be documented with its
  rationale at the code site. An AI agent must never silence a finding
  with a bare `noqa` or downgrade a severity without a stated reason.
- Secrets, credentials, and personal data must never be committed —
  including "temporary" test credentials.

## 4. Trust and boundaries

- For this project the maintainer has granted the AI agent release
  authority: the agent may merge, publish releases, and push tags on its
  own when the CI gates are green and the release rules below are met.
- This authority is project-specific and does not transfer to other
  projects. The agent must still surface every release decision in the
  conversation so the human can intervene.
- Releases must follow the project's versioning concept (see
  CONTRIBUTING.md); an agent that is unsure which version number applies
  asks instead of guessing.

## 5. Respect the project's rules

- AI agents must follow the same conventions as human contributors:
  changelog discipline (entry in the same commit as the change),
  backwards compatibility, TDD for new features, conventional commits.
- An agent that is unsure about a project rule must ask instead of
  improvising.

## 6. Interaction style

- Be precise and honest in issues and PRs, human or AI. No fabricated
  politeness, no invented facts, no blaming tools for one's own mistakes.
- Disagreement is fine; misrepresentation is not.

## Enforcement

Violations are handled by the maintainer. For AI-assisted contributions,
repeated violations may result in asking the operator to stop using an
agent for this project.
