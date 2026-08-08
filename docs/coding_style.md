Code style requirement: minimal abstraction.

Write the simplest implementation that is clear and correct. Do not equate
software quality with creating more functions. 

Before writing new code, first inspect the existing codebase for relevant local 
functions, utilities, and abstractions. Reuse or extend them whenever appropriate 
instead of duplicating existing functionality.

Use direct assignments for constants, paths, hyperparameters, column names,
configuration values, and simple one-off expressions. Do not wrap these values
in getter, builder, initializer, or factory functions.

A helper function should be introduced only when it provides a concrete benefit:
- the logic is reused;
- it represents a meaningful domain-level operation;
- it contains nontrivial logic;
- it requires independent testing;
- or it isolates I/O, randomness, mutation, or external state.

Avoid:
- functions called only once;
- one-line functions that merely return a literal or simple expression;
- wrappers around a single library call;
- functions whose names merely restate their implementation;
- speculative abstractions intended only for hypothetical future reuse;
- unnecessary classes, factories, configuration builders, and getter functions.

For notebooks and analysis scripts, prefer a readable top-to-bottom execution
flow. Keep simple transformations visible rather than hiding every step inside
a function.

