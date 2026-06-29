from telethon import events

from handlers.cancel import cancel_handler
from handlers.mirror import mirror_handler
from handlers.start import help_handler, start_handler
from handlers.stats import stats_handler, status_handler


def register_handlers(client):
    """Registers all callback handlers on the Telethon Client."""
    # Command handlers
    client.add_event_handler(start_handler, events.NewMessage(pattern=r'^/start$'))
    client.add_event_handler(help_handler, events.NewMessage(pattern=r'^/help$'))
    client.add_event_handler(stats_handler, events.NewMessage(pattern=r'^/stats$'))
    client.add_event_handler(status_handler, events.NewMessage(pattern=r'^/status$'))
    client.add_event_handler(cancel_handler, events.NewMessage(pattern=r'^/cancel'))
    
    # Generic message mirror handler
    client.add_event_handler(mirror_handler, events.NewMessage)
