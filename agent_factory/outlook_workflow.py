"""Helpers that connect Outlook mailbox content with specialist agent behavior."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .specialist_agent import SpecialistAgent


def message_to_model_input(message: Dict[str, Any]) -> str:
    sender = message.get("from", {}).get("emailAddress", {})
    sender_name = sender.get("name", "")
    sender_email = sender.get("address", "")
    subject = message.get("subject", "")
    preview = message.get("bodyPreview", "")
    return (
        f"From Name: {sender_name}\n"
        f"From Email: {sender_email}\n"
        f"Subject: {subject}\n"
        f"Preview: {preview}"
    )


def classify_message(agent: SpecialistAgent, message: Dict[str, Any]) -> Dict[str, Any]:
    model_input = message_to_model_input(message)
    prediction = agent.predict(model_input)
    return {
        "message_id": message.get("id"),
        "subject": message.get("subject"),
        "receivedDateTime": message.get("receivedDateTime"),
        "prediction": prediction.get("prediction"),
        "top_classes": prediction.get("top_classes", []),
        "web_link": message.get("webLink"),
    }


def suggest_reply_body(agent: SpecialistAgent, message: Dict[str, Any]) -> Tuple[str, str]:
    classification = classify_message(agent, message)
    label = str(classification.get("prediction", "draft_reply"))
    subject = message.get("subject", "your email")

    if label == "schedule_meeting":
        body = (
            "Thanks for your email.\n\n"
            f"I saw your request regarding '{subject}'. "
            "I can meet and will send calendar options shortly.\n\n"
            "Best regards,"
        )
    elif label == "flag_follow_up":
        body = (
            "Thanks for the note.\n\n"
            f"I reviewed your message about '{subject}' and this needs follow-up. "
            "I will respond with the next step and timing soon.\n\n"
            "Best regards,"
        )
    elif label == "archive":
        body = (
            "Thanks for sharing this update.\n\n"
            "No immediate action is required on my side at this time.\n\n"
            "Best regards,"
        )
    elif label == "unsubscribe":
        body = (
            "Hello,\n\n"
            "Please remove me from future marketing distribution for this list.\n\n"
            "Thank you."
        )
    else:
        body = (
            "Thanks for reaching out.\n\n"
            f"I received your email regarding '{subject}' and will follow up with a full response shortly.\n\n"
            "Best regards,"
        )

    return label, body


def triage_messages(agent: SpecialistAgent, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [classify_message(agent, message) for message in messages]
