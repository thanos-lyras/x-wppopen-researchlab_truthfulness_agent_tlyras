"""Vertex AI Gemini SFT job submission + polling + .env write-back."""

import time
from pathlib import Path

from google import genai
from google.genai import types

from . import config


class TuningService:
    def __init__(self):
        self.client = genai.Client(
            vertexai=True, project=config.PROJECT_ID, location=config.TUNING_LOCATION
        )

    def submit(self, train_uri: str, val_uri: str):
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
        return job

    def wait(self, job, poll_interval: int = 5 * 60):
        terminal = {"JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED"}
        while True:
            job = self.client.tunings.get(name=job.name)
            print(f"[{time.strftime('%H:%M:%S')}] state = {job.state}")
            if str(job.state) in terminal:
                break
            time.sleep(poll_interval)
        if job.tuned_model and job.tuned_model.model:
            print(f"\n✅ tuned model: {job.tuned_model.model}")
            self._write_env_var("FINE_TUNED_MODEL", job.tuned_model.model)
        return job

    @staticmethod
    def _write_env_var(key: str, value: str, env_path: str | Path = ".env") -> None:
        """Set or replace KEY=VALUE in `.env`, preserving the rest of the file."""
        path = Path(env_path)
        lines = path.read_text().splitlines() if path.exists() else []
        new_lines, found = [], False
        for line in lines:
            if line.startswith(f"{key}="):
                new_lines.append(f"{key}={value}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={value}")
        path.write_text("\n".join(new_lines) + "\n")
        print(f"✅ wrote {key}=… to {env_path}")
