import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "dataset"


def load_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def contains_any(text: str, patterns: List[re.Pattern]) -> bool:
    return any(p.search(text) for p in patterns)


def tokenize(text: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", normalize(text)) if len(t) > 2}


class Router:
    def __init__(self) -> None:
        self.messages = load_csv(DATA_DIR / "messages.csv")
        self.users = {row["user_id"]: row for row in load_csv(DATA_DIR / "users.csv")}
        self.groups = {row["group_id"]: row for row in load_csv(DATA_DIR / "groups.csv")}
        self.group_members = {(row["group_id"], row["user_id"]): row for row in load_csv(DATA_DIR / "group_members.csv")}
        self.business_accounts = {row["business_id"]: row for row in load_csv(DATA_DIR / "business_accounts.csv")}
        self.user_business_history = {(row["user_id"], row["business_id"]): row for row in load_csv(DATA_DIR / "user_business_history.csv")}
        self.message_history = load_csv(DATA_DIR / "message_history.csv")
        self.message_events = {(row["user_id"], row["message_id"]): row for row in load_csv(DATA_DIR / "message_events.csv")}
        self.history_by_user: Dict[str, List[Dict[str, str]]] = {}
        for row in self.message_history:
            self.history_by_user.setdefault(row["user_id"], []).append(row)
        for rows in self.history_by_user.values():
            rows.sort(key=lambda r: r["created_at"], reverse=True)

    def get_user(self, user_id: str) -> Dict[str, str]:
        return self.users.get(user_id, {})

    def get_business(self, business_id: str) -> Dict[str, str]:
        return self.business_accounts.get(business_id, {})

    def get_user_business(self, user_id: str, business_id: str) -> Optional[Dict[str, str]]:
        return self.user_business_history.get((user_id, business_id))

    def get_group_member(self, group_id: str, user_id: str) -> Optional[Dict[str, str]]:
        return self.group_members.get((group_id, user_id))

    def get_event(self, user_id: str, message_id: str) -> Optional[Dict[str, str]]:
        return self.message_events.get((user_id, message_id))

    def get_history_for_message(self, message: Dict[str, str]) -> List[Dict[str, str]]:
        user_id = message["user_id"]
        rows = self.history_by_user.get(user_id, [])
        candidates: List[Tuple[float, Dict[str, str]]] = []
        text = normalize(message.get("message_text", ""))
        tokens = tokenize(message.get("message_text", ""))
        for row in rows:
            if row.get("message_id") == message.get("message_id"):
                continue
            score = 0.0
            if message.get("sender_user_id") and row.get("sender_user_id") == message.get("sender_user_id"):
                score += 4.0
            if message.get("business_id") and row.get("business_id") == message.get("business_id"):
                score += 2.5
            if message.get("group_id") and row.get("group_id") == message.get("group_id"):
                score += 2.0
            if row.get("conversation_type") == message.get("conversation_type"):
                score += 1.0
            overlap = len(tokens & tokenize(row.get("message_text", "")))
            score += overlap * 0.6
            if text and not row.get("message_text"):
                score -= 0.4
            event = self.get_event(user_id, row.get("message_id", ""))
            if event:
                if event.get("message_opened") == "1" or event.get("message_replied") == "1":
                    score += 1.0
                if event.get("notification_dismissed") == "1" or event.get("muted_after_message") == "1" or event.get("message_reported") == "1":
                    score -= 1.5
            candidates.append((score, row))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [row for _, row in candidates[:6] if _ > 0.0]

    def pick_evidence(self, message: Dict[str, str]) -> str:
        hist = self.get_history_for_message(message)
        if not hist:
            return "none"
        ids = []
        seen = set()
        for row in hist:
            mid = row.get("message_id")
            if mid and mid not in seen:
                ids.append(mid)
                seen.add(mid)
            if len(ids) >= 3:
                break
        return ";".join(ids) if ids else "none"

    def detect_scam(self, text: str, message: Dict[str, str], history: List[Dict[str, str]]) -> bool:
        suspicious_patterns = [
            re.compile(r"\b(verify|verification|account[- ]?blocked|account[- ]?block|profile will be blocked|profile restricted|support alert|security alert|wallet kyc|link open|open the link|complete pending account check|check the wallet details|card number|pin|reattempt fee|refund approved|release the amount|release package)\b", re.I),
            re.compile(r"\b(route|routing) override\b", re.I),
            re.compile(r"\b(otp|password|login code|one[- ]time password|6 digit login code)\b.*\b(share|send|confirm|verify|restore|keep|active|block|account|wallet|profile|link)\b", re.I),
            re.compile(r"\b(share|send|confirm|verify|restore|keep|active|block|account|wallet|profile|link)\b.*\b(otp|password|login code|one[- ]time password|6 digit login code)\b", re.I),
        ]
        return contains_any(text, suspicious_patterns)

    def detect_promo(self, text: str, message: Dict[str, str]) -> bool:
        promo_patterns = [
            re.compile(r"\b(50% off|discount|offer|unsubscribe|reply stop|opt out|marketing|travel deal|itinerary|welcome|limited time|deal|sale|selling|for sale|pickup|dm if interested|buy|price|saved items|current balance|offer details|new here|saved deal|drop something|t&c)\b", re.I),
            re.compile(r"\b(for sale|selling|pickup|dm|interested|price|available|bought|used|curated|itinerary|package details)\b", re.I),
        ]
        return contains_any(text, promo_patterns)

    def detect_urgent(self, text: str, message: Dict[str, str], history: List[Dict[str, str]]) -> bool:
        if re.search(r"\b(nothing urgent|no hurry|no pressure|not urgent|no need to respond|no need to reply|no rush)\b", text, re.I):
            return False
        urgent_patterns = [
            re.compile(r"\b(quick heads-up|heads-up|time-sensitive|deadline|eod|immediately|urgent|quick help|call me now|came online now|incident|bridge|rollback|deploy|review|escalation|alert|final reminder|in 20 minutes|20 mins|max|this evening|closing soon|close|submit|need to close|open now|reply once|reply now|before .*pm|before .*am|please bring|keep your phone nearby)\b", re.I),
            re.compile(r"\b(must|required|need|update|heads-up|quick|immediately|call|submit)\b", re.I),
        ]
        if contains_any(text, urgent_patterns):
            return True
        return False

    def route(self, message: Dict[str, str]) -> Tuple[str, str, str, float, str]:
        text = normalize(message.get("message_text", ""))
        history = self.get_history_for_message(message)
        evidence = self.pick_evidence(message)

        if not text and message.get("media_type") == "voice":
            if message.get("conversation_type") == "business":
                return "mute", "spam", "The business voice note is low-value and does not show a clear reason to interrupt the user.", 0.81, evidence
            return "digest", "personal", "The voice note appears low urgency and does not show risk or a direct action request.", 0.79, evidence

        if self.detect_scam(text, message, history):
            return "mute", "scam", "The message uses account, OTP, or verification pressure and looks risky.", 0.9, evidence

        if message.get("conversation_type") == "business":
            business = self.get_business(message.get("business_id", ""))
            user_business = self.get_user_business(message["user_id"], message.get("business_id", ""))
            if user_business and any(w in text for w in ["appointment", "prescription", "claim", "pickup", "booking", "reminder"]):
                return "notify", "event", "A verified business is sending a relevant reminder tied to the user's known activity.", 0.9, evidence
            if self.detect_promo(text, message):
                if re.search(r"\b(50% off|discount|offer|limited time|try50|welcome! get|t&c|new here)\b", text, re.I) and re.search(r"\b(reply stop|unsubscribe|opt out)\b", text, re.I):
                    return "mute", "promotion", "The marketing message uses a high-frequency sales pattern and the user has opted out or is likely to ignore it.", 0.84, evidence
                if re.search(r"\b(reply stop|unsubscribe|opt out)\b", text, re.I):
                    return "digest", "promotion", "The message is promotional but not urgent enough to interrupt the user.", 0.79, evidence
                if any(self.get_event(message["user_id"], row.get("message_id", "")) and (self.get_event(message["user_id"], row.get("message_id", "")) .get("notification_dismissed") == "1" or self.get_event(message["user_id"], row.get("message_id", "")) .get("muted_after_message") == "1" or self.get_event(message["user_id"], row.get("message_id", "")) .get("message_reported") == "1") for row in history):
                    return "mute", "promotion", "Similar historical messages were ignored, dismissed, or muted by this user.", 0.85, evidence
                return "digest", "promotion", "The message is promotional but not urgent enough to interrupt the user.", 0.79, evidence
            if business and business.get("verified") == "1":
                if user_business and (user_business.get("activity_count_180d") not in {"", "0"} or user_business.get("messages_opened_30d") not in {"", "0"}):
                    if self.detect_urgent(text, message, history) or any(w in text for w in ["order", "delivery", "booking", "appointment", "claim", "refund", "payment", "pickup", "account"]):
                        message_type = "event" if any(w in text for w in ["appointment", "prescription", "claim", "booking", "reminder"]) else "business_update"
                        return "notify", message_type, "A verified business is sending a relevant update tied to the user's recent interaction history.", 0.91, evidence
                return "digest", "business_update", "The verified business message is legitimate but not urgent enough for interruption.", 0.8, evidence
            return "digest", "business_update", "The business message is informational and can be deferred.", 0.75, evidence

        if message.get("conversation_type") == "group":
            group_id = message.get("group_id", "")
            member = self.get_group_member(group_id, message["user_id"])
            if any(k in text for k in ["prod review", "queue numbers", "failed-payment", "client note", "eod", "incident bridge", "rollback", "deployment notes", "incident summary", "escalation", "review"]) and not self.detect_scam(text, message, history):
                return "notify", "urgent", "The message is a work-related deadline or dependency that should interrupt the user.", 0.88, evidence
            if re.search(r"@\w+", text):
                return "notify", "personal", "The sender directly addresses this user and asks for a response or action.", 0.87, evidence
            if any(k in text for k in ["school", "circular", "consent", "route", "bus", "field trip", "faculty", "pickup", "supply", "water", "plumber", "tanker", "valve", "maintenance", "incident", "bridge", "deploy", "rollback", "review", "client", "eod", "deadline", "final reminder", "today"]) and not self.detect_scam(text, message, history):
                return "notify", "event", "A school or operational update should interrupt the user because it is time-sensitive.", 0.87, evidence
            if any(k in text for k in ["cultural night", "form", "sheet", "flat no", "dish", "item", "next sunday", "whenever you get time"]) and not self.detect_urgent(text, message, history):
                return "digest", "event", "The message is a useful group update but not urgent enough to interrupt the user.", 0.82, evidence
            if self.detect_urgent(text, message, history):
                if re.search(r"\b(quick heads-up|heads-up|time-sensitive|20 mins|max)\b", text, re.I):
                    return "notify", "urgent", "A quick heads-up or time-bound update should interrupt the user.", 0.88, evidence
                if any(k in text for k in ["school", "circular", "consent", "route", "bus", "field trip", "faculty", "pickup", "supply", "water", "plumber", "tanker", "valve", "maintenance", "incident", "bridge", "deploy", "rollback", "review", "client", "eod", "deadline", "final reminder", "today"]):
                    return "notify", "event" if any(k in text for k in ["school", "circular", "consent", "route", "bus", "field trip", "faculty", "pickup", "supply", "water", "teacher", "parents"]) else "urgent", "A time-sensitive group update needs the user's attention.", 0.88, evidence
                return "notify", "urgent", "The message is a direct request or deadline that should interrupt the user.", 0.87, evidence
            if any(k in text for k in ["good morning", "good afternoon", "hope today is peaceful", "sending good vibes", "just saying", "no need to respond", "greeting", "blessings", "warm water", "forwarding because it felt nice"]) and (int(message.get("forwarded_count", "0") or 0) >= 1 or any(k in text for k in ["forwarding", "forward"])):
                return "mute", "greeting", "The message is a low-value greeting or forwarded note that the user likely does not need interrupted.", 0.84, evidence
            if re.search(r"\b(fwd|forward|forwarding|forward to family|sharing here)\b", text, re.I):
                return "mute", "forward", "The sender is repeatedly forwarding low-value content and the user is unlikely to want it now.", 0.83, evidence
            if self.detect_promo(text, message):
                if int(message.get("forwarded_count", "0") or 0) >= 3:
                    return "mute", "forward", "The sender is repeatedly forwarding low-value content and the user is unlikely to want it now.", 0.83, evidence
                if any(self.get_event(message["user_id"], row.get("message_id", "")) and (self.get_event(message["user_id"], row.get("message_id", "")) .get("notification_dismissed") == "1" or self.get_event(message["user_id"], row.get("message_id", "")) .get("muted_after_message") == "1" or self.get_event(message["user_id"], row.get("message_id", "")) .get("message_reported") == "1") for row in history):
                    return "mute", "promotion", "Similar historical messages were ignored, dismissed, or muted by this user.", 0.85, evidence
                return "digest", "promotion", "The message is potentially relevant but not urgent enough to interrupt the user.", 0.8, evidence
            if any(k in text for k in ["good morning", "good afternoon", "hope today is peaceful", "sending good vibes", "just saying", "no need to respond", "greeting", "blessings", "warm water", "forwarding because it felt nice"]) and (int(message.get("forwarded_count", "0") or 0) >= 1 or any(k in text for k in ["forwarding", "forward"])):
                return "mute", "greeting", "The message is a low-value greeting or forwarded note that the user likely does not need interrupted.", 0.84, evidence
            if any(k in text for k in ["good morning", "good afternoon", "hope today is peaceful", "sending good vibes", "just saying", "no need to respond", "greeting", "blessings", "warm water"]) and int(message.get("forwarded_count", "0") or 0) < 1:
                return "digest", "greeting", "The message is a harmless greeting that can be read later.", 0.8, evidence
            return "digest", "personal", "The group message is harmless and can be read later.", 0.79, evidence

        if self.detect_urgent(text, message, history):
            return "notify", "urgent", "The sender is asking for a direct action or response now.", 0.85, evidence

        if self.detect_promo(text, message):
            if re.search(r"\b(reply stop|unsubscribe|opt out)\b", text, re.I):
                return "digest", "promotion", "The message is promotional but not urgent enough to interrupt the user.", 0.78, evidence
            return "digest", "promotion", "The message is promotional and can be deferred.", 0.78, evidence

        if any(k in text for k in ["good morning", "good afternoon", "hope today is peaceful", "sending good vibes", "just saying", "no need to respond", "greeting", "blessings", "warm water"]) and int(message.get("forwarded_count", "0") or 0) >= 1:
            return "mute", "greeting", "The message is a low-value greeting or repeated forward.", 0.8, evidence
        if any(k in text for k in ["good morning", "good afternoon", "hope today is peaceful", "sending good vibes", "just saying", "no need to respond", "greeting", "blessings", "warm water"]):
            return "digest", "greeting", "The message is a harmless greeting that can be read later.", 0.8, evidence

        if message.get("conversation_type") == "personal":
            return "digest", "personal", "The message is a low-stakes personal note and does not show urgency or risk.", 0.74, evidence

        return "digest", "personal", "The message appears harmless and can be processed later.", 0.74, evidence


def write_predictions(rows: List[Tuple[str, str, str, str, float, str]]) -> None:
    output_path = DATA_DIR / "output.csv"
    root_output = ROOT / "output.csv"
    header = ["message_id", "action", "message_type", "reason", "confidence", "evidence_message_ids"]
    for path in [output_path, root_output]:
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            for row in rows:
                writer.writerow([row[0], row[1], row[2], row[3], f"{row[4]:.2f}", row[5]])


def main() -> None:
    router = Router()
    predictions: List[Tuple[str, str, str, str, float, str]] = []
    for message in router.messages:
        action, message_type, reason, confidence, evidence = router.route(message)
        predictions.append((message["message_id"], action, message_type, reason, confidence, evidence))
    write_predictions(predictions)


if __name__ == "__main__":
    main()
