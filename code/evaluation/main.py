import csv
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent.parent
CODE_DIR = ROOT / "code"
DATA_DIR = ROOT / "dataset"

sys.path.insert(0, str(CODE_DIR))
from main import Router  # noqa: E402


def load_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build_message(row: Dict[str, str]) -> Dict[str, str]:
    return {
        "message_id": row["message_id"],
        "user_id": row["user_id"],
        "conversation_type": row["conversation_type"],
        "group_id": row.get("group_id", ""),
        "business_id": row.get("business_id", ""),
        "sender_user_id": row.get("sender_user_id", ""),
        "created_at": row.get("created_at", ""),
        "message_text": row.get("message_text", ""),
        "media_type": row.get("media_type", ""),
        "media_id": row.get("media_id", ""),
        "forwarded_count": row.get("forwarded_count", "0"),
    }


def evaluate_samples(router: Router) -> Tuple[int, int, List[Dict[str, str]]]:
    rows = load_csv(DATA_DIR / "sample_messages.csv")
    correct = 0
    mismatches: List[Dict[str, str]] = []
    for row in rows:
        pred_action, pred_type, _, _, _ = router.route(build_message(row))
        if pred_action == row["action"] and pred_type == row["message_type"]:
            correct += 1
        else:
            mismatches.append(
                {
                    "message_id": row["message_id"],
                    "expected_action": row["action"],
                    "expected_type": row["message_type"],
                    "predicted_action": pred_action,
                    "predicted_type": pred_type,
                }
            )
    return len(rows), correct, mismatches


def validate_predictions() -> Tuple[int, int, List[str]]:
    messages = load_csv(DATA_DIR / "messages.csv")
    predictions_path = DATA_DIR / "output.csv"
    if not predictions_path.exists():
        return 0, 0, ["predictions file missing"]

    with predictions_path.open(newline="", encoding="utf-8") as fh:
        predictions = list(csv.DictReader(fh))

    issues: List[str] = []
    if predictions and list(predictions[0].keys()) != ["message_id", "action", "message_type", "reason", "confidence", "evidence_message_ids"]:
        issues.append("prediction header mismatch")
    if len(predictions) != len(messages):
        issues.append(f"expected {len(messages)} predictions, found {len(predictions)}")
    return len(messages), len(predictions), issues


def main() -> None:
    router = Router()
    sample_count, correct_count, mismatches = evaluate_samples(router)
    message_count, prediction_count, issues = validate_predictions()

    accuracy = correct_count / sample_count if sample_count else 0.0
    print(f"sample_messages.csv: {correct_count}/{sample_count} correct ({accuracy:.2%})")
    if mismatches:
        print("sample mismatches:")
        for item in mismatches[:10]:
            print(f"- {item['message_id']}: expected {item['expected_action']}/{item['expected_type']}, got {item['predicted_action']}/{item['predicted_type']}")
    print(f"output.csv: {prediction_count}/{message_count} predictions present")
    if issues:
        for issue in issues:
            print(f"- {issue}")


if __name__ == "__main__":
    main()
