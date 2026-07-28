from app.core.config import settings
from app.services.voice_narration import _clean_text


def test_clean_text_removes_markdown_and_collapses_space():
    assert _clean_text('  **Yakın gelecek**\n\n# Mesaj  ') == 'Yakın gelecek Mesaj'


def test_default_turkish_hd_voice_is_configured():
    assert settings.google_tts_language_code == 'tr-TR'
    assert settings.google_tts_voice_name.startswith('tr-TR-Chirp3-HD-')

from app.schemas.fortune import FortuneFeedbackRequest


def test_ai_content_report_status_is_accepted():
    model = FortuneFeedbackRequest(status='reported', note='Uygunsuz içerik')
    assert model.status == 'reported'
