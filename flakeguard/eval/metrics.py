import math
import random


def compute_precision_recall_f1(y_true, y_pred, pos_label="flaky"):
    """Compute binary Precision, Recall, and F1 score for a given target label."""
    tp = sum(
        1
        for t, p in zip(y_true, y_pred)
        if t == pos_label and p == pos_label
    )
    fp = sum(
        1
        for t, p in zip(y_true, y_pred)
        if t != pos_label and p == pos_label
    )
    fn = sum(
        1
        for t, p in zip(y_true, y_pred)
        if t == pos_label and p != pos_label
    )

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        (2 * precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def compute_root_cause_accuracy(rc_true, rc_pred):
    """Compute accuracy of root-cause predictions."""
    if not rc_true or len(rc_true) == 0:
        return 0.0
    correct = sum(1 for t, p in zip(rc_true, rc_pred) if t == p)
    return correct / len(rc_true)


def compute_false_quarantine_rate(
    y_true, y_pred, real_label="real", flaky_label="flaky"
):
    """Compute False-Quarantine Rate = (real failures labeled flaky) / (total real failures)."""
    real_count = sum(1 for t in y_true if t == real_label)
    if real_count == 0:
        return 0.0
    real_as_flaky = sum(
        1
        for t, p in zip(y_true, y_pred)
        if t == real_label and p == flaky_label
    )
    return real_as_flaky / real_count


def compute_confusion_matrix(
    y_true, y_pred, labels=("flaky", "real", "stable")
):
    """Compute 3x3 confusion matrix mapping [actual][predicted] -> count."""
    cm = {actual: {pred: 0 for pred in labels} for actual in labels}
    for t, p in zip(y_true, y_pred):
        if t in cm and p in cm[t]:
            cm[t][p] += 1
    return cm


def bootstrap_ci(metric_fn, data, n_bootstraps=1000, ci=95.0, seed=42):
    """Compute non-parametric bootstrap confidence interval for a metric function over data.

    Args:
        metric_fn: Function taking a sample dataset (list) and returning float.
        data: List of data samples (e.g. dicts or tuples).
        n_bootstraps: Number of bootstrap samples (default: 1000).
        ci: Confidence interval percentage (default: 95.0).
        seed: Random seed for reproducibility.

    Returns:
        Dict with 'mean', 'ci_lower', 'ci_upper'.
    """
    if not data or len(data) == 0:
        return {"mean": 0.0, "ci_lower": 0.0, "ci_upper": 0.0}

    rng = random.Random(seed)
    n = len(data)
    boot_stats = []

    for _ in range(n_bootstraps):
        sample = [data[rng.randint(0, n - 1)] for _ in range(n)]
        boot_stats.append(metric_fn(sample))

    boot_stats.sort()
    alpha = (100.0 - ci) / 2.0
    lower_idx = int(math.floor((alpha / 100.0) * n_bootstraps))
    upper_idx = int(math.ceil(((100.0 - alpha) / 100.0) * n_bootstraps)) - 1

    lower_idx = max(0, min(lower_idx, n_bootstraps - 1))
    upper_idx = max(0, min(upper_idx, n_bootstraps - 1))

    mean_val = sum(boot_stats) / n_bootstraps
    ci_lower = boot_stats[lower_idx]
    ci_upper = boot_stats[upper_idx]

    return {"mean": mean_val, "ci_lower": ci_lower, "ci_upper": ci_upper}
