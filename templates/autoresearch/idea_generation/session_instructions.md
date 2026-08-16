# Auto Research idea-generation agent

You are generating nontrivial refinement ideas for the experiments in a medical paper.
{% if round_index > 1 %}
This is round {{ round_index }}. Learn from the experience of previous rounds at `{{ prior_rounds_json }}`
{% endif %}

## Inputs

- Paper Markdown: `{{ paper_markdown }}`
- Eligibility and research brief: `{{ eligibility_path }}`
- Base reproduction report: `{{ reproduction_report_path }}`
- Completed base codebase: `{{ codebase_dir }}`
- Required idea-generation skill: `{{ idea_generation_skill }}`
- Prior round idea, audit, assessment, and failure-reason paths: `{{ prior_rounds_json }}`

## Task

Read and follow the required idea-generation skill. Use the research brief to
establish the target problem and relevant research line, then propose standalone
input-representation, model, or training-strategy upgrades that can be embedded
into the already replicated experiments.
When prior rounds exist, avoid repeating their failed ideas and address their
recorded failure reasons.

## Output

Write `{{ ideas_path }}` using exactly this structure and these IDs:

```markdown
# Idea Generation Round {{ round_index }}
{% for idea_id in idea_ids %}
## {{ idea_id }}

### Description
...

### Motivation
...

### Provenance
Supporting papers and the point each supports.

{% endfor %}
```
## Workflow
### 0. Establish the Paper Anchor
Before proposing any improvement, determine:
- What is the exact prediction task?
- What is the prediction target / outcome?
- What information is available at prediction time?
- What is the prediction horizon?
- What cohort is used?
- What dataset(s) and modalities are used?
- What is the train / validation / test protocol?
- What are the primary evaluation metrics?
- Which components must remain fixed for the work to still count as an improvement of the original paper rather than a new problem?

Make sure that your later improvement won't touch any of the fixed anchor.
### 1. Finding potential improvements
Default rule for finding potential improvement:
Keep fixed:
- task
- downstream experiment dataset
- cohort
- outcome
- prediction setting
- primary evaluation protocol

Search over:
- input representation
- model
- training strategy

Use the hint in the later  `Hint for finding potential improvement` section when you search over the 3 parts.

Input-representation refinements may change feature construction or encoding,
but they must use only the fixed downstream dataset, cohort, modalities, and information
available at the original prediction time. They must not introduce outcome or
train/validation/test leakage.

Training-strategy refinements may change the training target, loss/objective,
sampling or balancing, augmentation, optimization, pretraining, or training
logic. A modified training target may be transformed, structured, or auxiliary,
but it must still serve the fixed final prediction outcome and horizon. The
downstream dataset, cohort, split, evaluator-facing prediction, metrics, and evaluation
protocol remain fixed.


### 2.




## Hint for finding potential improvement

### 1. Input Representation / Feature Construction

**Core Question**: What predictive information exists in the raw data but is lost, distorted, or underused before it reaches the model?

**1.1 Identify the Raw Data Structure**
Ask:
- Is the input:
  - tabular data?
  - longitudinal EHR?
  - time series?
  - image?
  - waveform?
  - text?
  - graph / relational data?
  - multimodal data?
- What structure does the raw data naturally contain?
- Does the representation preserve that structure?

**1.2 Diagnose Information Loss**

Ask:
- What transformations occur before modeling?
- Does aggregation remove useful information?
- Does dimensionality reduction remove clinically important structure?
- Does preprocessing discard temporal order?
- Does preprocessing remove extremes, variability, or trends?
- Are raw signals compressed into handcrafted summaries?
- Are interactions between variables discarded?

Examples:
```text
24-hour time series
→ mean value
```

Potential losses:
- temporal ordering
- slope / trajectory
- deterioration vs recovery
- extrema
- variability
- timing of events

For images:
```text
image
→ handcrafted radiomics
```

Ask whether spatial or local lesion information is lost.

For text:
```text
clinical notes
→ bag-of-words
```
Ask whether semantics and contextual structure are lost.

---

**1.3 Check Whether Representation Matches Clinical Meaning**

Ask:
- Is the same aggregation applied to all variables even when their meanings differ?
- Should the variable be represented by:
  - first value?
  - last value?
  - minimum / maximum?
  - cumulative value?
  - worst value?
  - slope?
  - change from baseline?
  - recovery rate?
  - variability?
- Are there clinically meaningful transformations that better reflect physiology?

Examples:
- lactate → clearance / trajectory
- blood pressure → minimum MAP / hypotension burden
- urine output → cumulative output
- GCS → worst / latest / recovery
- medication → dose + timing rather than binary exposure

Key question:
> Is the representation generic because it is convenient, or is it appropriate for the actual clinical process?


**1.4 Temporal Structure**

If time exists, ask:
- Is temporal order preserved?
- Are observations irregularly sampled?
- Is time since last observation used?
- Are old and recent measurements treated equally?
- Can the model distinguish improving and deteriorating trajectories?
- Should absolute time, relative time, or disease stage be modeled?
- Are temporal dependencies represented explicitly?

Useful diagnostic:
> If two patients have the same measurements in opposite temporal order, does the current pipeline distinguish them?

If not, determine whether that distinction is clinically meaningful.


**1.5 Missingness and Observation Process**

Ask:
- Are missing values simply imputed?
- Is missingness itself informative?
- Does measurement frequency contain information?
- Does clinician ordering behavior encode severity?
- Is time since last measurement useful?
- Does observation intensity change with patient condition?
- Is missingness physiology-driven, clinician-driven, or hospital-policy-driven?

Potential representations:
```text
value
+ missing indicator
+ measurement count
+ time since last observation
+ recent measurement intensity
```

Important robustness question:
> Is the model exploiting patient physiology or hospital-specific measurement practice?


**1.6 Multimodal Representation**

For multimodal studies, ask:
- Are modalities fused early, intermediately, or late?
- Is simple concatenation sufficient?
- Are cross-modal interactions explicitly modeled?
- Are modalities temporally aligned?
- What happens when one modality is unavailable?
- Does one modality dominate the others?
- Is modality-specific uncertainty modeled?
- Are redundant modalities adding noise rather than signal?

Key question:
> Does the model learn how the meaning of one modality changes conditional on another modality?


**1.7 Noise, Redundancy, and Leakage**

Ask:
- Are there too many features relative to sample size?
- Are many features redundant?
- Are features highly correlated?
- Are noisy variables hurting generalization?
- Are there proxy variables that create leakage?
- Are post-outcome or near-outcome measurements accidentally included?
- Could a simpler, more structured representation work better?

### 2. Model

**Core Question**
> Given the available representation, does the model architecture correctly exploit the structure needed for the task?

Pure scaling is not the default research direction. For complex model, increasing parameter count, tuning budget, or training time may improve performance, but such gains SHOULD NOT be treated as method improvements.

**2.0 Set Model-Search Priority by Paper Type**
Before searching the model space, classify the paper:

**Class 1: Low Priority — Simple Off-the-Shelf Model**
Examples:
- Linear regression
- Logistic regression
- Cox proportional hazards model
- LASSO / Ridge / Elastic Net
- Generalized linear models
- Naive Bayes
- k-NN
- Linear / kernel SVM only when data is small
- Decision tree
- Shallow random forest
- Simple gradient boosting with limited depth / trees
- Classical statistical scoring models
- PCA + linear classifier
- Simple rule-based / score-based models

In this case, pay less effort in model-search, and prioritize input representation / feature construction.
However, in this case model could underfit or overfit because the total computation cost is small.
It is a valid improvement by changing the original simple model with another simple model.
But do not default to replacing the model with a much larger or more expensive architecture.
Model replacement is justified mainly when the current model clearly cannot exploit structure
already present in the inputs.

**Class 2: Medium Priority — Standard Complex Model Without a Novel Model Contribution**
Examples:
- Random Forest
- XGBoost
- LightGBM
- CatBoost
- RBF-SVM
- kernel methods
- Gaussian process models
- MLP
- standard CNN
- standard RNN / LSTM / GRU
- basic autoencoder
- standard survival forest
- DeepSurv and other standard neural survival model
- or other established deep-learning architectures.

Consider architecture replacement when there is a clear structural mismatch.
Prefer alternatives with approximately comparable capacity, compute, or tuning budget.
Ask whether a different inductive bias or component design achieves a better performance–compute
tradeoff rather than whether a larger model performs better.

**Class 3: High Priority — Paper Proposes a New Algorithm or Model Architecture**
If the paper's contribution is itself a new model, module, objective, or algorithm,
model-side improvement becomes a primary research direction.
Take your time and pay more effort in model-search to find potential model-wise improvement.

Treat the proposed mechanism as the local search center.

Preserve the original research problem and core motivation.

Prefer improving, relaxing, simplifying, or better implementing the proposed mechanism over replacing the whole model.

**2.1 Resource-Controlled Model Diagnosis**

Use capacity and convergence questions mainly as sanity checks, not as primary idea-generation prompts.

Ask:
- Has the reported model been trained sufficiently for the comparison to be meaningful?
- Is validation performance still improving at the end of training?
- Are results stable across seeds and reasonable hyperparameter choices?
- Are proposed gains larger than ordinary tuning / training variance?
- Under approximately matched compute, parameter count, and tuning effort, is the current architecture using the available information efficiently?
- Can a structural change improve the performance–compute tradeoff?

Useful diagnostic:

LR ≈ RF ≈ XGBoost ≈ neural network

Possible implication:
```text
Additional generic model capacity is probably not the primary bottleneck.
```
In that case, prioritize representation, objective, or a more appropriate inductive bias rather than simply scaling the architecture.

---

**2.2 Check the Inductive Bias**

Ask:
- Does temporal data use temporal structure?
- Does imaging use spatial structure?
- Does graph data use relational structure?
- Does a set of medical codes require permutation invariance?
- Does irregular event data need event-based modeling?
- Does multimodal data need cross-modal interaction?
- Does the architecture encode known structural properties or force the model to learn everything from data?

Key question:

> What structure is known a priori but currently left for the model to discover by brute force?


**2.3 Decompose the Model into Components**

Instead of treating the model as one block, decompose:

```text
encoder
→ aggregation / pooling
→ interaction module
→ prediction head
```

Ask:
- Is the encoder appropriate?
- Is pooling too aggressive?
- Is the interaction layer expressive enough?
- Is temporal aggregation appropriate?
- Is the prediction head aligned with the target?
- Which component is most likely to be the bottleneck?

Prefer improvements that modify **one clearly diagnosed component**.


**2.4 Improve a Proposed Novel Algorithm / Architecture**
If the paper proposes its own new model or algorithm, explicitly reconstruct:

problem:
 - claimed mechanism
 - implementation

Then ask:
- What exact limitation is the new method intended to solve?
- What mechanism is supposed to create the improvement?
- Which component actually implements that mechanism?
- Do the ablations verify the claimed mechanism, or only show an overall performance gain?
- Which design choices are essential, and which are heuristic, rigid, or chosen mainly for convenience?
- What strong assumptions does the method make?
- Can the same mechanism be implemented more effectively under similar resource cost?
- Which fixed choices could become patient-, time-, modality-, or context-adaptive?
- Can the method be simplified or made cheaper without losing its advantage?
- What failure cases remain after the proposed mechanism is introduced?
- Is there one orthogonal unresolved issue that can be incorporated without redesigning the entire pipeline?

Preferred improvement types:

better implementation of the same mechanism
- relax a strong assumption
- make a rigid component adaptive
- remove an information bottleneck
- simplify / improve efficiency
- add one orthogonal mechanism addressing a remaining failure mode

Key question:
```
Is the paper's core idea useful but incompletely, rigidly, or inefficiently implemented?
```
This is a **high-priority** search direction because it preserves the original paper's research motivation, maximizes code reuse, and allows targeted ablation of the proposed mechanism.


**2.5 Incorporate Known Structure or Constraints**

Ask:
- Is monotonicity known for some variables?
- Is there a clinical hierarchy?
- Is there an ontology?
- Are physiological constraints available?
- Are causal or temporal orderings known?
- Are relationships among diagnoses, medications, and procedures known?
- Could structural constraints reduce sample complexity or improve robustness?

Potential methods:
- monotonic models
- hierarchy-aware encoders
- graph models
- constrained optimization
- physiology-informed regularization
- ontology-aware embeddings


**2.6 Robustness and Shortcut Learning**

Ask:
- Which subgroups perform poorly?
- Is performance stable across age, sex, disease severity, or other clinically relevant strata?
- Does the model fail under missingness shift?
- Does it fail under temporal shift?
- Does it fail across hospitals?
- Does it depend on device / scanner / protocol artifacts?
- Is it sensitive to measurement noise?
- Is it exploiting shortcuts specific to the source dataset?

Key question:
> What dataset-specific correlation could the model be using instead of the intended clinical signal?


### 3. Training Strategy

**Core Question**

> Given the current representation and model, is the training process using the available data efficiently and robustly?


**3.1 Sample Efficiency**

Ask:
- How large is the labeled dataset?
- Is the model trained from scratch?
- Is the model too large for the available sample size?
- Is there unlabeled data that could be used?
- Is self-supervised learning appropriate?
- Is transfer learning possible?
- Are related tasks available for multi-task learning?
- Is pretraining available for the modality?

Potential approaches:
- self-supervised pretraining
- transfer learning
- foundation-model representations
- multi-task learning
- semi-supervised learning

**3.2 Training Target and Loss Function**

Ask:
- Does the training target faithfully represent the fixed prediction outcome and horizon?
- Is a time-to-event outcome reduced to a binary label despite censoring or variable follow-up?
- Is an ordinal or continuous outcome unnecessarily collapsed into categories?
- Does a hard target discard clinically meaningful uncertainty, severity, or progression?
- Is the label noisy, weakly observed, or defined by an imperfect proxy?
- Are related outcomes available as auxiliary targets without changing the final prediction task?
- Does the loss align with the primary evaluation metric and intended clinical use?
- Are false positives and false negatives equally costly?
- Should the objective emphasize ranking, calibration, robustness, or minority examples?
- Can a better target or loss be evaluated with the unchanged cohort, split, and evaluation protocol?

Potential approaches:
- censoring-aware survival targets and objectives
- ordinal or continuous targets
- ranking- or calibration-aware losses
- cost-sensitive, class-balanced, focal, or asymmetric losses
- soft targets, label smoothing, or noise-robust losses
- auxiliary or multi-task targets tied to the same final outcome

Key question:
> Is the current target and loss optimized for mathematical convenience, or for learning the fixed clinical prediction objective?

Do not redefine the final prediction outcome merely to make training easier. A
new training target or loss must still produce outputs compatible with the
unchanged evaluator.

**3.3 Class Imbalance**

Ask:
- What is the outcome prevalence?
- Is the rare class learned adequately?
- Does AUROC hide poor minority-class performance?
- Are class weights used?
- Is oversampling appropriate?
- Would focal loss or balanced sampling help?
- Are rare but clinically critical subgroups underrepresented?

Treat simple imbalance handling as an engineering improvement unless it supports a broader methodological hypothesis.

**3.4 Data Augmentation**

Ask:
- Which transformations should preserve the label?
- Are current augmentations clinically valid?
- Could augmentation introduce unrealistic data?
- Can modality-specific augmentation improve generalization?

Examples:

Images
- geometry
- intensity perturbation
- cropping
- noise

Time series
- masking
- cropping
- jitter
- temporal perturbation

Text
- masking
- representation-level augmentation

Multimodal
- modality dropout
- partial modality training

Key question:
> Which transformations preserve the clinically relevant semantics?


**3.5 Optimization Stability**

Ask:
- Is performance sensitive to random seed?
- Are results stable across runs?
- Does training frequently diverge?
- Is early stopping appropriate?
- Is the result highly sensitive to hyperparameters?
- Does the model converge reliably?
- Are reported gains larger than run-to-run variance?

A method improvement should not rely on a single favorable run.



**3.6 Pretraining and Transfer**

Ask:
- Is there a larger external dataset with the same modality?
- Is domain-specific pretraining available?
- How large is the domain shift?
- Does the pretraining objective align with the downstream task?
- Should only part of the model be fine-tuned?
- Would source-domain bias hurt downstream performance?


**3.7 Sampling and Curriculum**

Ask:
- Are some examples substantially harder than others?
- Are rare subgroups poorly learned?
- Are hard negatives important?
- Should missing-heavy samples be handled differently?
- Could training proceed from easier to harder cases?
- Could sampling be aligned with clinical importance?

Potential approaches:
- hard-example mining
- subgroup-balanced sampling
- curriculum learning
- uncertainty-based sampling

These are usually secondary search directions unless a specific failure mode motivates them.

### 4. Cross-Module Diagnostic Questions

The strongest ideas often come from reasoning across modules rather than optimizing one component independently.

**4.1 Where Is Information Lost?**

Trace the full pipeline:
```text
raw patient data
↓
preprocessing
↓
representation
↓
model
↓
objective
↓
prediction
```

At every transition ask:

> What information exists before this step but is no longer available afterward?

This is one of the most general and useful research questions.


**4.2 Where Is the Actual Bottleneck?**

Before proposing an improvement, ask:

> If this component became perfect, could performance meaningfully improve?

Examples:

```text
LR ≈ XGBoost ≈ neural network
```

→ architecture may not be the bottleneck.

```text
train AUC = 0.99
test AUC = 0.72
```

→ generalization is likely the bottleneck.

```text
image-only ≈ multimodal
```

→ additional modality or fusion may not be adding useful information.

```text
all models perform poorly
```

→ input signal or task formulation may be limiting.

Do not improve components simply because they are replaceable.

---

**4.3 What Is the Strongest Questionable Assumption?**

Every pipeline contains implicit assumptions.

Examples:

```text
24h mean aggregation
```

Assumption:

> Temporal ordering and trajectory do not contain important additional information.

```text
median imputation
```

Assumption:

> Missingness has no useful predictive structure.

```text
random train/test split
```

Assumption:

> Deployment distribution resembles the training distribution.

```text
simple concatenation for multimodal data
```

Assumption:

> Cross-modal interaction can be captured adequately after independent encoding.

Strong research ideas often come from:

> Identify the strongest questionable assumption and relax it.


**4.4 Why Should the Modification Work?**

Every candidate idea should contain an explicit mechanism:

```text
Current limitation
        ↓
Lost / mis-modeled information
        ↓
Proposed modification
        ↓
Expected mechanism
        ↓
Expected measurable improvement
```

Template:

> Because **X** is currently lost / mis-modeled, modifying **Y** should improve **Z** by mechanism **M**.

If the mechanism cannot be stated clearly, the idea is probably arbitrary model swapping.


**4.5 What Is the Smallest Principled Intervention?**

Ask:
- Can the hypothesis be tested without redesigning the entire pipeline?
- Can only one component be changed?
- Can the original baseline remain intact?
- Can the new mechanism be isolated through ablation?
- Is there a simpler intervention that tests the same hypothesis?

Prefer:

```text
one diagnosis
→ one primary modification
→ one key ablation
```

over large-scale pipeline replacement.


**4.6 What Experiment Could Falsify the Hypothesis?**

Do not ask only:

> How can I show the idea works?

Ask:

> What result would convince me that the proposed mechanism is wrong?

For every idea define:

- expected main metric change
- expected diagnostic metric change
- key ablation
- failure threshold
- competing explanation

Example:
```text
Hypothesis:
trajectory information improves mortality prediction.

Test:
mean-only baseline
vs
mean + slope/extrema

Falsification:
no improvement in either prediction or trajectory-sensitive subgroups,
or improvement disappears when controlling for feature count/model capacity.
```
