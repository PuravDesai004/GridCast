# Volume 2: Flow (Parts 4 and 5)

Goal: let the user follow one real piece of data from the moment someone acts to the moment the result appears, and describe what happens for the other important operations. "What happens internally when I click this?" is a favourite examiner question.

## Part 4: End-to-end data flow

Pick the single most important user action, the one the project exists to perform (uploading a file, running an analysis, sending a query, requesting a prediction, starting an experiment). Say which one you picked and why. Trace it from start to finish through these steps, skipping any that do not exist in this project (a command-line tool has no frontend, a batch job has no request):

1. User action
2. Frontend
3. Request creation
4. API or entry point
5. Validation
6. Data preprocessing
7. Core processing
8. Model, algorithm or service call
9. Post-processing
10. Database or storage
11. Final response
12. Frontend visualization or output

Use a table so the data's journey stays visible:

| Step | Component (file:function) | Receives (format) | Does | Hands on (format) |
|---|---|---|---|---|

Under it, explain each step in a few sentences: what happens, why it happens, what data is passed and in what shape, which component handles it, and what the next component receives. The format columns matter most. Show the actual shape with real field names from the code or schema (a short JSON object, a DataFrame with named columns, a list of chunks), and point out where the data changes shape. Most "what if" questions from examiners land on those handoffs.

Tag each step. A step the documents describe but the code does not contain is [DOCUMENTED BUT NOT VERIFIED], and the trace should say so rather than smoothing over the gap.

## Part 5: "What happens when..."

Choose three to six operations that matter most in this project (the user clicks Analyze, uploads a file, requests a prediction, a scheduled job runs, a query is submitted, an error occurs). If one is the operation already traced in Part 4, refer back to it instead of repeating it.

Give each operation two passes. First a plain-language story of two to four sentences. Then the technical chain:

```
USER ACTION → ENTRY POINT → VALIDATION → PROCESSING → MODEL / ALGORITHM
            → DATABASE / SERVICE → POST-PROCESSING → RESPONSE
```

Fill the chain with real names and say which step could fail. Include at least one failure lifecycle (the external API times out, the file is malformed, the input is empty), because "what if X fails?" is among the most common viva questions. If the code has no handling for that failure, say what actually happens (crash, silent wrong output, hang) and tag it [LIMITATION]. The full catalogue of failure modes belongs to Part 14. Here, show one or two in motion.
