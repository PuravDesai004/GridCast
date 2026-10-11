# Volume 3: Brain (Parts 6 to 11)

Goal: explain the thinking part of the project, what each smart-sounding piece really is, why each technology and decision was chosen, and show the logic running on a small example.

## Part 6: Core logic

Identify the "brain": the logic that makes the project worth building. It might be an algorithm, an ML model, a statistical test, a scoring formula, a ranking system, an NLP or RAG pipeline, an optimization model, a transformation pipeline, business rules or a decision engine. Say which one it is and where it lives in the code.

Work through it in this order:

1. What problem it solves and why it is needed
2. Inputs and outputs
3. How it works conceptually (simple idea first)
4. How it works technically, tied to the actual code path
5. The algorithm, model or formula used, and every important variable
6. A short walkthrough (Part 10 is the full worked example)
7. How to read and interpret the output
8. Edge cases
9. Limitations

For any formula, write it out, define every variable, say where each value comes from in the code or data, say why this formula was used, and say how the result changes what the system does next. Then substitute small numbers and calculate.

If statistics are involved, explain only the concepts the project actually uses, chosen from: population and sample, control and treatment, baseline, metric, mean and median, variance, null and alternative hypothesis, p-value, confidence interval, significance level, statistical versus practical significance, effect size, power, sample size, false positives and false negatives. Skip the rest.

If the project has no real brain (a plain CRUD app, say), say so and treat the business rules and data model as the core logic. Do not manufacture an algorithm.

## Part 7: What is AI, ML, NLP or statistics, and what is not

Decide, component by component, which category each smart-sounding part belongs to. Use these meanings, because the boundaries are where examiners probe:

- Deterministic code: fixed rules, the same input always gives the same output, nothing is learned.
- Classic algorithm: a defined procedure (sorting, search, graph traversal, linear programming), not learned from data.
- Statistics: inference from samples (tests, intervals, regression used for inference).
- Machine learning: parameters learned from data (fit or train), including classical models such as trees, linear models and clustering.
- Deep learning: multi-layer neural networks trained by gradient descent.
- NLP: processing language, which may be rule-based, statistical, ML or LLM-based. Say which.
- Embeddings: vectors produced by a learned model. The similarity math applied to them (cosine similarity, say) is plain linear algebra, but inside a semantic search pipeline it becomes part of that pipeline's matching logic.
- Generative AI or LLM use: a pretrained model generates text. Say whether the project trains, fine-tunes, or only calls a hosted or local model.
- RAG: a retriever (embeddings plus vector search) feeding context to a generator (an LLM). Say which halves are implemented.
- Agents and multi-agent systems: LLM calls orchestrated by code, with tools and state. Say what the orchestrating code decides and what the LLM decides.

Present a table:

| Component | Category | Why it belongs there | What it does in this project | What it does NOT do |
|---|---|---|---|---|

The last column prevents overclaiming. Typical entries: "does not train a model, calls an API", "output is checked against a schema but not for factual accuracy", "similarity is computed in code, not by the model".

## Part 8: Technology stack

Build one table from what the project actually uses, confirmed in manifests and imports, not from what such projects usually use:

| Technology | What it is | Role in this project | Why it is used | Important viva point |
|---|---|---|---|---|

Group rows under the categories that apply: frontend, backend, database, AI/ML, NLP, statistics, APIs, storage, testing, visualization, infrastructure, deployment.

Answer "why THIS technology?" and not only "what is this technology?". Take the reason from the material when it is there. When it is not, give the plausible general reasoning, label it as such, and tell the user to replace it with their real reason, since they were there when the choice was made.

## Part 9: Design decisions

This part carries the most weight in a viva. List every major architectural decision and give each one this block:

```
DECISION:     what was chosen
REASON:       why (stated in the material / inferred from the code / general reasoning: say which)
ALTERNATIVE:  what could have been used instead
WHY NOT:      why the alternative was passed over (from the material, or labelled general reasoning)
TRADE-OFF:    what the project gained and what it gave up
```

Decisions worth checking for: database choice, REST versus another style, the ML model, the statistical test, the embedding model, a threshold, chunk size, a scoring formula, local versus remote storage, a vector database, the overall architecture.

When the material does not give the reason, do not present a guess as fact. Offer the likely reasons, labelled, and ask the user which one was actually theirs. An examiner wants the real reason, and "I picked it because X, and the cost was Y" is a stronger answer than any reason supplied by a tutor.

## Part 10: Small worked example

Run a miniature, realistic example through the project's actual logic: INPUT, then STEP 1, STEP 2, STEP 3 and so on, to FINAL OUTPUT. Use small numbers, show every calculation, and finish by saying what the result means inside the project.

Use real sample data from the material when there is some (a test fixture, a sample row, a documented example). When you must invent inputs, label them "illustrative values" and keep the logic exactly the project's. If the logic is not numeric (a CRUD flow, say), follow one record through the code instead. Do not swap in a convenient textbook example, because it proves nothing about this project.

## Part 11: Data

Explain the data the system touches: input data, stored data, intermediate data, output data, metadata, schemas, important fields, transformations, validation and formats. Use the flow that fits the project and skip the others:

```
DATABASE → TABLE / COLLECTION → FIELDS → RELATIONSHIPS → HOW THE APPLICATION USES THEM
DOCUMENT → CHUNK → EMBEDDING → VECTOR STORAGE → RETRIEVAL
USER → GROUP ASSIGNMENT → EVENTS → METRIC → AGGREGATION → STATISTICAL TEST → DECISION
RAW SOURCE → STAGING → TRANSFORMATION → SERVING TABLE → DASHBOARD
```

Describe only what the material shows: the schema from the model definitions or SQL, the columns from the file headers. Do not state distributions, class balance or row counts you have not computed. If you need such a figure and have a code tool, compute it and say that you did.
