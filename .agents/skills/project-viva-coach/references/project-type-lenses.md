# Project-type lenses

Read this after the inventory to decide where to look hardest. Most projects mix several types, so apply every lens that fits. These notes are general knowledge about such projects. Use them to decide what to check, and report only what the project's own material shows.

## Contents

- Web app or REST API
- Classical ML pipeline
- Deep learning model
- LLM, RAG and agent systems
- Data pipelines and analytics
- Statistics and experimentation
- Optimization
- Recommendation, search and ranking
- Computer vision
- Mobile, desktop, embedded and games
- Other inputs: notebooks, datasets, screenshots, diagrams, reports, slides

## Web app or REST API

The brain is usually the business rules and the data model. Many web projects have no algorithm, and that is fine.

Trace: client → route → validation → auth check → service or business logic → ORM or query → database → serializer → response → render.

Check where validation happens (on the server, not only in the form), how authentication differs from authorization, how sessions or tokens work, how secrets and config are loaded, and how the app is deployed.

Traps: SQL injection and ORM use, password hashing, CORS, what happens on a duplicate or missing record, pagination.

## Classical ML pipeline

The brain is features plus model plus evaluation.

Trace: raw data → cleaning → feature engineering → split → training → evaluation → saved model → inference path.

Check how the split was done (random or time-based), whether any preprocessing was fit on the full data before splitting (leakage), which metric was used and why, what the baseline is, how hyperparameters were chosen, and whether the saved model is the one that serves predictions.

Traps: accuracy as the metric on imbalanced classes, no evidence of overfitting checks, a headline accuracy with no test set shown, why this model over a simpler one.

## Deep learning model

The brain is the network architecture, the loss, the optimizer and the training loop.

Trace: dataset → preprocessing and augmentation → model → loss → optimizer step → validation → checkpoint → inference.

Check input and output shapes, what is pretrained and what is frozen, epochs, learning rate, batch size, early stopping, and what the validation curve shows (only if it was provided).

Traps: claiming training when the project only fine-tunes a pretrained model, no baseline, hyperparameters nobody can explain.

## LLM, RAG and agent systems

The brain is usually the pipeline design and the prompts, not a trained model. The model itself is often an API call.

RAG trace: ingestion → chunking → embedding → vector store → query embedding → retrieval (top-k, threshold) → prompt assembly → LLM call → parsing and validation → response.

Agent trace: user goal → orchestrator → agent or tool selection → tool call → state passed between agents → termination condition → final answer.

One rule governs this whole category: separate what the LLM decides from what the code decides. The model generates text. The code builds prompts, parses and validates output, retries, routes, stores results and enforces limits.

Check the model name and version, chunk size and overlap and why, the embedding model and its dimensions, top-k and thresholds, prompt templates, structured-output validation, handling of API errors and timeouts, cost and latency, and how quality is evaluated.

Traps: calling API use "training", no evaluation of retrieval or answers, hallucination handling that amounts to telling the model not to hallucinate, prompt injection through retrieved text, non-determinism, accuracy claims with no evaluation shown.

## Data pipelines and analytics

The brain is the transformation logic and the modelling choices.

Trace: source → ingestion → staging → transformation → serving layer → dashboard or report. Follow one record or one batch.

Check full versus incremental loads, idempotency (what happens if a job runs twice), scheduling and orchestration, data quality tests, schema changes, how late or duplicate records are handled, and where compute cost lands. For BI dashboards, check how each measure is defined, how filters and aggregation behave, and how data refreshes.

Traps: metric definitions that differ between views, a snapshot demo presented as a live pipeline.

## Statistics and experimentation

The brain is the design of the experiment and the choice of test.

Trace: unit of randomization → group assignment → events → metric → aggregation → test → decision.

Check the hypotheses, why this test, the significance level, sample size and power, effect size versus p-value, multiple comparisons, and peeking at results early.

Traps: reading a p-value as the probability the hypothesis is true, treating statistical significance as business importance, ignoring sample ratio mismatch.

## Optimization

The brain is the set of decision variables, the objective function, the constraints and the solver.

Trace: data → model construction → solve → solution extraction → interpretation.

Check what each variable and constraint means in domain terms, whether the problem is linear or integer, how solver status is handled (infeasible, unbounded), and which assumptions make the model an approximation. Include a tiny instance with two or three variables so the user can solve it by hand.

Traps: a model that is feasible only because its constraints are loose, ignoring uncertainty in inputs such as predicted values.

## Recommendation, search and ranking

The brain is candidate generation, scoring and ordering.

Check the score formula, cold start, how results are evaluated (name metrics only if the project uses them), and freshness or popularity bias.

## Computer vision

Trace: image → preprocessing → model → post-processing → output (boxes, labels, masks).

Check the dataset and labelling, input size, pretrained weights, metrics, and which lighting or camera conditions were tested.

## Mobile, desktop, embedded and games

Map to the same skeleton: input events → state → logic → output.

Check the event loop or lifecycle, threading, hardware or OS interfaces, persistence, communication protocols, and whether it was tested on a real device.

## Other inputs

- Notebooks: cells are pipeline steps, so follow them in order. Outputs saved in a notebook show one past run and do not prove the notebook still reproduces them. Watch for hidden state from cells run out of order.
- Datasets: report the schema, size and types the file shows. Do not claim distributions or balance unless you computed them.
- Screenshots: describe what is visible. The backend behind a screenshot is unknown unless something else shows it.
- Diagrams and reports: treat them as documentation. Their claims are [DOCUMENTED BUT NOT VERIFIED] until code confirms them.
- Slides: keep slide numbers, because they are your citations.
