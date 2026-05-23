"""
Unit tests for Video Editor Lambda function.

Tests segment selection, merging, chronological validation, and error handling.
"""

import pytest
from video_editor import (
    SegmentSelectionError,
    TimeRange,
    VideoEditError,
    VideoEncodingError,
    merge_adjacent_segments,
    select_keep_segments,
    validate_chronological_order,
)


class TestSegmentSelection:
    """Tests for keep segment selection."""

    def test_select_keep_segments_all_keep(self):
        """
        Given: Classifications with all segments marked as not fluff
        When: select_keep_segments is called
        Then: Returns all segments as keep segments
        """
        classifications = [
            {"start_time": 0.0, "end_time": 10.0, "is_fluff": False},
            {"start_time": 10.0, "end_time": 20.0, "is_fluff": False},
            {"start_time": 20.0, "end_time": 30.0, "is_fluff": False},
        ]

        keep_segments = select_keep_segments(classifications)

        assert len(keep_segments) == 3
        assert keep_segments[0].start == 0.0
        assert keep_segments[0].end == 10.0
        assert keep_segments[2].start == 20.0
        assert keep_segments[2].end == 30.0

    def test_select_keep_segments_mixed(self):
        """
        Given: Classifications with mix of fluff and keep segments
        When: select_keep_segments is called
        Then: Returns only non-fluff segments
        """
        classifications = [
            {"start_time": 0.0, "end_time": 5.0, "is_fluff": True},  # Intro
            {"start_time": 5.0, "end_time": 15.0, "is_fluff": False},  # Keep
            {"start_time": 15.0, "end_time": 20.0, "is_fluff": True},  # Ad
            {"start_time": 20.0, "end_time": 30.0, "is_fluff": False},  # Keep
        ]

        keep_segments = select_keep_segments(classifications)

        assert len(keep_segments) == 2
        assert keep_segments[0].start == 5.0
        assert keep_segments[0].end == 15.0
        assert keep_segments[1].start == 20.0
        assert keep_segments[1].end == 30.0

    def test_select_keep_segments_all_fluff(self):
        """
        Given: Classifications with all segments marked as fluff
        When: select_keep_segments is called
        Then: Raises SegmentSelectionError
        """
        classifications = [
            {"start_time": 0.0, "end_time": 10.0, "is_fluff": True},
            {"start_time": 10.0, "end_time": 20.0, "is_fluff": True},
        ]

        with pytest.raises(SegmentSelectionError, match="No keep segments found"):
            select_keep_segments(classifications)

    def test_select_keep_segments_invalid_times(self):
        """
        Given: Classifications with invalid time ranges (end <= start)
        When: select_keep_segments is called
        Then: Skips invalid segments
        """
        classifications = [
            {"start_time": 0.0, "end_time": 10.0, "is_fluff": False},
            {"start_time": 15.0, "end_time": 15.0, "is_fluff": False},  # Invalid
            {"start_time": 20.0, "end_time": 30.0, "is_fluff": False},
        ]

        keep_segments = select_keep_segments(classifications)

        assert len(keep_segments) == 2
        assert keep_segments[0].start == 0.0
        assert keep_segments[1].start == 20.0


class TestSegmentMerging:
    """Tests for adjacent segment merging."""

    def test_merge_adjacent_segments_no_gaps(self):
        """
        Given: Segments with no gaps between them
        When: merge_adjacent_segments is called
        Then: Merges all segments into one
        """
        segments = [
            TimeRange(start=0.0, end=10.0),
            TimeRange(start=10.0, end=20.0),
            TimeRange(start=20.0, end=30.0),
        ]

        merged = merge_adjacent_segments(segments, gap_threshold=1.0)

        assert len(merged) == 1
        assert merged[0].start == 0.0
        assert merged[0].end == 30.0

    def test_merge_adjacent_segments_small_gaps(self):
        """
        Given: Segments with gaps smaller than threshold
        When: merge_adjacent_segments is called
        Then: Merges segments with small gaps
        """
        segments = [
            TimeRange(start=0.0, end=10.0),
            TimeRange(start=10.5, end=20.0),  # 0.5s gap
            TimeRange(start=20.8, end=30.0),  # 0.8s gap
        ]

        merged = merge_adjacent_segments(segments, gap_threshold=1.0)

        assert len(merged) == 1
        assert merged[0].start == 0.0
        assert merged[0].end == 30.0

    def test_merge_adjacent_segments_large_gaps(self):
        """
        Given: Segments with gaps larger than threshold
        When: merge_adjacent_segments is called
        Then: Does not merge segments with large gaps
        """
        segments = [
            TimeRange(start=0.0, end=10.0),
            TimeRange(start=12.0, end=20.0),  # 2.0s gap
            TimeRange(start=25.0, end=30.0),  # 5.0s gap
        ]

        merged = merge_adjacent_segments(segments, gap_threshold=1.0)

        assert len(merged) == 3
        assert merged[0].start == 0.0
        assert merged[0].end == 10.0
        assert merged[1].start == 12.0
        assert merged[1].end == 20.0
        assert merged[2].start == 25.0
        assert merged[2].end == 30.0

    def test_merge_adjacent_segments_mixed_gaps(self):
        """
        Given: Segments with mix of small and large gaps
        When: merge_adjacent_segments is called
        Then: Merges only segments with gaps below threshold
        """
        segments = [
            TimeRange(start=0.0, end=10.0),
            TimeRange(start=10.5, end=20.0),  # 0.5s gap - merge
            TimeRange(start=25.0, end=30.0),  # 5.0s gap - don't merge
            TimeRange(start=30.8, end=40.0),  # 0.8s gap - merge
        ]

        merged = merge_adjacent_segments(segments, gap_threshold=1.0)

        assert len(merged) == 2
        assert merged[0].start == 0.0
        assert merged[0].end == 20.0
        assert merged[1].start == 25.0
        assert merged[1].end == 40.0

    def test_merge_adjacent_segments_empty_list(self):
        """
        Given: Empty list of segments
        When: merge_adjacent_segments is called
        Then: Returns empty list
        """
        segments = []
        merged = merge_adjacent_segments(segments, gap_threshold=1.0)
        assert len(merged) == 0

    def test_merge_adjacent_segments_single_segment(self):
        """
        Given: Single segment
        When: merge_adjacent_segments is called
        Then: Returns the same segment
        """
        segments = [TimeRange(start=0.0, end=10.0)]
        merged = merge_adjacent_segments(segments, gap_threshold=1.0)

        assert len(merged) == 1
        assert merged[0].start == 0.0
        assert merged[0].end == 10.0

    def test_merge_adjacent_segments_unsorted(self):
        """
        Given: Segments not in chronological order
        When: merge_adjacent_segments is called
        Then: Sorts and merges correctly
        """
        segments = [
            TimeRange(start=20.0, end=30.0),
            TimeRange(start=0.0, end=10.0),
            TimeRange(start=10.5, end=20.0),
        ]

        merged = merge_adjacent_segments(segments, gap_threshold=1.0)

        assert len(merged) == 1
        assert merged[0].start == 0.0
        assert merged[0].end == 30.0


class TestChronologicalValidation:
    """Tests for chronological order validation."""

    def test_validate_chronological_order_valid(self):
        """
        Given: Segments in chronological order
        When: validate_chronological_order is called
        Then: Returns True
        """
        segments = [
            TimeRange(start=0.0, end=10.0),
            TimeRange(start=10.0, end=20.0),
            TimeRange(start=20.0, end=30.0),
        ]

        assert validate_chronological_order(segments) is True

    def test_validate_chronological_order_with_gaps(self):
        """
        Given: Segments in chronological order with gaps
        When: validate_chronological_order is called
        Then: Returns True
        """
        segments = [
            TimeRange(start=0.0, end=10.0),
            TimeRange(start=15.0, end=20.0),
            TimeRange(start=25.0, end=30.0),
        ]

        assert validate_chronological_order(segments) is True

    def test_validate_chronological_order_overlap(self):
        """
        Given: Segments with overlapping times
        When: validate_chronological_order is called
        Then: Raises SegmentSelectionError
        """
        segments = [
            TimeRange(start=0.0, end=15.0),
            TimeRange(start=10.0, end=20.0),  # Overlaps with previous
        ]

        with pytest.raises(SegmentSelectionError, match="not in chronological order"):
            validate_chronological_order(segments)

    def test_validate_chronological_order_out_of_order(self):
        """
        Given: Segments not in chronological order
        When: validate_chronological_order is called
        Then: Raises SegmentSelectionError
        """
        segments = [
            TimeRange(start=20.0, end=30.0),
            TimeRange(start=0.0, end=10.0),  # Out of order
        ]

        with pytest.raises(SegmentSelectionError, match="not in chronological order"):
            validate_chronological_order(segments)

    def test_validate_chronological_order_single_segment(self):
        """
        Given: Single segment
        When: validate_chronological_order is called
        Then: Returns True
        """
        segments = [TimeRange(start=0.0, end=10.0)]
        assert validate_chronological_order(segments) is True

    def test_validate_chronological_order_empty_list(self):
        """
        Given: Empty list of segments
        When: validate_chronological_order is called
        Then: Returns True (vacuously true)
        """
        segments = []
        # Empty list should not raise error
        # The function will return True after the loop completes
        assert validate_chronological_order(segments) is True


class TestErrorHandling:
    """Tests for error handling edge cases."""

    def test_segment_selection_error_inheritance(self):
        """
        Given: SegmentSelectionError exception
        When: Checking exception type
        Then: Is instance of VideoEditError
        """
        error = SegmentSelectionError("test error")
        assert isinstance(error, VideoEditError)

    def test_video_encoding_error_inheritance(self):
        """
        Given: VideoEncodingError exception
        When: Checking exception type
        Then: Is instance of VideoEditError
        """
        error = VideoEncodingError("test error")
        assert isinstance(error, VideoEditError)


class TestTimeRange:
    """Tests for TimeRange dataclass."""

    def test_time_range_creation(self):
        """
        Given: Start and end times
        When: Creating TimeRange
        Then: Creates object with correct attributes
        """
        time_range = TimeRange(start=5.0, end=15.0)

        assert time_range.start == 5.0
        assert time_range.end == 15.0

    def test_time_range_duration_calculation(self):
        """
        Given: TimeRange object
        When: Calculating duration
        Then: Returns correct duration
        """
        time_range = TimeRange(start=5.0, end=15.0)
        duration = time_range.end - time_range.start

        assert duration == 10.0
