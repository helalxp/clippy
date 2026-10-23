import burned_subtitles
from burned_subtitles import band_top, crop_filter


class TestBandTop:
    def test_subtitled_show_gives_a_band_above_the_highest_line(self):
        # Two-line subtitles at 0.84, one-line at 0.90, silent frames between.
        answers = [0.84, None, 0.90, 0.84, None, 0.90, None, 0.84, None, None]
        assert band_top(answers) == 0.82

    def test_too_few_frames_with_text_is_no_track(self):
        answers = [0.85, None, None, None, None, None, None, None, None, None]
        assert band_top(answers) is None

    def test_text_high_in_the_frame_is_not_a_subtitle_track(self):
        # Kinetic titles across the middle of an edited intro: trimming there
        # would cut away a third of the picture.
        answers = [0.45, 0.50, 0.55, 0.48, 0.52, 0.47]
        assert band_top(answers) is None

    def test_one_stray_high_reading_is_ignored(self):
        answers = [0.30, 0.86, 0.86, 0.87, 0.86]
        assert band_top(answers) == 0.84

    def test_a_sliver_at_the_very_bottom_is_not_worth_a_reencode(self):
        assert band_top([0.995, 0.995, 0.995]) is None

    def test_garbage_and_empty_answers(self):
        assert band_top([]) is None
        assert band_top(["x", None, 2.0, -1]) is None


def test_crop_keeps_the_top_with_an_even_height():
    assert crop_filter(0.792) == "crop=iw:trunc(ih*0.7920/2)*2:0:0"


def test_disabled_or_keyless_check_never_calls_out(monkeypatch):
    monkeypatch.setattr(burned_subtitles, "ENABLED", False)
    assert burned_subtitles.detect("v.mp4") is None
    monkeypatch.setattr(burned_subtitles, "ENABLED", True)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert burned_subtitles.detect("v.mp4") is None
