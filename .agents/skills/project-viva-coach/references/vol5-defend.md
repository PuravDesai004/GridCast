# Volume 5: Defend (Parts 19 to 23)

Goal: turn understanding into delivery. Slide scripts the user can speak, viva questions answered at two depths, the reason the project matters, and one mental model that holds it all.

## Part 19: Presentation script

Only when slides, a PPT or a PDF deck were provided. For every slide use this layout:

```
# SLIDE N: <title>
## What the slide means
## Speaking script
## What each box or bullet means
## Important numbers
## Likely questions
## Strong answers
## Transition
```

- Meaning: the technical content behind the slide, in plain terms.
- Script: how a student would say it about their own project. Natural and confident, never "I will now explain the following". Size it to the slide: a title slide gets a sentence or two, a dense architecture slide gets more. Make the reasoning visible so the user can rebuild the script in their own words.
- Boxes and bullets: what each one stands for in the real system.
- Numbers: every percentage, threshold, count, dimension, latency, score, parameter and formula on the slide, with where it comes from and what it means. If a number cannot be traced to the code, a result file or the documents, tag it [DOCUMENTED BUT NOT VERIFIED] and tell the user to find its source before the viva. If a slide claims something the code does not do, flag the discrepancy.
- Likely questions and strong answers: specific to this slide, concise and technically accurate.
- Transition: one natural sentence into the next slide.

## Part 20: Viva preparation

Generate likely questions in these groups, tuned to this project. Seed ideas:

- BASIC: what does it do, who is it for
- ARCHITECTURE: how do the components talk to each other
- TECHNICAL: how does the algorithm or model work
- WHY: why this technology, threshold, chunk size, formula
- ALTERNATIVE: why not the obvious other choice
- DATA: how is data stored and transformed
- AI/ML: where exactly is AI or ML used, and where is it not
- STATISTICS: why this test or metric (only if relevant)
- EDGE CASES: what if the input is empty, the API is down, the file is malformed
- SECURITY: what are the risks
- TESTING: how do you know it is correct
- LIMITATIONS: what is the biggest weakness
- FUTURE: what would you improve
- DEEP VIVA: questions that separate someone who understands the implementation from someone who memorized slides

Deep viva questions sound like this: "Open the file where X happens and walk me through it." "What does this function return when the input is empty?" "Why did you pick this threshold, and what changes at a different value?" "Which line would you change to add Y?" "What breaks if this component is removed?" "Where in the code is the claim on slide 7 true?" "The output is wrong, so how would you debug it?"

Format every question like this:

```
QUESTION
SHORT ANSWER:   something to say in 10 to 20 seconds
DEEP ANSWER:    the stronger version if the examiner presses
COMMON MISTAKE: what not to say
```

Build answers only from the material. Where the right answer depends on a reason that lives in the author's head (why this model, why this threshold), write the skeleton of the answer and ask the user to supply their real reason. Common mistakes usually come from overclaiming: calling a hosted-model call "training", presenting a planned feature as built, quoting a number from a slide that nothing supports.

Cover every group, but let the number of questions follow the size of the project.

## Part 21: Why it matters

Say what real problem the project addresses, why it matters, who benefits, what it improves, what would happen without it, and its practical value. Keep claims proportionate. Do not invent impact figures, and do not call a student project production-ready unless the material shows it.

## Part 22: Project name

If the name carries meaning, explain the literal meaning, the intended meaning, why it fits, and how the architecture supports it. If it does not genuinely fit, skip this part. A forced metaphor gives an examiner something to puncture.

## Part 23: Master mental model

Close the guide with the whole project in one place:

1. One-paragraph explanation
2. One architecture diagram
3. End-to-end flow, ten steps at most
4. Ten things to memorize, only the most important facts
5. 30-second answer to "What is your project?"
6. 1-minute answer to "Explain how your project works."
7. 3-minute answer to "Explain your project's architecture and methodology."

Keep the facts identical across the three lengths, and use only claims already established and tagged in earlier volumes. Write the answers as a base the user can reshape. The final measure is that they can explain the project in their own words, so finish by inviting them to say it back to you, and give feedback on what they say.
