"""Vertex AI Gemini SFT job submission + polling + .env write-back."""

import time

from dotenv import set_key
from google import genai
from google.genai import types

from . import config


class TuningService:
    """Submit a Vertex AI Gemini SFT job, poll until terminal, write the deployed endpoint to .env."""

    def __init__(self):
        """Build a Vertex-mode genai client pinned to the regional TUNING_LOCATION ('global' rejects SFT)."""
        self.client = genai.Client(
            vertexai=True, project=config.PROJECT_ID, location=config.TUNING_LOCATION
        )

    def submit(self, train_uri: str, val_uri: str):
        """Kick off the SFT job with hyperparams from config.py. Returns immediately; training runs server-side."""
        # Display name encodes base model + hyperparams so jobs are distinguishable in Vertex UI.
        display_name = (
            f"ft_{config.BASE_MODEL.split('/')[-1]}"
            f"_ep{config.N_EPOCHS}_lr{config.LRM}_{config.ADAPTER_SIZE.lower()}_v1stmt"
        )
        print(f"submitting tuning job: {display_name}")
        job = self.client.tunings.tune(
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
        # Persist the job name so `check_finetune_status` can poll it later
        # without the user re-typing the resource path.
        set_key(".env", "LAST_TUNING_JOB", job.name, quote_mode="never")
        return job

    def wait(self, job, poll_interval: int = 5 * 60):
        """Poll every `poll_interval` seconds until terminal; on SUCCEEDED, write the endpoint to .env."""
        # job.state is a JobState enum — compare by .name to avoid the "JobState." prefix
        # that str() emits, which would never match a bare-name allowlist.
        terminal = {"JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED"}
        while True:
            job = self.client.tunings.get(name=job.name)
            print(f"[{time.strftime('%H:%M:%S')}] state = {job.state}")
            if job.state.name in terminal:
                break
            time.sleep(poll_interval)
        # Write the deployed-endpoint path, not `tuned_model.model` — Vertex serves
        # tuned Gemini inference via endpoints; the bare `models/<id>@<ver>` path 404s.
        if job.tuned_model and job.tuned_model.endpoint:
            print(f"\n✅ tuned endpoint: {job.tuned_model.endpoint}")
            # quote_mode="never" keeps the bare-value style of the existing .env lines.
            set_key(".env", "FINE_TUNED_MODEL", job.tuned_model.endpoint, quote_mode="never")
        return job
