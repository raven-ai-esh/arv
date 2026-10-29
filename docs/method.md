# Method and limits

ARV builds a useful working model from incomplete data. An observation can suggest
an entity or relation. Further independent grounds may reinforce the hypothesis;
an actual counterfact may weaken it. The agent chooses the next useful reading
and ultimately selects a coherent picture with its remaining questions.

The full instructions are in the packaged
[skill](../skills/assumption-research-verification/SKILL.md).

## Responsibilities

| Agent | MCP server |
| --- | --- |
| Reads authorised sources | Stores supplied passages and provenance |
| Judges semantic relevance and source independence | Counts distinct recorded roots and combines ordinal relevance |
| Recognises equivalent meanings and competing explanations | Reuses or merges claims when instructed |
| Chooses an explanation and explains uncertainty | Checks declared conflicts and required premises |

A source identity is an input supplied by the agent. ARV cannot discover that two
apparently distinct records secretly derive from the same source. Equivalence and
independence still need judgement.

## Assumptions

User conventions and ordinary domain defaults are explicit nodes. They may support
a working model without a separate document proving each ordinary inference.
They remain distinguishable from observed facts. The quickstart’s unit convention
belongs only to that synthetic exercise and is not a default for other tasks.

## Verification

Support, opposition and relevance tiers help maintain the model. They are not
calibrated probabilities, and a model that passes consistency checks can still
contain a mistaken inference or an inaccurate source.

ARV has no established general benchmark advantage over a plain agent. The bundled
demo proves specified software behaviour through MCP and persistence. It does not
measure autonomous reasoning quality, user usefulness, model cost or latency.

## Completion and history

`arv_finish` stores a working model and open questions. New material graph data
reopens the result. An optional reviewer can inspect the same graph and record
attributed feedback. A reviewer certificate is not mandatory for a new working model.

Older investigations retain their historical validation protocol. They are not
silently converted; their method is described in the packaged
[historical reference](../skills/assumption-research-verification/references/legacy-validation.md).
