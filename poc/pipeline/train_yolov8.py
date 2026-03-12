import argparse
from pathlib import Path

from .utils import load_yaml, resolve_path

try:
    from ultralytics import YOLO  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    YOLO = None


def main() -> None:
    parser = argparse.ArgumentParser(description="POC YOLOv8 training")
    parser.add_argument("--config", default="poc/config/poc.yaml")
    parser.add_argument("--dataset", default="data/datasets/yolo/dataset.yaml")
    parser.add_argument("--project", default="data/runs")
    args = parser.parse_args()

    config = load_yaml(args.config)
    train_cfg = config.get("train", {})
    model_path = train_cfg.get("yolo_model", "yolov8n.pt")
    epochs = int(train_cfg.get("epochs", 10))
    imgsz = int(train_cfg.get("imgsz", 640))

    if YOLO is None:
        raise RuntimeError("ultralytics not installed. Please pip install ultralytics.")

    dataset_yaml = resolve_path(args.dataset)
    project_dir = resolve_path(args.project)
    project_dir.mkdir(parents=True, exist_ok=True)

    model = YOLO(model_path)
    model.train(data=str(dataset_yaml), epochs=epochs, imgsz=imgsz, project=str(project_dir))
    print("training completed")


if __name__ == "__main__":
    main()

