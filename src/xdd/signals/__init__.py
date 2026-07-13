"""Signal processing: filtering, sentiment, and event formation."""

from xdd.signals.pipeline import SignalPipeline
from xdd.signals.sentiment import score_sentiment
from xdd.signals.spam_filter import ManipulationFilter

__all__ = ["SignalPipeline", "score_sentiment", "ManipulationFilter"]
