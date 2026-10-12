# Connecting the model research to the app

## What already exists

The [research repository](https://github.com/mnshah0101/playonsportsresearch), inspected at
`22a39b63526a696595ee5eb42b9bc790514464b9`, contains data preparation, model training and
evaluation code. Its reported model results were not rerun for this assignment. The latency
benchmark entry point was still marked for later work.

Keep the research software separate from the lightweight app server. Preparing this app does
not require PyTorch, model weights or a GPU.

The research code's `ModelAdapter` provides `fit`, `predict`, `save` and `load`. Its result fields
include `quality_issue`, `issues`, severity/confidence and metadata, with numeric scores stored
separately. The app expects `defects`, `issue_score`, database IDs and video timestamps. A future
integration task must translate between those formats and test that no meaning is lost.

## Rules for that translation

- The worker reads each frame and keeps its video timestamp, job, asset, model and settings.
  A filename alone is not enough, and the browser cannot supply trusted model results.
- Preserve descriptive defect names. Use a separate mapping when grouping names for evaluation.
  A crew-facing label is a description, not a performance measurement.
- Use the validated numeric issue score and record how it was calculated. A model saying
  “I am confident” in text is not a calibrated probability.
- Invalid model output is a failure, not a clean frame.
- Current labels rate the whole image. Leave each defect's severity unavailable until it has
  been checked against suitable per-defect labels. Do not copy the image rating onto every defect.
- Score-based alerts can be reviewed while severity filtering remains off. Each threshold must
  record the model and validation results used to choose it.
- Missing heat maps must be shown as unavailable. An attention map or generated box needs testing
  before we treat it as a reliable defect location.

## Measuring performance fairly

Keep all frames from one game in the same data split. Games linked by duplicate images must also
stay together. Train the model on training data. Use validation data to choose prompts, models,
checkpoints and thresholds. Learn the label vocabulary from training data only. Keep the final
test set separate for the final comparison.

Do not regenerate splits or change locked test labels during app work. Review disputed labels
through a separate, recorded process. If final test data was already used to investigate model
errors, disclose that and agree on a fresh evaluation method.

Report precision, recall, F1 and per-defect results, including how many examples support each
number. Report severity results only where they are meaningful. Keep the hardware, model version,
image preparation, random seed and data split with the results so another person can reproduce them.
Explain uncertainty and whether settings were chosen using those same results.

The team still needs to clarify how the reported 90%+ precision/recall goal will be accepted (D-04).
The Figma numbers are examples and cannot be used as test results.

## Experiments are not final design decisions

The September 25 suggestions—changing loss weights, adding an MLP classifier or changing
structured-output training—are experiments. The meeting summary and current code may describe
different runs, so check the exact settings before claiming how a result was produced.

Known labels and descriptions are training targets or evaluation information, not default inputs
when analyzing a new frame. Giving the model answers that would not be available in real use
would make the evaluation misleading.

## Before selecting a model for the app

Record the exact saved model/checksum, adapter version, settings, result format, scoring method,
validation results, threshold and measured memory/latency. Confirm that the data can be used for
the demo. The initial Qwen candidates and later research recommendations are not a confirmed
application model selection (D-10).
