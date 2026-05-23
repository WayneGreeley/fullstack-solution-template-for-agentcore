"""
Unit tests for Nova Analyzer Lambda function.

Tests core functionality including pattern detection, similarity computation,
and segment classification.
"""

import unittest
from unittest.mock import Mock

# Import functions to test
from nova_analyzer import (
    FluffDetection,
    FluffType,
    classify_segments,
    compute_semantic_similarity,
    detect_fluff_patterns,
)


class TestComputeSemanticSimilarity(unittest.TestCase):
    """Tests for semantic similarity computation."""

    def test_identical_embeddings_return_one(self):
        """
        Given two identical embeddings
        When computing semantic similarity
        Then the result should be 1.0
        """
        embedding = [0.5] * 1024
        similarity = compute_semantic_similarity(embedding, embedding)
        self.assertAlmostEqual(similarity, 1.0, places=5)

    def test_orthogonal_embeddings_return_half(self):
        """
        Given two orthogonal embeddings
        When computing semantic similarity
        Then the result should be approximately 0.5
        """
        embedding1 = [1.0] + [0.0] * 1023
        embedding2 = [0.0] + [1.0] + [0.0] * 1022
        similarity = compute_semantic_similarity(embedding1, embedding2)
        self.assertAlmostEqual(similarity, 0.5, places=5)

    def test_opposite_embeddings_return_zero(self):
        """
        Given two opposite embeddings
        When computing semantic similarity
        Then the result should be approximately 0.0
        """
        embedding1 = [1.0] * 1024
        embedding2 = [-1.0] * 1024
        similarity = compute_semantic_similarity(embedding1, embedding2)
        self.assertAlmostEqual(similarity, 0.0, places=5)

    def test_zero_norm_embeddings_return_zero(self):
        """
        Given embeddings with zero norm
        When computing semantic similarity
        Then the result should be 0.0
        """
        embedding1 = [0.0] * 1024
        embedding2 = [1.0] * 1024
        similarity = compute_semantic_similarity(embedding1, embedding2)
        self.assertEqual(similarity, 0.0)


class TestDetectFluffPatterns(unittest.TestCase):
    """Tests for fluff pattern detection."""

    def test_detect_cta_pattern(self):
        """
        Given a transcript segment with "like and subscribe"
        When detecting fluff patterns
        Then a CTA detection should be returned
        """
        segments = [
            {
                "text": "Please like and subscribe to my channel",
                "start_time": 10.0,
                "end_time": 15.0,
            }
        ]
        detections = detect_fluff_patterns(segments)

        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].pattern_type, "CTA")
        self.assertEqual(detections[0].start_time, 10.0)
        self.assertEqual(detections[0].end_time, 15.0)
        self.assertGreater(detections[0].confidence, 0.8)

    def test_detect_ad_pattern(self):
        """
        Given a transcript segment with "promo code"
        When detecting fluff patterns
        Then an AD detection should be returned
        """
        segments = [
            {
                "text": "Use promo code SAVE20 for a discount",
                "start_time": 20.0,
                "end_time": 25.0,
            }
        ]
        detections = detect_fluff_patterns(segments)

        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].pattern_type, "AD")
        self.assertIn("promo code", detections[0].matched_text.lower())

    def test_detect_intro_pattern(self):
        """
        Given a transcript segment with "hey guys"
        When detecting fluff patterns
        Then an INTRO detection should be returned
        """
        segments = [
            {
                "text": "Hey guys, welcome back to my channel",
                "start_time": 0.0,
                "end_time": 3.0,
            }
        ]
        detections = detect_fluff_patterns(segments)

        self.assertEqual(len(detections), 2)  # "hey guys" and "welcome back"
        pattern_types = {d.pattern_type for d in detections}
        self.assertIn("INTRO", pattern_types)

    def test_detect_outro_pattern(self):
        """
        Given a transcript segment with "thanks for watching"
        When detecting fluff patterns
        Then an OUTRO detection should be returned
        """
        segments = [
            {
                "text": "Thanks for watching, see you next time",
                "start_time": 300.0,
                "end_time": 305.0,
            }
        ]
        detections = detect_fluff_patterns(segments)

        self.assertGreater(len(detections), 0)
        pattern_types = {d.pattern_type for d in detections}
        self.assertIn("OUTRO", pattern_types)

    def test_no_patterns_in_clean_text(self):
        """
        Given a transcript segment with no fluff patterns
        When detecting fluff patterns
        Then no detections should be returned
        """
        segments = [
            {
                "text": "This is the main content about machine learning",
                "start_time": 50.0,
                "end_time": 55.0,
            }
        ]
        detections = detect_fluff_patterns(segments)

        self.assertEqual(len(detections), 0)

    def test_multiple_patterns_in_one_segment(self):
        """
        Given a transcript segment with multiple fluff patterns
        When detecting fluff patterns
        Then multiple detections should be returned
        """
        segments = [
            {
                "text": "Like and subscribe, and use promo code SAVE20",
                "start_time": 10.0,
                "end_time": 15.0,
            }
        ]
        detections = detect_fluff_patterns(segments)

        self.assertGreater(len(detections), 1)
        pattern_types = {d.pattern_type for d in detections}
        self.assertIn("CTA", pattern_types)
        self.assertIn("AD", pattern_types)


class TestClassifySegments(unittest.TestCase):
    """Tests for segment classification."""

    def test_classify_segment_with_cta_pattern(self):
        """
        Given a segment with CTA pattern detection
        When classifying segments
        Then the segment should be classified as fluff with CTA type
        """
        segments = [
            {"text": "Like and subscribe", "start_time": 10.0, "end_time": 15.0}
        ]
        embeddings = [Mock(embedding_vector=[0.5] * 1024)]
        relevance_scores = [0.8]
        pattern_detections = [
            FluffDetection(
                pattern_type="CTA",
                start_time=10.0,
                end_time=15.0,
                confidence=0.9,
                matched_text="like and subscribe",
            )
        ]
        silence_periods = []
        main_topic = "Machine learning tutorial"

        classifications = classify_segments(
            segments=segments,
            embeddings=embeddings,
            relevance_scores=relevance_scores,
            pattern_detections=pattern_detections,
            silence_periods=silence_periods,
            main_topic=main_topic,
        )

        self.assertEqual(len(classifications), 1)
        self.assertTrue(classifications[0].is_fluff)
        self.assertEqual(classifications[0].fluff_type, "CTA")
        self.assertGreater(classifications[0].confidence, 0.8)

    def test_classify_segment_with_low_relevance(self):
        """
        Given a segment with low relevance score (<0.4)
        When classifying segments
        Then the segment should be classified as tangent
        """
        segments = [
            {"text": "Random off-topic content", "start_time": 50.0, "end_time": 55.0}
        ]
        embeddings = [Mock(embedding_vector=[0.5] * 1024)]
        relevance_scores = [0.2]  # Low relevance
        pattern_detections = []
        silence_periods = []
        main_topic = "Machine learning tutorial"

        classifications = classify_segments(
            segments=segments,
            embeddings=embeddings,
            relevance_scores=relevance_scores,
            pattern_detections=pattern_detections,
            silence_periods=silence_periods,
            main_topic=main_topic,
        )

        self.assertEqual(len(classifications), 1)
        self.assertTrue(classifications[0].is_fluff)
        self.assertEqual(classifications[0].fluff_type, FluffType.TANGENT.value)

    def test_classify_segment_with_silence(self):
        """
        Given a segment overlapping with silence period
        When classifying segments
        Then the segment should be classified as silence fluff
        """
        segments = [{"text": "", "start_time": 100.0, "end_time": 105.0}]
        embeddings = [Mock(embedding_vector=[0.5] * 1024)]
        relevance_scores = [0.5]
        pattern_detections = []
        silence_periods = [(100.0, 105.0)]  # Overlaps with segment
        main_topic = "Machine learning tutorial"

        classifications = classify_segments(
            segments=segments,
            embeddings=embeddings,
            relevance_scores=relevance_scores,
            pattern_detections=pattern_detections,
            silence_periods=silence_periods,
            main_topic=main_topic,
        )

        self.assertEqual(len(classifications), 1)
        self.assertTrue(classifications[0].is_fluff)
        self.assertEqual(classifications[0].fluff_type, FluffType.SILENCE.value)

    def test_classify_relevant_segment_as_keep(self):
        """
        Given a segment with high relevance and no fluff patterns
        When classifying segments
        Then the segment should be classified as keep (not fluff)
        """
        segments = [
            {
                "text": "Neural networks are composed of layers",
                "start_time": 50.0,
                "end_time": 55.0,
            }
        ]
        embeddings = [Mock(embedding_vector=[0.5] * 1024)]
        relevance_scores = [0.9]  # High relevance
        pattern_detections = []
        silence_periods = []
        main_topic = "Machine learning tutorial"

        classifications = classify_segments(
            segments=segments,
            embeddings=embeddings,
            relevance_scores=relevance_scores,
            pattern_detections=pattern_detections,
            silence_periods=silence_periods,
            main_topic=main_topic,
        )

        self.assertEqual(len(classifications), 1)
        self.assertFalse(classifications[0].is_fluff)
        self.assertIsNone(classifications[0].fluff_type)
        self.assertGreater(classifications[0].relevance_score, 0.8)


if __name__ == "__main__":
    unittest.main()
