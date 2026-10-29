---
name: assumption-research-verification
description: Reconstruct the most plausible working picture from incomplete data by accumulating observations, semantically matching hypotheses, and revising their support. Use for understanding entities, relationships, processes and their results; preserve observations, task conventions and alternative explanations in a persistent MCP graph.
---

# Assumption–Research–Verification

Build a coherent, useful **working model** of the subject. Read data, infer plausible
entities and relations, collect new grounds, revisit competing explanations, then
select the picture that best accounts for the observations. Verification here is
the accumulation and comparison of meaningful grounds; it is not a demand for
documentary proof of every ordinary inference.

## Research loop

Identify the question, subject/domain, period and authorized sources. Start with
`arv_begin`; no fixed check budget unless the user requested one. The graph does
not grant source access. Use authorized source tools or files to read the data.

- Record observations with `arv_observe`: actual source identity, locator, scope,
  date and passage. Preserve identity across copies. Your own summary is derived
  from its observations and is not a second independent fact.
- Infer useful hypotheses from observations and ordinary knowledge of the domain.
  Matching recordings can suggest a shared event or instrument effect. A separate
  document proving every ordinary inference is not required to adopt a plausible
  working picture. Do not invent specific identities, measurements or dates.
- Use `arv_model` or a focused `arv_inspect` to find existing claims. Reuse hypotheses
  **by meaning**, using `same_as` with their IDs for equivalent wording. If duplicate
  claims already exist, compare their meanings and use `arv_merge`; keep distinct
  claims separate when their subjects or relations genuinely differ.
- Call `arv_hypothesize` with the new observation IDs in `based_on`. This adds support
  and recomputes plausibility. Explain why those observations are diagnostic and
  choose `weak`, `moderate` or `strong` relevance. More names or more files do not
  automatically mean more independent observations.
- New facts may strengthen, narrow or contradict a hypothesis. Use `arv_assess`
  with `support` or `oppose` and a reason. Different observations can have different
  relevance. `withdraw` retires a no-longer-applicable interpretation with a reason;
  the previous assessment remains in history. Re-read current revisions on conflict.
  If a supporting premise loses support, revisit its dependent inference. Do not
  silently discard a necessary premise merely to keep a desired conclusion.
- Select subsequent reading by how it can improve the working picture or resolve
  a meaningful disagreement. `arv_check` is available for targeted inquiries; there
  is no mandatory contract or preregistration step for every observation. Preserve
  access errors, unavailable data and empty searches as their actual outcomes.

For example, recordings from separate instruments may support one shared-event
hypothesis. New diagnostic observations can reinforce it. A copied recording or
a retelling of the same observation adds no new root. Shared hardware can make
apparently separate readings dependent; judge that relationship semantically.

## Task conventions and reasonable defaults

Use `arv_assume(kind="user_rule")` for interpretations the user or domain owner has
adopted. Use `domain_prior` for ordinary structural defaults. Link these assumptions
to the hypotheses that use them. Assumptions remain distinguishable from observations
inside the research trail; they can still enter the selected working model.

If the task adopts “raw U values are interpreted as centimetres”, apply
that rule and retain it as a convention. Missing extra paperwork is not a
counterfact. A later calibration record defining another scale can change the
interpretation. Keep the convention and its origin inspectable.

Do not turn a domain-specific example into a universal convention for all tasks.
Do not fabricate measurements, exact parameters, identities or dates. Ordinary
residual details need not become prominent caveats or block the working picture.

## Synthesis

Use `arv_model` to inspect relative support, counterfacts, defaults and a suggested
coherent selection. Relevance weights are ordinal bookkeeping, not calibrated
probabilities. Multiple related defaults do not accumulate as independent facts.
Shared original observations count once through alternative derivation paths.

The agent judges semantic fit and how the entities and relations work together.
Compare meaningful rivals; do not manufacture implausible alternatives only to
reject them. A tie is a reason to make an explicit reasoned choice or retain a
specific unresolved relation, not to suspend the whole investigation.

Call `arv_finish` with the coherent summary and selected claims, or use its suggested
selection. Include useful remaining questions. The result is a working model:
observed and inferred entities, their properties and relationships, normal processes,
results, important mechanisms, risks and opportunities. Keep the graph and source
basis inspectable. No unrelated-dataset holdout or independent certificate
is required merely to accept a reasonable working inference.

Stop when the model is adequate for the user's question and further available
reading is unlikely to materially change that answer. Do not substitute a fixed
number of hypotheses, checks, repeated rounds or minutes for this judgment.
Complete or cancel targeted checks you have actually left pending. New material
graph data reopens the stored conclusion; previous conclusions remain in history.

## Review and historical research

A reviewer evaluates plausibility, coherence, meaningful corroboration, user rules
and actual contradictions. Missing documentary confirmation of an ordinary accepted
inference is not itself a defect. Read [review guidance](references/working-review.md)
when reviewing. Optional `arv_review` records attributed feedback without converting
review into the definition of ARV or a mandatory stopping certificate.

Research created under the former validation protocol retains that protocol and
its history. When explicitly resuming such a bound research, the server exposes its
historical tools and [historical method](references/legacy-validation.md). New default
research uses the working-model loop above; do not silently migrate an old certificate.
