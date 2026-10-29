# Release and adoption

Publisher: [raven-ai-esh](https://github.com/raven-ai-esh). Repository:
[raven-ai-esh/arv](https://github.com/raven-ai-esh/arv). Licence: MIT.

## Release checks

The CI matrix covers Windows, macOS and Linux. Each job creates a fresh archive,
installs its dependencies into an empty cache, executes the scripted demonstration
and full tests, then installs the package in native Codex and checks real MCP and
SQLite effects. See [verification scope](verification.md) and the actual Actions
results before claiming support for a particular host mode.

After publishing a version, verify anonymous source/archive download and Git
marketplace installation. Package version changes belong in both manifests,
pyproject.toml and the lock file. The release builder reads the manifest version
and writes a ZIP with per-file and archive checksums.

## First users

The initial audience is developers of research agents and analysts working with
incomplete records and observations. Start with people who can install the tool,
complete one task and explain where it helped or added friction.

Use the bundled synthetic case to demonstrate new grounds reinforcing a hypothesis,
copies adding no independent weight, and a counterfact changing a conclusion.
Label scripted calls separately from autonomous agent work.

Before claiming improvement, compare a plain agent and ARV using the same model,
source corpus and task. Assess unsupported conclusions, preserved contradictions,
source traceability, useful outcomes, time and token cost. Report neutral or worse
results too. No comparative advantage is established by this release.

## Further distribution

- An MCP Registry listing needs separate server-package work.
- OpenAI public-directory local MCP submissions require an approved partner and
  an allowlisted organisation. Eligibility is unverified.
  [Official guide](https://developers.openai.com/plugins/deploy/desktop-only).
- Consider Show HN once people can try the package. The maker should write the
  post and participate personally; follow the
  [guidelines and linked posting tips](https://news.ycombinator.com/showhn.html).

Publishing the repository does not send invitations or post announcements.
