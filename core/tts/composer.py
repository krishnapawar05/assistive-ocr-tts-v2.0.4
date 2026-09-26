"""SpeechComposer: turns accepted text into what is spoken."""
from typing import Optional


class SpeechComposer:
    def __init__(self, max_chars: int):
        self.max_chars = int(max_chars)

    def compose(self, text: str) -> Optional[str]:
        """Return the utterance, or None if there is nothing to say.

        Long text is cut at a word boundary so a full board does not block speech for minutes.
        """
        text = (text or "").strip()
        if not text:
            return None
        if len(text) <= self.max_chars:
            return text
        cut = text[: self.max_chars]
        space = cut.rfind(" ")
        return (cut[:space] if space > self.max_chars // 2 else cut).rstrip()
