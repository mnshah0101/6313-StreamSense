# Experiment order and gates

Every experiment config composes now. Implementations arrive by delivery checkpoint;
see the README for executable versus planned behavior.

| Order | ID | Purpose / gate | Target in project brief |
| ---: | --- | --- | --- |
| 1 | E-00 | Environment, tests, then actual model smoke | Sept 23–24 |
| 2 | E-01 | Audit and split; Gate A before any model result counts | Sept 24 |
| 3 | E-02a | BRISQUE/NIQE binary baseline | Sept 25 |
| 4 | E-02b | ResNet-18 binary, terms, severity baseline | Sept 25 |
| 5 | E-03-lite | Qwen3.5-0.8B zero-shot; alternate Qwen2.5-VL-3B | Sept 25 |
| 6 | E-07a | 64-image / 50-step LoRA pipeline check, not a reported result | Sept 28 |
| 7 | E-07b | Rank × learning-rate grid if E-03 shows a gap worth closing | Oct 2 |
| 8 | E-05 | Validation-only threshold/severity calibration; Gate D | Oct 2–9 |
| 9 | E-06 | Game, source, defect, severity and weather errors | Oct 9 |
| 10 | E-09 | Hardware-labelled latency, throughput and stream estimate | Oct 9 |
| 11 | E-10 | Quantization only if latency/memory/throughput requires it | Conditional TODO |
| 12 | Final | Locked-test comparison of selected VLM, CNN and classical model | Oct 16 |

The E-07b config specifies nine runs: ranks 8/16/32 × learning rates
0.00005/0.0001/0.0002 at one seed. After validation selection, rerun the best two with
seeds 0, 1, and 2. Slurm array generation is delivered in stage 7.

Threshold targets are validation constraints, not guarantees of production precision.
Report support and game-bootstrap uncertainty, particularly for rare terms and the
user-labelled subset. Never select configurations using the final test result.

E-04 prompt stability, E-08 flexible naming, E-11 distillation, E-12 conditional
inference, E-13 heat maps, and E-14 Slack UX retain their external project gates.
This repository does not send Slack messages or implement those deferred features.
