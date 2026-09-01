# Proportional Revision

## Goal

When revising project files after feedback, make changes proportional to the actual scope and severity of the issue.

The revised project files should normally read as if they had been written correctly from the beginning.

## Core Rules

### 1. Keep local feedback local

If the user points out a local problem X:

* fix X;
* fix anything that logically depends on X;
* preserve unrelated correct content.

Do not make X a recurring warning, example, organizing principle, or theme of
the affected file, module, workflow, or project merely because it was mentioned
recently.

“Local” limits the thematic prominence and unrelated scope of the feedback. It
does not require retaining obsolete constructs or minimizing the number of
files touched. Change completeness follows `change_scope.md`.

### 2. Counterfactual Reader Test

After revising, imagine a reader who never saw the previous mistake.

For the new content introduced because of the feedback, ask:

> Would this still be natural and useful if the mistake had never occurred?

If not, remove it.


## Final Check

Before finishing:

* Is the actual problem fixed?
* Are all logically affected consequences fixed?
* Did I change anything unrelated?
* Did the latest feedback become disproportionately prominent?
* Do the project files read naturally without knowledge of the previous mistake?

If so, return the clean revised project files.
