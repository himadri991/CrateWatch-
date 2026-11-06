# Writing Guide

Use this checklist before submitting the report, comments, README, or PPT.

## Voice

- Write in plain English. Prefer short sentences over long compound sentences.
- Use active voice. Name the actor: "The API rejects duplicate sequence numbers", not "Duplicate sequence numbers are rejected".
- State the number, the file, or the command when it helps the reader check the claim.
- Explain why a decision was made. Do not describe every line of code.
- Keep the tone neutral. Avoid sales language, hype, and slogans.
- It is fine to say what was not tested. Limitations make the report stronger.

## Punctuation and symbols

- Do not use U+2014. Use a comma, a colon, parentheses, or a new sentence.
- Do not use en dashes in ranges. Use "to": "15 to 25 C".
- Do not use emojis, checkmarks, or decorative icons in the report or PPT.
- Use straight quotes in code and JSON. Use normal text quotes in prose.
- Use "percent" in prose and `%` in tables if space is tight.

## Phrases to remove

These phrases show up in generic AI drafts. Replace them with a concrete claim.

- "in today's fast-paced world"
- "in an era where"
- "it is important to note"
- "it is worth noting"
- "needless to say"
- "at the end of the day"
- "when it comes to"
- "the future of X starts here"
- "more than just a"
- "not just X, but Y"
- "this isn't about X, it's about Y"
- "a testament to"
- "whether you're a X or a Y"
- "from X to Y" when used as a vague range
- "let's dive in"
- "dive into"
- "embark on a journey"
- "navigate the landscape"
- "unlock the power"
- "elevate"
- "empower"
- "foster"
- "leverage"
- "delve"
- "seamless"
- "robust"
- "cutting edge"
- "revolutionary"
- "transformative"
- "game changer"
- "holistic"
- "synergy"
- "comprehensive"
- "meticulous"
- "pivotal"
- "crucial"
- "vital role"
- "underscore"
- "showcase"
- "myriad"
- "plethora"
- "tapestry"
- "realm"
- "landscape" when used as a metaphor
- "in conclusion"
- "to sum up"
- "the result? "
- "imagine a world where"

## Patterns to avoid

- Three-item lists that exist only for rhythm: "fast, reliable, and secure". Use a real list with different lengths if the content needs it.
- A generic opening paragraph that defines the industry before saying anything specific.
- A closing paragraph that repeats the introduction.
- Over-signposting: "First, I will... Next, I will... Finally, I will...". Use headings instead.
- Empty contrast: "It is not just a dashboard. It is a platform." State what it does.
- Fake quotes, invented customer names, or made-up statistics.
- Claims that a feature is "production ready" when it was not deployed.
- Screenshots or numbers without a source. Name the file or command.

## Slide rules

- One idea per slide.
- At most six bullets. At most twelve words per bullet.
- Use a table or a screenshot when the slide would otherwise be a wall of text.
- Put the measured result on the slide. Do not make the audience wait for an appendix.
- Keep the same color and font on every slide.
- Use the notes field for detail, not the slide body.
- Do not put a paragraph in a text box and shrink the font below 16 points.

## Code comments

- Comment the reason, not the syntax.
- Use a comment when a reader would ask "why is this here?".
- Do not comment every line.
- Do not leave generated comments such as "This function returns the result" or "Initialize the variable".
- Keep comments short and specific to this project.

## Final checks

Run the style checker before submission:

```bash
make style
```

Search the project for U+2014 in an editor before submission.

Read the PPT out loud once. If a slide sounds like a brochure, rewrite it with a number, a file name, or a concrete action.
