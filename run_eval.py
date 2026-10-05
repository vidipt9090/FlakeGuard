import subprocess
import sys
import time


def run_command(step_name, cmd_args):
    print("\n" + "=" * 90)
    print(f"PIPELINE STEP: {step_name}")
    print("=" * 90)
    start_time = time.time()
    res = subprocess.run([sys.executable] + cmd_args, check=True)
    elapsed = time.time() - start_time
    print(f"Step '{step_name}' completed in {elapsed:.2f}s with exit code {res.returncode}")


def main():
    print("==========================================================================================")
    print("FLAKEGUARD COMPLETE REPRODUCIBILITY PIPELINE")
    print("Regenerating all benchmark results and metric tables in results/ from scratch...")
    print("==========================================================================================")

    total_start = time.time()

    # Step 1: Validate Neutralization
    run_command("Validate Neutralization", ["scripts/validate_neutralization.py"])

    # Step 2: Shuffled Benchmark Runs
    run_command("20-Run Shuffled Benchmark", ["scripts/run_benchmark_runs.py"])

    # Step 3: Rerun Baselines Evaluation
    run_command("Rerun Baselines Evaluation", ["eval/run_baselines.py"])

    # Step 4: LLM Prompts Evaluation
    run_command("LLM Prompts Evaluation (v1, v2, v3)", ["llm/run_prompts.py"])

    # Step 5: Failure Log Generation
    run_command("Failure Log Generation", ["analysis/failure_log.py"])

    # Step 6: Navigator Call Graph Evaluation
    run_command("Navigator Call Graph Evaluation", ["scripts/run_navigator_eval.py"])

    total_elapsed = time.time() - total_start

    print("\n" + "=" * 90)
    print("FULL REPRODUCIBILITY PIPELINE COMPLETED SUCCESSFULLY!")
    print(f"Total pipeline execution time: {total_elapsed / 60:.2f} minutes")
    print("Generated results files:")
    print("  - results/runs.csv")
    print("  - results/baseline_metrics.csv")
    print("  - results/llm_metrics.csv")
    print("  - results/llm_raw/<v1|v2|v3>/<case>.json")
    print("  - results/failure_log.csv")
    print("  - results/navigation.csv")
    print("=" * 90)


if __name__ == "__main__":
    main()
