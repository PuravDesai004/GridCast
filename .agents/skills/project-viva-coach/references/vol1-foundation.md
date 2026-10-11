# Volume 1: Foundation (Parts 1 to 3)

Goal: put the whole project in the user's head before any detail. At the end they can answer "Explain your project" and redraw the architecture from memory.

Open the volume with the "Materials reviewed" and "Not provided" lines from step 1 of SKILL.md.

## Part 1: What is this project?

Write in plain language, as if explaining to a smart friend outside the field.

Cover:
- the problem it solves and who it is for
- what goes in, what happens to it, what comes out
- why the project exists
- what makes it more than a basic implementation of the same idea

Then give three reusable pieces:

1. One-line explanation: a single sentence that carries the whole project.
2. 30-second explanation: what to say when a professor asks "Explain your project."
3. Simple analogy: include one only if a real-world comparison genuinely fits, and say where it breaks down. A forced analogy misleads and gives the examiner something to poke at.

Cite where the purpose comes from. If the README or report states it, say so. If you worked it out from the code, tag it [INFERRED] and ask the user to confirm it is the real motivation, since they are the one who has to say it aloud.

"What makes it different" is where overselling creeps in. Base it on what the code does that a naive version would not (validation, caching, a custom scoring step, a fallback path), not on adjectives from the README.

## Part 2: Architecture at a glance

Draw one plain-text diagram of the actual system, top to bottom, in a code block. Label each box with the real component name and, where useful, the file that implements it. Branch where the code branches. Start from this skeleton and adapt it, because every project differs:

```
USER
  ↓
FRONTEND (what the user touches)
  ↓
API / ENTRY POINT
  ↓
CORE PIPELINE
  ├── MODULE A
  ├── MODULE B
  └── MODULE C
  ↓
DATABASE / STORAGE
  ↓
EXTERNAL SERVICES / MODELS
  ↓
RESULT → back to the user
```

Remove boxes that do not exist (a CLI tool has no frontend, a notebook project may have no API). Do not add a box for a component that is only mentioned in the documents with no code behind it. If something is documented but absent, mark it [DOCUMENTED BUT NOT VERIFIED] or [PLANNED] in the diagram.

Under the diagram, give each block a short entry. Part 3 goes deep, so keep these to what ties the map together:

```
BLOCK: <name> [TAG]  (file:function)
What it is and why it exists:
Receives:
Produces:
```

## Part 3: Complete system components

Group the project into the layers that actually exist. Typical layers: frontend, backend or API, authentication, business logic, core processing pipeline, AI or ML models, NLP, statistics, algorithms, database, vector database, cache, file storage, external APIs, background jobs, message queues, monitoring, testing, deployment. Include only what is present.

For each component use this template, and explain the component's role in THIS project, not the textbook definition:

```
### <Component> [TAG]  (file:function)
WHAT:         what it is here
WHY:          why the project needs it
HOW:          what happens inside it, step by step
INPUT:        what it receives, and in what format
OUTPUT:       what it hands on, and in what format
TECHNOLOGY:   what it is built with, and why this one
DEPENDENCIES: what it uses, and what uses it
FAILURE:      what happens if it fails or is removed
ALTERNATIVE:  what else could have done the job
LIMITATION:   where it falls short
```

Part 2 answers "what are the pieces and how do they connect". Part 3 answers "how does each piece work inside". Do not repeat the same sentences in both: Part 2 gives the short version (what, why, receives, produces, where), and Part 3 gives the rest (how, technology, dependencies, failure, alternative, limitation).

A good entry reads: "FastAPI is the API layer here. When the frontend posts X, it validates Y and passes it to Z, which does the actual processing." A bad entry reads: "FastAPI is a Python web framework." If the material does not show what a component does in this project, write "Not enough information is provided to determine this." rather than describing what such components usually do.
