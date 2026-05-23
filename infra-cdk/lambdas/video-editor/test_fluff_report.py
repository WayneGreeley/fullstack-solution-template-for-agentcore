"""
Unit tests for fluff report generation module.

Tests removed segment generation, time metrics calculation,
and report data completeness.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from fluff_report import (
    FluffReport,
    FluffReportError,
    RemovedSegment,
    TimeMetrics,
    calculate_fluff_by_type,
    calculate_time_metrics,
    find_transcript_for_segment,
    generate_fluff_report,
    generate_removed_segments,
    load_transcript_segments,
    save_fluff_report_to_s3,
)


class TestFindTranscriptForSegment:
    """Tests for finding transcript text for time ranges."""

    def test_exact_match(self):
        """
        Given: Transcript segments with exact time match
        When: Finding transcript for segment
        Then: Returns matching transcript text
        """
        transcript_segments = [
            {"start_time": 0.0, "end_time": 5.0, "text": "Hello world"},
            {"start_time": 5.0, "end_time": 10.0, "text": "This is a test"},
        ]

        result = find_transcript_for_segment(5.0, 10.0, transcript_segments)

        assert result == "This is a test"

    def test_overlapping_segments(self):
        """
        Given: Multiple overlapping transcript segments
        When: Finding transcript for time range
        Then: Returns concatenated text from all overlapping segments
        """
        transcript_segments = [
            {"start_time": 0.0, "end_time": 5.0, "text": "First part"},
            {"start_time": 3.0, "end_time": 8.0, "text": "Second part"},
            {"start_time": 7.0, "end_time": 12.0, "text": "Third part"},
        ]

        result = find_transcript_for_segment(2.0, 9.0, transcript_segments)

        assert result == "First part Second part Third part"

    def test_no_matching_segments(self):
        """
        Given: Transcript segments that don't overlap with time range
        When: Finding transcript for segment
        Then: Returns placeholder message
        """
        transcript_segments = [
            {"start_time": 0.0, "end_time": 5.0, "text": "Hello"},
            {"start_time": 10.0, "end_time": 15.0, "text": "World"},
        ]

        result = find_transcript_for_segment(6.0, 9.0, transcript_segments)

        assert result == "[No transcript available]"


class TestGenerateRemovedSegments:
    """Tests for generating removed segments list."""

    def test_single_removed_segment(self):
        """
        Given: Classifications with one fluff segment
        When: Generating removed segments
        Then: Returns list with one RemovedSegment
        """
        classifications = [
            {
                "start_time": 0.0,
                "end_time": 5.0,
                "is_fluff": True,
                "fluff_type": "intro",
                "confidence": 0.9,
            }
        ]

        transcript_segments = [
            {"start_time": 0.0, "end_time": 5.0, "text": "Hey guys welcome back"}
        ]

        result = generate_removed_segments(classifications, transcript_segments)

        assert len(result) == 1
        assert result[0].start_time == 0.0
        assert result[0].end_time == 5.0
        assert result[0].duration == 5.0
        assert result[0].fluff_type == "intro"
        assert result[0].confidence == 0.9
        assert result[0].transcript == "Hey guys welcome back"

    def test_multiple_removed_segments(self):
        """
        Given: Classifications with multiple fluff segments
        When: Generating removed segments
        Then: Returns list with all fluff segments
        """
        classifications = [
            {
                "start_time": 0.0,
                "end_time": 5.0,
                "is_fluff": True,
                "fluff_type": "intro",
                "confidence": 0.9,
            },
            {
                "start_time": 5.0,
                "end_time": 10.0,
                "is_fluff": False,
                "fluff_type": None,
                "confidence": 0.8,
            },
            {
                "start_time": 10.0,
                "end_time": 15.0,
                "is_fluff": True,
                "fluff_type": "call_to_action",
                "confidence": 0.95,
            },
        ]

        transcript_segments = [
            {"start_time": 0.0, "end_time": 5.0, "text": "Hey guys"},
            {"start_time": 5.0, "end_time": 10.0, "text": "Content here"},
            {"start_time": 10.0, "end_time": 15.0, "text": "Like and subscribe"},
        ]

        result = generate_removed_segments(classifications, transcript_segments)

        assert len(result) == 2
        assert result[0].fluff_type == "intro"
        assert result[1].fluff_type == "call_to_action"

    def test_no_removed_segments(self):
        """
        Given: Classifications with no fluff segments
        When: Generating removed segments
        Then: Returns empty list
        """
        classifications = [
            {
                "start_time": 0.0,
                "end_time": 10.0,
                "is_fluff": False,
                "fluff_type": None,
                "confidence": 0.8,
            }
        ]

        transcript_segments = [
            {"start_time": 0.0, "end_time": 10.0, "text": "Good content"}
        ]

        result = generate_removed_segments(classifications, transcript_segments)

        assert len(result) == 0


class TestCalculateTimeMetrics:
    """Tests for time metrics calculation."""

    def test_time_saved_calculation(self):
        """
        Given: Original and edited durations
        When: Calculating time metrics
        Then: Time saved equals original minus edited
        """
        result = calculate_time_metrics(original_duration=100.0, edited_duration=70.0)

        assert result.original_duration == 100.0
        assert result.edited_duration == 70.0
        assert result.time_saved == 30.0

    def test_retention_percentage_calculation(self):
        """
        Given: Original and edited durations
        When: Calculating time metrics
        Then: Retention percentage equals (edited / original) * 100
        """
        result = calculate_time_metrics(original_duration=100.0, edited_duration=75.0)

        assert result.retention_percentage == 75.0

    def test_zero_original_duration(self):
        """
        Given: Zero original duration (edge case)
        When: Calculating time metrics
        Then: Retention percentage is 0
        """
        result = calculate_time_metrics(original_duration=0.0, edited_duration=0.0)

        assert result.retention_percentage == 0.0
        assert result.time_saved == 0.0


class TestCalculateFluffByType:
    """Tests for fluff duration by type calculation."""

    def test_single_fluff_type(self):
        """
        Given: Removed segments of single type
        When: Calculating fluff by type
        Then: Returns correct total duration for that type
        """
        removed_segments = [
            RemovedSegment(
                start_time=0.0,
                end_time=5.0,
                duration=5.0,
                fluff_type="intro",
                confidence=0.9,
                transcript="Hey guys",
            ),
            RemovedSegment(
                start_time=10.0,
                end_time=13.0,
                duration=3.0,
                fluff_type="intro",
                confidence=0.85,
                transcript="Welcome back",
            ),
        ]

        result = calculate_fluff_by_type(removed_segments)

        assert result["intro"] == 8.0

    def test_multiple_fluff_types(self):
        """
        Given: Removed segments of different types
        When: Calculating fluff by type
        Then: Returns correct duration for each type
        """
        removed_segments = [
            RemovedSegment(
                start_time=0.0,
                end_time=5.0,
                duration=5.0,
                fluff_type="intro",
                confidence=0.9,
                transcript="Hey guys",
            ),
            RemovedSegment(
                start_time=10.0,
                end_time=15.0,
                duration=5.0,
                fluff_type="call_to_action",
                confidence=0.95,
                transcript="Like and subscribe",
            ),
            RemovedSegment(
                start_time=20.0,
                end_time=22.0,
                duration=2.0,
                fluff_type="silence",
                confidence=0.98,
                transcript="[No transcript available]",
            ),
        ]

        result = calculate_fluff_by_type(removed_segments)

        assert result["intro"] == 5.0
        assert result["call_to_action"] == 5.0
        assert result["silence"] == 2.0


class TestLoadTranscriptSegments:
    """Tests for loading transcript from S3."""

    @patch("fluff_report.boto3.client")
    def test_successful_load(self, mock_boto3_client):
        """
        Given: Valid S3 path to transcript
        When: Loading transcript segments
        Then: Returns parsed segments list
        """
        # Mock S3 response
        mock_s3 = MagicMock()
        mock_boto3_client.return_value = mock_s3

        transcript_data = {
            "segments": [
                {"start_time": 0.0, "end_time": 5.0, "text": "Hello world"}
            ]
        }

        mock_s3.get_object.return_value = {
            "Body": MagicMock(
                read=MagicMock(
                    return_value=json.dumps(transcript_data).encode("utf-8")
                )
            )
        }

        result = load_transcript_segments("s3://test-bucket/test-key.json")

        assert len(result) == 1
        assert result[0]["text"] == "Hello world"

    @patch("fluff_report.boto3.client")
    def test_invalid_s3_uri(self, mock_boto3_client):
        """
        Given: Invalid S3 URI (not starting with s3://)
        When: Loading transcript segments
        Then: Raises FluffReportError
        """
        with pytest.raises(FluffReportError, match="Invalid S3 URI"):
            load_transcript_segments("http://invalid-uri")


class TestSaveFluffReportToS3:
    """Tests for saving fluff report to S3."""

    @patch("fluff_report.boto3.client")
    def test_successful_save(self, mock_boto3_client):
        """
        Given: Valid fluff report
        When: Saving to S3
        Then: Uploads JSON to S3 and returns S3 path
        """
        # Mock S3 client
        mock_s3 = MagicMock()
        mock_boto3_client.return_value = mock_s3

        report = FluffReport(
            job_id="test-job",
            removed_segments=[],
            time_metrics=TimeMetrics(
                original_duration=100.0,
                edited_duration=80.0,
                time_saved=20.0,
                retention_percentage=80.0,
            ),
            fluff_by_type={"intro": 10.0, "outro": 10.0},
            total_segments_removed=2,
            total_segments_kept=8,
        )

        result = save_fluff_report_to_s3(
            report=report, s3_bucket="test-bucket", s3_key="test-key.json"
        )

        assert result == "s3://test-bucket/test-key.json"
        mock_s3.put_object.assert_called_once()


class TestGenerateFluffReport:
    """Tests for complete fluff report generation."""

    @patch("fluff_report.load_transcript_segments")
    def test_complete_report_generation(self, mock_load_transcript):
        """
        Given: Classifications, transcript, and duration data
        When: Generating fluff report
        Then: Returns complete FluffReport with all fields populated
        """
        # Mock transcript loading
        mock_load_transcript.return_value = [
            {"start_time": 0.0, "end_time": 5.0, "text": "Hey guys"},
            {"start_time": 5.0, "end_time": 10.0, "text": "Good content"},
            {"start_time": 10.0, "end_time": 15.0, "text": "Like and subscribe"},
        ]

        classifications = [
            {
                "start_time": 0.0,
                "end_time": 5.0,
                "is_fluff": True,
                "fluff_type": "intro",
                "confidence": 0.9,
            },
            {
                "start_time": 5.0,
                "end_time": 10.0,
                "is_fluff": False,
                "fluff_type": None,
                "confidence": 0.8,
            },
            {
                "start_time": 10.0,
                "end_time": 15.0,
                "is_fluff": True,
                "fluff_type": "call_to_action",
                "confidence": 0.95,
            },
        ]

        result = generate_fluff_report(
            job_id="test-job",
            classifications=classifications,
            transcript_s3_path="s3://test-bucket/transcript.json",
            original_duration=15.0,
            edited_duration=5.0,
        )

        # Validate report structure
        assert result.job_id == "test-job"
        assert len(result.removed_segments) == 2
        assert result.time_metrics.time_saved == 10.0
        assert result.time_metrics.retention_percentage == pytest.approx(33.33, rel=0.1)
        assert result.total_segments_removed == 2
        assert result.total_segments_kept == 1
        assert "intro" in result.fluff_by_type
        assert "call_to_action" in result.fluff_by_type
