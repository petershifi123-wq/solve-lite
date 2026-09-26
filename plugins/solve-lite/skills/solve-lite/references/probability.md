# Probability, calibration, and abstention

solve lite never prints a percent sign for an uncalibrated decision score.

## Relative support

When verified history is too small or fails validation, `probability_kind` is `relative_support`. The displayed integers use deterministic largest-remainder rounding and sum to 100, for example `A 63 / B 27 / C 10`. They are ranking support points, not probabilities. `calibrated_probability` stays `null`.

## Held-out calibration

For each bounded `domain` and `kind`, only prior local-neighbor attempts with exactly one user-confirmed or deterministic outcome are eligible. This includes attempts that later abstained at the calibrated boundary, preventing a successful-predictions-only sample. A fingerprint hash assigns every request to one stable split: four buckets for fitting and one bucket for held-out validation. A group never moves between splits.

The calibrator uses a fixed finite grid of temperature values. It requires at least 30 fitting examples, 10 held-out examples, and at least two outcome labels in both sets. The held-out gate requires:

- calibrated multiclass Brier Score no worse than the raw score;
- Expected Calibration Error (10 equal-width confidence bins) at most 0.15;
- at least five held-out examples above the learned abstain boundary; and
- at least 0.80 held-out selective accuracy above that boundary.

Only a gate marked `VALID` may set `probability_kind=calibrated_heldout` and show `%`. Failure returns `UNAVAILABLE` or `INVALID`, keeps the raw neighbor ranking as relative support, and does not claim probability.

## Metrics and boundary

Multiclass Brier Score is the mean sum of squared probability error across labels. ECE compares mean confidence with observed accuracy in each confidence bin. Normalized entropy is `-sum(p log p) / log(K)` for `K > 1`; margin is the top probability minus the second. The abstain boundary is the lowest fixed candidate threshold from 0.50 through 0.95 that reaches the target accuracy with enough fitting examples, and it must pass the held-out gate. A calibrated prediction below that boundary returns `ABSTAIN`.

Calibration is local, deterministic, and advisory. It adds no external API, online training, provider estimator, or production authority.
