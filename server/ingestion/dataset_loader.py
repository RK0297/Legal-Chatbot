"""Dataset loader for Indian Law Dataset from Hugging Face (viber1/indian-law-dataset)."""
from pathlib import Path
import json
import logging
from typing import Optional, List, Dict

import os

DEFAULT_RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

logger = logging.getLogger(__name__)

class IndianLawDatasetLoader:
    """Extracts, cleans, and structures Indian law dataset into standardized JSON format."""

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = Path(output_dir or DEFAULT_RAW_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.dataset = None

    def load_dataset(self, dataset_name: str = "viber1/indian-law-dataset"):
        """Load dataset from Hugging Face Hub."""
        try:
            from datasets import load_dataset
            logger.info(f"Downloading dataset from Hugging Face: {dataset_name}")
            self.dataset = load_dataset(dataset_name)
            logger.info(f"Dataset loaded. Available splits: {list(self.dataset.keys())}")
            return self.dataset
        except ImportError:
            logger.error("Hugging Face 'datasets' library is not installed. Please run: pip install datasets")
            raise
        except Exception as e:
            logger.error(f"Failed to load dataset {dataset_name}: {e}")
            raise

    def convert_to_json(self, split: str = "train", max_examples: Optional[int] = None) -> List[Dict]:
        """Convert a dataset split into Instruction-Response records."""
        if not self.dataset or split not in self.dataset:
            logger.error(f"Split '{split}' unavailable or dataset not loaded.")
            return []

        split_data = self.dataset[split]
        if max_examples:
            split_data = split_data.select(range(min(max_examples, len(split_data))))

        logger.info(f"Converting {len(split_data)} records from '{split}' split...")
        converted = []
        skipped = 0

        for idx, item in enumerate(split_data):
            try:
                instruction = str(item.get("Instruction") or item.get("question") or "").strip()
                response = str(item.get("Response") or item.get("answer") or "").strip()

                if len(instruction) < 10 or len(response) < 50:
                    skipped += 1
                    continue

                converted.append({
                    "id": idx,
                    "Instruction": instruction,
                    "Response": response,
                })
            except Exception as e:
                logger.warning(f"Error parsing item {idx}: {e}")
                skipped += 1

        logger.info(f"Successfully converted {len(converted)} records (skipped {skipped}).")
        return converted

    def save_to_json(self, data: List[Dict], filename: str = "legal_data_all.json") -> Path:
        """Write records to raw JSON file."""
        target_path = self.output_dir / filename
        logger.info(f"Saving {len(data)} records to {target_path}...")
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Successfully written: {target_path}")
        return target_path

    def process_and_save_all(self, max_per_split: Optional[int] = None) -> Path:
        """Execute full pipeline for all splits."""
        if not self.dataset:
            self.load_dataset()

        all_records = []
        for split in self.dataset.keys():
            records = self.convert_to_json(split=split, max_examples=max_per_split)
            all_records.extend(records)

        return self.save_to_json(all_records, "legal_data_all.json")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    loader = IndianLawDatasetLoader()
    loader.load_dataset()
    loader.process_and_save_all()
