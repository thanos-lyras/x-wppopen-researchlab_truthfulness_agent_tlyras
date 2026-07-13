"""Vertex Gemini SFT: submit job → poll to terminal → write deployed endpoint to `.env`."""

import os
import time
from dotenv import set_key
from google.genai import types
from services.vertex_client import client
from . import config


class TuningManager:
    def submit(self, train_uri: str, val_uri: str):
        # Display name encodes hyperparams so jobs are distinguishable in Vertex UI.
        display_name = (
            f"ft_{config.BASE_MODEL.split('/')[-1]}"
            f"_ep{config.N_EPOCHS}_lr{config.LRM}_{config.ADAPTER_SIZE.lower()}_v1stmt"
        )
        print(f"submitting tuning job: {display_name}")
        job = client.tunings.tune(
            base_model=config.BASE_MODEL,
            training_dataset={"gcs_uri": train_uri},
            config=types.CreateTuningJobConfig(
                tuned_model_display_name=display_name,
                validation_dataset={"gcs_uri": val_uri},
                adapter_size=config.ADAPTER_SIZE,
                epoch_count=config.N_EPOCHS,
                learning_rate_multiplier=config.LRM,
            ),
        )
        print(f"job submitted: {job.name}")
        # Persist so check_finetune_status can poll it later without re-typing.
        # Write to BOTH: .env for future process boots (CLI/local); os.environ
        # for same-process reads (in-MCP submit → in-MCP check_finetune_status).
        set_key(".env", "LAST_TUNING_JOB", job.name, quote_mode="never")
        os.environ["LAST_TUNING_JOB"] = job.name
        return job

    def wait(self, job, poll_interval: int = 5 * 60):
        # Compare by .name — str(job.state) includes the "JobState." prefix.
        terminal = {"JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED"}
        while True:
            job = client.tunings.get(name=job.name)
            print(f"[{time.strftime('%H:%M:%S')}] state = {job.state}")
            if job.state.name in terminal:
                break
            time.sleep(poll_interval)
        # Serve tuned Gemini via the deployed endpoint path, not `tuned_model.model` (which 404s).
        if job.tuned_model and job.tuned_model.endpoint:
            print(f"\n✅ tuned endpoint: {job.tuned_model.endpoint}")
            set_key(".env", "FINE_TUNED_MODEL", job.tuned_model.endpoint, quote_mode="never")
            # Live-update so predict picks up the endpoint without an MCP restart.
            os.environ["FINE_TUNED_MODEL"] = job.tuned_model.endpoint
        return job
