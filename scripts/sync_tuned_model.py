"""Wait on an existing Vertex AI tuning job and write FINE_TUNED_MODEL=… to .env.

Usage:
    python -m scripts.sync_tuned_model <JOB_RESOURCE_NAME>

JOB_RESOURCE_NAME looks like:
    projects/<num>/locations/us-central1/tuningJobs/<id>
"""

import argparse

from mcp_server.utils.tuning_service import TuningService


def main():
    p = argparse.ArgumentParser()
    p.add_argument("job_name",
                   help="Vertex tuning job resource name (from the original submit output)")
    args = p.parse_args()

    tuning = TuningService()
    job = tuning.client.tunings.get(name=args.job_name)
    print(f"polling {args.job_name}\ncurrent state: {job.state}")
    tuning.wait(job)


if __name__ == "__main__":
    main()
