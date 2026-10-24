from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import Settings
from app.messaging.senders import Sender, build_sender
from app.services.delivery import Deliverer


def build_deliverer(
    settings: Settings, session_factory: sessionmaker[Session], sender: Sender | None = None
) -> Deliverer:
    return Deliverer(session_factory, sender or build_sender(settings), settings.max_delivery_attempts)
