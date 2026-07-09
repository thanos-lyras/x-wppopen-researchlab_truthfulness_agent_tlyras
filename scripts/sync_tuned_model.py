"""Poll an existing Vertex tuning job to terminal state and write FINE_TUNED_MODEL to .env."""

import argparse
from mcp_server.utils.tuning_manager import TuningManager
from services.vertex_client import client


def main():
    p = argparse.ArgumentParser()
    p.add_argument("job_name",
                   help="Vertex tuning job resource name (projects/<num>/locations/<region>/tuningJobs/<id>)")
    args = p.parse_args()

    job = client.tunings.get(name=args.job_name)
    print(f"polling {args.job_name}\ncurrent state: {job.state}")
    TuningManager().wait(job)


if __name__ == "__main__":
    main()
