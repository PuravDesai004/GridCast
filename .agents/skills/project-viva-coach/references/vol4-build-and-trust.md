# Volume 4: Build and trust (Parts 12 to 18)

Goal: map the explanation onto the real code, then show how the project behaves when things go wrong, how it is checked, how it could be attacked, and where it is weak. Honesty is the point of this volume. Examiners trust students who know where their project breaks.

## Part 12: Code structure

Use the inventory output and the files you read. Explain the files that make the architecture work and skip the rest; do not narrate every line. For each important file:

```
FILE:                   path
PURPOSE:                what it is for
KEY FUNCTIONS/CLASSES:
CALLED BY / CALLS:
INPUT / OUTPUT:
IMPORTANT LOGIC:        the part worth understanding
WHY IT MATTERS:
```

Then draw the call chain at file level:

```
FILE A → FILE B → FILE C → DATABASE / API / MODEL
```

Build it from the import graph and confirm it by reading, since imports show what is available, not what is called on the main path. For the one or two functions that carry the most weight, walk through the logic step by step, including branches and early returns.

## Part 13: APIs and endpoints

Include this only if the project exposes or consumes an API. List endpoints from the code (decorators, route files, controllers), never from what such a framework typically has:

| Method | Endpoint | Purpose | Input | Output | Important behavior |
|---|---|---|---|---|---|

Then take the most important endpoint and show REQUEST → VALIDATION → PROCESSING → RESPONSE with real field names. Report what is present and write "Not implemented" for what is not: authentication, authorization, error handling and status codes, rate limiting, input validation.

## Part 14: Error handling

For each relevant failure, show the chain ERROR → DETECTION → HANDLING → USER RESPONSE, and state whether the system retries, falls back, returns an error, logs, continues or stops. Relevant failures include invalid input, missing or empty data, model failure, external API failure, database failure, timeout, malformed response, authentication failure, statistical edge cases and file parsing failure.

Read the try/except blocks, validation code and fallback branches. Where nothing handles a failure, write "Not implemented" and say what would actually happen. That answer is far better in a viva than a vague claim of robustness.

## Part 15: Testing and validation

Report what exists: unit, integration or end-to-end tests, mocking, edge-case and error tests, performance tests, statistical validation, model evaluation, data validation. For each important test:

```
WHAT IT TESTS:
WHY IT MATTERS:
WHAT SUCCESS MEANS:
```

Then answer: what does this testing NOT prove? Typical gaps: tests mock the external service, so real-API behaviour is untested. The evaluation set is small or comes from the same source as the training data. Failure paths have no tests. Quote results (accuracy, coverage, latency) only where the material shows them. If there are no tests, say so, and describe how the user can honestly argue correctness (manual checks against known cases, sample outputs, whatever evaluation they did run).

## Part 16: Security and reliability

Check each of these and report only what the project has: authentication, authorization, input validation, secrets management, PII handling, prompt injection, SQL injection, file upload risks, API exposure, rate limiting, data leakage, dependency risks, external API security, privacy. For anything missing, write "Not implemented." Do not invent protections.

The inventory script lists environment variable names and flags suspicious hard-coded values as candidates by file and line. Treat those as leads to verify, and never repeat a secret's value in your answer.

## Part 17: Limitations

Be brutally honest. Cover technical, algorithmic, statistical, AI, data, scalability, security and UX limitations, plus known bugs and missing features. For each:

```
WHAT → WHY → IMPACT → POSSIBLE FIX
```

Tag each [LIMITATION]. Do not soften them or bury them. A limitation the user names first and explains well reads as understanding.

## Part 18: Future scope

Separate CURRENT from FUTURE. Describe future features only if the material mentions them or strongly supports them. Tag them [PLANNED] when the material says so, and call anything else a suggestion. For each one: what it adds, why it is useful, and which part of the current architecture it would change.
