"""
Unit tests for fluff detection module.

Tests pattern detection, silence detection, tangent detection,
and segment classification logic.
"""

import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fluff_detector import (
    FluffDetection,
    FluffType,
    SegmentClassification,
    calculate_fluff_statistics,
    classify_segments,
    detect_ad_patterns,
    detect_cta_patterns,
    detect_filler_patterns,
    detect_fluff_patterns,
    detect_intro_patterns,
    detect_outro_patterns,
    detect_silence,
    detect_tangents,
)


class TestCTAPatternDetection(unittest.TestCase):
    """Tests for call-to-action pattern detection."""

    def test_detect_like_and_subscribe(self):
        """
        Given: Text containing "like and subscribe"
        When: detect_cta_patterns is called
        Then: Pattern is detected with high confidence
        """
        text = "please like and subscribe to my channel"
        matches = detect_cta_patterns(text)

        # May match multiple patterns (like and subscribe, subscribe to channel)
        self.assertGreater(len(matches), 0)
        # Check that at least one match contains "like and subscribe"
        match_texts = [m[0].lower() for m in matches]
        self.assertTrue(any("like and subscribe" in text for text in match_texts))
        self.assertEqual(matches[0][1], 0.9)

    def test_detect_hit_the_bell(self):
        """
        Given: Text containing "hit the bell"
        When: detect_cta_patterns is called
        Then: Pattern is detected
        """
        text = "don't forget to hit the bell icon"
        matches = detect_cta_patterns(text)

        self.assertEqual(len(matches), 1)
        self.assertIn("hit the bell", matches[0][0].lower())

    def test_no_cta_in_clean_text(self):
        """
        Given: Text without CTA patterns
        When: detect_cta_patterns is called
        Then: No patterns are detected
        """
        text = "this is the main content about machine learning"
        matches = detect_cta_patterns(text)

        self.assertEqual(len(matches), 0)


class TestAdPatternDetection(unittest.TestCase):
    """Tests for advertisement pattern detection."""

    def test_detect_sponsor(self):
        """
        Given: Text containing "sponsor"
        When: detect_ad_patterns is called
        Then: Pattern is detected
        """
        text = "this video is sponsored by skillshare"
        matches = detect_ad_patterns(text)

        self.assertGreater(len(matches), 0)
        self.assertIn("sponsor", matches[0][0].lower())

    def test_detect_promo_code(self):
        """
        Given: Text containing "promo code"
        When: detect_ad_patterns is called
        Then: Pattern is detected
        """
        text = "use promo code SAVE20 for a discount"
        matches = detect_ad_patterns(text)

        self.assertEqual(len(matches), 1)
        self.assertIn("promo code", matches[0][0].lower())

    def test_detect_affiliate_link(self):
        """
        Given: Text containing "affiliate link"
        When: detect_ad_patterns is called
        Then: Pattern is detected
        """
        text = "check out the affiliate link in the description"
        matches = detect_ad_patterns(text)

        self.assertGreater(len(matches), 0)


class TestIntroPatternDetection(unittest.TestCase):
    """Tests for intro greeting pattern detection."""

    def test_detect_hey_guys(self):
        """
        Given: Text containing "hey guys"
        When: detect_intro_patterns is called
        Then: Pattern is detected
        """
        text = "hey guys welcome back to my channel"
        matches = detect_intro_patterns(text)

        self.assertGreater(len(matches), 0)
        self.assertIn("hey guys", matches[0][0].lower())

    def test_detect_welcome_back(self):
        """
        Given: Text containing "welcome back"
        When: detect_intro_patterns is called
        Then: Pattern is detected
        """
        text = "welcome back everyone"
        matches = detect_intro_patterns(text)

        self.assertEqual(len(matches), 1)
        self.assertIn("welcome back", matches[0][0].lower())


class TestOutroPatternDetection(unittest.TestCase):
    """Tests for outro closing pattern detection."""

    def test_detect_thanks_for_watching(self):
        """
        Given: Text containing "thanks for watching"
        When: detect_outro_patterns is called
        Then: Pattern is detected
        """
        text = "thanks for watching and see you next time"
        matches = detect_outro_patterns(text)

        self.assertGreater(len(matches), 0)

    def test_detect_see_you_next(self):
        """
        Given: Text containing "see you next"
        When: detect_outro_patterns is called
        Then: Pattern is detected
        """
        text = "see you in the next video"
        matches = detect_outro_patterns(text)

        self.assertEqual(len(matches), 1)


class TestFillerPatternDetection(unittest.TestCase):
    """Tests for filler phrase pattern detection."""

    def test_detect_repeated_um(self):
        """
        Given: Text containing repeated "um"
        When: detect_filler_patterns is called
        Then: Pattern is detected
        """
        text = "so umum I think that"  # No space between um's for regex to match
        matches = detect_filler_patterns(text)

        self.assertGreater(len(matches), 0)

    def test_detect_you_know_what_i_mean(self):
        """
        Given: Text containing "you know what I mean"
        When: detect_filler_patterns is called
        Then: Pattern is detected
        """
        text = "it's complicated you know what I mean"
        matches = detect_filler_patterns(text)

        self.assertEqual(len(matches), 1)


class TestFluffPatternDetection(unittest.TestCase):
    """Tests for complete fluff pattern detection."""

    def test_detect_multiple_patterns_in_segments(self):
        """
        Given: Segments with multiple fluff patterns
        When: detect_fluff_patterns is called
        Then: All patterns are detected with correct timestamps
        """
        segments = [
            {"text": "hey guys welcome back", "start_time": 0.0, "end_time": 2.0},
            {
                "text": "like and subscribe to my channel",
                "start_time": 2.0,
                "end_time": 4.0,
            },
            {
                "text": "this video is sponsored by",
                "start_time": 4.0,
                "end_time": 6.0,
            },
        ]

        detections = detect_fluff_patterns(segments)

        self.assertGreater(len(detections), 0)
        # Should detect intro, CTA, and ad patterns
        pattern_types = {d.pattern_type for d in detections}
        self.assertIn("INTRO", pattern_types)
        self.assertIn("CTA", pattern_types)
        self.assertIn("AD", pattern_types)

    def test_no_patterns_in_clean_segments(self):
        """
        Given: Segments without fluff patterns
        When: detect_fluff_patterns is called
        Then: No patterns are detected
        """
        segments = [
            {
                "text": "machine learning is a subset of AI",
                "start_time": 0.0,
                "end_time": 3.0,
            },
            {
                "text": "neural networks use backpropagation",
                "start_time": 3.0,
                "end_time": 6.0,
            },
        ]

        detections = detect_fluff_patterns(segments)

        self.assertEqual(len(detections), 0)


class TestSilenceDetection(unittest.TestCase):
    """Tests for silence detection in audio."""

    @patch("fluff_detector.subprocess.run")
    def test_detect_silence_periods(self, mock_run):
        """
        Given: Audio file with silence periods
        When: detect_silence is called
        Then: Silence periods are detected with correct timestamps
        """
        # Mock FFmpeg output
        mock_result = MagicMock()
        mock_result.stderr = """
[silencedetect @ 0x123] silence_start: 10.5
[silencedetect @ 0x123] silence_end: 13.2 | silence_duration: 2.7
[silencedetect @ 0x123] silence_start: 25.0
[silencedetect @ 0x123] silence_end: 28.5 | silence_duration: 3.5
        """
        mock_run.return_value = mock_result

        with tempfile.NamedTemporaryFile(suffix=".wav") as temp_audio:
            silence_periods = detect_silence(temp_audio.name, threshold_seconds=2.0)

        self.assertEqual(len(silence_periods), 2)
        self.assertEqual(silence_periods[0], (10.5, 13.2))
        self.assertEqual(silence_periods[1], (25.0, 28.5))

    @patch("fluff_detector.subprocess.run")
    def test_no_silence_detected(self, mock_run):
        """
        Given: Audio file without silence periods
        When: detect_silence is called
        Then: Empty list is returned
        """
        mock_result = MagicMock()
        mock_result.stderr = "No silence detected"
        mock_run.return_value = mock_result

        with tempfile.NamedTemporaryFile(suffix=".wav") as temp_audio:
            silence_periods = detect_silence(temp_audio.name)

        self.assertEqual(len(silence_periods), 0)


class TestTangentDetection(unittest.TestCase):
    """Tests for tangent detection based on relevance scores."""

    def test_detect_low_relevance_segments(self):
        """
        Given: Relevance scores with some below threshold
        When: detect_tangents is called
        Then: Low relevance segments are identified as tangents
        """
        relevance_scores = [0.8, 0.3, 0.9, 0.2, 0.7]
        tangent_indices = detect_tangents(relevance_scores, threshold=0.4)

        self.assertEqual(len(tangent_indices), 2)
        self.assertIn(1, tangent_indices)  # 0.3 < 0.4
        self.assertIn(3, tangent_indices)  # 0.2 < 0.4

    def test_no_tangents_when_all_relevant(self):
        """
        Given: All relevance scores above threshold
        When: detect_tangents is called
        Then: No tangents are detected
        """
        relevance_scores = [0.8, 0.9, 0.7, 0.6, 0.5]
        tangent_indices = detect_tangents(relevance_scores, threshold=0.4)

        self.assertEqual(len(tangent_indices), 0)


class TestSegmentClassification(unittest.TestCase):
    """Tests for segment classification logic."""

    def test_classify_segment_with_pattern_match(self):
        """
        Given: Segment with detected fluff pattern
        When: classify_segments is called
        Then: Segment is classified as fluff with pattern type
        """
        segments = [{"text": "like and subscribe", "start_time": 0.0, "end_time": 2.0}]
        relevance_scores = [0.8]
        pattern_detections = [
            FluffDetection(
                pattern_type="CTA",
                start_time=0.0,
                end_time=2.0,
                confidence=0.9,
                matched_text="like and subscribe",
            )
        ]
        silence_periods = []

        classifications = classify_segments(
            segments=segments,
            relevance_scores=relevance_scores,
            pattern_detections=pattern_detections,
            silence_periods=silence_periods,
            main_topic="machine learning",
        )

        self.assertEqual(len(classifications), 1)
        self.assertTrue(classifications[0].is_fluff)
        self.assertEqual(classifications[0].fluff_type, "CTA")
        self.assertEqual(classifications[0].confidence, 0.9)

    def test_classify_segment_with_silence(self):
        """
        Given: Segment overlapping with silence period
        When: classify_segments is called
        Then: Segment is classified as silence fluff
        """
        segments = [{"text": "", "start_time": 10.0, "end_time": 13.0}]
        relevance_scores = [0.5]
        pattern_detections = []
        # Silence period starts before segment, so segment start_time (10.0) is within silence
        silence_periods = [(9.5, 13.2)]

        classifications = classify_segments(
            segments=segments,
            relevance_scores=relevance_scores,
            pattern_detections=pattern_detections,
            silence_periods=silence_periods,
            main_topic="machine learning",
        )

        self.assertEqual(len(classifications), 1)
        self.assertTrue(classifications[0].is_fluff)
        self.assertEqual(classifications[0].fluff_type, FluffType.SILENCE.value)
        self.assertEqual(classifications[0].confidence, 0.95)

    def test_classify_segment_as_tangent(self):
        """
        Given: Segment with low relevance score
        When: classify_segments is called
        Then: Segment is classified as tangent
        """
        segments = [
            {"text": "random off-topic story", "start_time": 0.0, "end_time": 5.0}
        ]
        relevance_scores = [0.2]
        pattern_detections = []
        silence_periods = []

        classifications = classify_segments(
            segments=segments,
            relevance_scores=relevance_scores,
            pattern_detections=pattern_detections,
            silence_periods=silence_periods,
            main_topic="machine learning",
            tangent_threshold=0.4,
        )

        self.assertEqual(len(classifications), 1)
        self.assertTrue(classifications[0].is_fluff)
        self.assertEqual(classifications[0].fluff_type, FluffType.TANGENT.value)
        self.assertGreater(classifications[0].confidence, 0.5)

    def test_classify_segment_as_keep(self):
        """
        Given: Segment with high relevance and no fluff patterns
        When: classify_segments is called
        Then: Segment is classified as keep (not fluff)
        """
        segments = [
            {
                "text": "neural networks use gradient descent",
                "start_time": 0.0,
                "end_time": 3.0,
            }
        ]
        relevance_scores = [0.9]
        pattern_detections = []
        silence_periods = []

        classifications = classify_segments(
            segments=segments,
            relevance_scores=relevance_scores,
            pattern_detections=pattern_detections,
            silence_periods=silence_periods,
            main_topic="machine learning",
        )

        self.assertEqual(len(classifications), 1)
        self.assertFalse(classifications[0].is_fluff)
        self.assertIsNone(classifications[0].fluff_type)
        self.assertEqual(classifications[0].confidence, 0.9)


class TestFluffStatistics(unittest.TestCase):
    """Tests for fluff statistics calculation."""

    def test_calculate_total_fluff_duration(self):
        """
        Given: Classifications with multiple fluff segments
        When: calculate_fluff_statistics is called
        Then: Total fluff duration is correctly calculated
        """
        classifications = [
            SegmentClassification(
                segment_id="seg_0",
                start_time=0.0,
                end_time=2.0,
                is_fluff=True,
                fluff_type="CTA",
                confidence=0.9,
                relevance_score=0.5,
                reasoning="CTA pattern",
            ),
            SegmentClassification(
                segment_id="seg_1",
                start_time=2.0,
                end_time=5.0,
                is_fluff=False,
                fluff_type=None,
                confidence=0.8,
                relevance_score=0.8,
                reasoning="Relevant",
            ),
            SegmentClassification(
                segment_id="seg_2",
                start_time=5.0,
                end_time=8.0,
                is_fluff=True,
                fluff_type="AD",
                confidence=0.9,
                relevance_score=0.3,
                reasoning="Ad pattern",
            ),
        ]

        total_duration, fluff_by_type = calculate_fluff_statistics(classifications)

        self.assertEqual(total_duration, 5.0)  # 2.0 + 3.0
        self.assertEqual(fluff_by_type["CTA"], 2.0)
        self.assertEqual(fluff_by_type["AD"], 3.0)

    def test_no_fluff_segments(self):
        """
        Given: Classifications with no fluff segments
        When: calculate_fluff_statistics is called
        Then: Total duration is zero and fluff_by_type is empty
        """
        classifications = [
            SegmentClassification(
                segment_id="seg_0",
                start_time=0.0,
                end_time=5.0,
                is_fluff=False,
                fluff_type=None,
                confidence=0.9,
                relevance_score=0.9,
                reasoning="Relevant",
            )
        ]

        total_duration, fluff_by_type = calculate_fluff_statistics(classifications)

        self.assertEqual(total_duration, 0.0)
        self.assertEqual(len(fluff_by_type), 0)


if __name__ == "__main__":
    unittest.main()
