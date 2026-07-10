"""CSV → preprocess → stratified train/val/test JSONL for Vertex SFT."""

import json
from pathlib import Path
import pandas as pd
from sklearn.model_selection import train_test_split
from . import config


class DatasetProcessor:
    def prepare(self, csv_path=None) -> dict[str, Path]:
        """Preprocess → 80/10/10 stratified split → write 3 JSONL files. Returns {'train','val','test'} → Path."""
        df = self._preprocess(pd.read_csv(csv_path or config.DATA_CSV))

        # Stratified by binary_label so each split preserves the True/False ratio.
        train, temp = train_test_split(df, test_size=0.20,
                                       stratify=df["binary_label"], random_state=config.SEED)
        val, test = train_test_split(temp, test_size=0.50,
                                     stratify=temp["binary_label"], random_state=config.SEED)

        paths = {n: config.SPLITS_DIR / f"{n}.jsonl" for n in ("train", "val", "test")}
        for name, split, training in [("train", train, True), ("val", val, True), ("test", test, False)]:
            self._write(paths[name], split, training)
            print(f"{name:5s}: {len(split):5d}  TRUE={split['binary_label'].mean():.3f}  → {paths[name]}")
        return paths

    def _preprocess(self, df: pd.DataFrame) -> pd.DataFrame:
        n0 = len(df)
        df = df.assign(binary_label=df["Label"].map(config.LABEL_MAP))
        df = df[["statement", "binary_label"]].dropna()
        df = df[df["statement"].str.strip() != ""].drop_duplicates().reset_index(drop=True)
        print(f"preprocess: kept {len(df)}/{n0} rows ({n0 - len(df)} dropped)")
        return df

    def _write(self, path: Path, df: pd.DataFrame, training: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for _, row in df.iterrows():
                f.write(json.dumps(self._row(row, training), ensure_ascii=False) + "\n")

    def _row(self, row: pd.Series, training: bool) -> dict:
        """One Vertex SFT record. Training rows include the model turn; test rows wrap as request+ground_truth for offline eval."""
        msg = {
            "systemInstruction": {"role": "system", "parts": [{"text": config.SYSTEM_INSTRUCTION}]},
            "contents": [{"role": "user", "parts": [{"text": row["statement"]}]}],
        }
        target = config.TARGET_TOKEN[row["binary_label"]]
        if training:
            msg["contents"].append({"role": "model", "parts": [{"text": target}]})
            return msg
        return {"request": msg, "ground_truth": target}
