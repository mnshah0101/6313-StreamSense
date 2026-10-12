# Specification index

These specifications describe the planned application and its relationship to existing research.
They are a source-based draft for team review, not a claim that every design has client approval.

| Document | Developer question answered |
| --- | --- |
| [Sources and requirements](sources.md) | What evidence supports the requirements? |
| [Architecture](architecture.md) | Which component owns each responsibility? |
| [Data model](data-model.md) | What is stored and what must remain consistent? |
| [API and interfaces](api.md) | How do components exchange requests and results? |
| [Security and privacy](security.md) | Who may access data, and how is it protected? |
| [ML integration](ml-integration.md) | How does research become validated application output? |
| [UI specification](design/ui-spec.md) | What screens, states, and constraints are required? |
| [User flows](design/user-flows.md) | What happens during each user task and failure? |
| [Decision register](decisions.md) | What is settled, provisional, or blocking? |
| [Development guide](development.md) | How do I install, run, and verify the scaffold? |

The scope is upload-based image-quality analysis and a course demonstration that can simulate
multiple streams from videos. Research code exists separately. This repository currently
implements only the development scaffold listed in the verification record.
