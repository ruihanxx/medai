# Proportional Revision

## Goal

When revising project files after feedback, make changes proportional to the actual scope and severity of the issue.

The revised project files should normally read as if they had been written correctly from the beginning.

## Core Rules

### 1. small fix for small issues

If the user points out a local problem X:

* fix X;
* fix anything that logically depends on X;
* preserve unrelated correct content.

Do not make X the new theme of the project files merely because it was mentioned recently.

### 2. Prefer the smallest complete revision

For a minor/local problem, make a local patch,
make sure the patch is of the same scale as original content.

Do not unnecessarily:

* add new warnings or explanations in document;
* add a more detailed and expanded content


Revision scope should follow the **logical dependency of the defect**, not its conversational salience.


### 3. Counterfactual Reader Test

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
