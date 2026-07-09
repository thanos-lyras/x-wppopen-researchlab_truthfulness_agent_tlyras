"""CLI wrapper around the SFT pipeline — same services as the `fine_tune_truthfulness` MCP tool."""

import argparse
from mcp_server.utils import config
from mcp_server.utils.dataset_processor import DatasetProcessor
from mcp_server.utils.tuning_manager import TuningManager
from services.gcs_service import GCSService


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--split-only", action="store_true",
                   help="write the 3 JSONL files and exit (no GCS / SFT)")
    p.add_argument("--no-wait", action="store_true",
                   help="submit the SFT job and exit (don't block until terminal state)")
    args = p.parse_args()

    paths = DatasetProcessor().prepare()
    if args.split_only:
        return

    gcs = GCSService()
    train_uri = gcs.upload(paths["train"], f"finetuning/{config.BASE_MODEL}/train.jsonl")
    val_uri   = gcs.upload(paths["val"],   f"finetuning/{config.BASE_MODEL}/val.jsonl")

    tuning = TuningManager()
    job = tuning.submit(train_uri, val_uri)

    if args.no_wait:
        print("submitted; not waiting. Track in Vertex AI Console.")
        return

    tuning.wait(job)


if __name__ == "__main__":
    main()
