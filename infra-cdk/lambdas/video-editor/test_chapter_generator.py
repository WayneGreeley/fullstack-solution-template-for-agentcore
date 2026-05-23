"""
Unit tests for chapter generation module.

Tests chapter generation, alignment, and embedding functionality.
"""

import json
import os
import tempfile
from unittest.mock import Mock, patch

import pytest
from chapter_generator import (
    Chapter,
    ChapterGenerationError,
    TimeRange,
    align_chapters_with_edited_video,
    embed_chapters_in_video,
    generate_chapter_title_with_nova,
    generate_chapters,
    get_transcript_for_segment,
    identify_thematic_sections,
    load_transcript_segments,
    save_chapters_to_s3,
)


class TestLoadTranscriptSegments:
    """Tests for load_transcript_segments function."""

    def test_load_valid_transcript(self):
        """
        Given a valid S3 path to transcript JSON
        When load_transcript_segments is called
        Then it should return the list of segments
        """
        # Given
        s3_path = "s3://test-bucket/job123/transcript.json"
        mock_segments = [
            {"start_time": 0.0, "end_time": 5.0, "text": "Hello world"},
            {"start_time": 5.0, "end_time": 10.0, "text": "This is a test"},
        ]
        mock_transcript = {"segments": mock_segments}

        with patch("chapter_generator.boto3.client") as mock_boto:
            mock_s3 = Mock()
            mock_boto.return_value = mock_s3
            mock_s3.get_object.return_value = {
                "Body": Mock(
                    read=Mock(return_value=json.dumps(mock_transcript).encode("utf-8"))
                )
            }

            # When
            result = load_transcript_segments(s3_path)

            # Then
            assert result == mock_segments
            mock_s3.get_object.assert_called_once_with(
                Bucket="test-bucket", Key="job123/transcript.json"
            )

    def test_load_transcript_invalid_uri(self):
        """
        Given an invalid S3 URI
        When load_transcript_segments is called
        Then it should raise ChapterGenerationError
        """
        # Given
        invalid_path = "invalid://path"

        with patch("chapter_generator.boto3.client"):
            # When/Then
            with pytest.raises(ChapterGenerationError, match="Invalid S3 URI"):
                load_transcript_segments(invalid_path)


class TestGetTranscriptForSegment:
    """Tests for get_transcript_for_segment function."""

    def test_get_transcript_for_overlapping_segments(self):
        """
        Given transcript segments and a time range
        When get_transcript_for_segment is called
        Then it should return concatenated text from overlapping segments
        """
        # Given
        transcript_segments = [
            {"start_time": 0.0, "end_time": 5.0, "text": "First segment"},
            {"start_time": 5.0, "end_time": 10.0, "text": "Second segment"},
            {"start_time": 10.0, "end_time": 15.0, "text": "Third segment"},
        ]
        start_time = 3.0
        end_time = 12.0

        # When
        result = get_transcript_for_segment(start_time, end_time, transcript_segments)

        # Then
        assert result == "First segment Second segment Third segment"

    def test_get_transcript_no_overlap(self):
        """
        Given transcript segments and a time range with no overlap
        When get_transcript_for_segment is called
        Then it should return empty string
        """
        # Given
        transcript_segments = [
            {"start_time": 0.0, "end_time": 5.0, "text": "First segment"},
        ]
        start_time = 10.0
        end_time = 15.0

        # When
        result = get_transcript_for_segment(start_time, end_time, transcript_segments)

        # Then
        assert result == ""


class TestIdentifyThematicSections:
    """Tests for identify_thematic_sections function."""

    def test_identify_sections_with_minimum_duration(self):
        """
        Given keep segments and minimum chapter duration
        When identify_thematic_sections is called
        Then it should group segments into sections meeting minimum duration
        """
        # Given
        keep_segments = [
            TimeRange(start=0.0, end=200.0),
            TimeRange(start=200.0, end=400.0),
            TimeRange(start=400.0, end=600.0),
        ]
        transcript_segments = []
        min_chapter_duration = 300.0

        # When
        result = identify_thematic_sections(
            keep_segments, transcript_segments, min_chapter_duration
        )

        # Then
        assert len(result) == 2
        assert result[0].start == 0.0
        assert result[0].end == 400.0
        assert result[1].start == 400.0
        assert result[1].end == 600.0

    def test_identify_sections_empty_segments(self):
        """
        Given empty keep segments list
        When identify_thematic_sections is called
        Then it should return empty list
        """
        # Given
        keep_segments = []
        transcript_segments = []

        # When
        result = identify_thematic_sections(keep_segments, transcript_segments)

        # Then
        assert result == []


class TestGenerateChapterTitleWithNova:
    """Tests for generate_chapter_title_with_nova function."""

    def test_generate_title_success(self):
        """
        Given a section transcript
        When generate_chapter_title_with_nova is called
        Then it should return a descriptive title from Nova
        """
        # Given
        section_transcript = "This section discusses machine learning algorithms"
        section_index = 0

        mock_response = {
            "output": {
                "message": {
                    "content": [{"text": "Machine Learning Algorithms"}]
                }
            }
        }

        with patch("chapter_generator.boto3.client") as mock_boto:
            mock_bedrock = Mock()
            mock_boto.return_value = mock_bedrock
            mock_bedrock.invoke_model.return_value = {
                "body": Mock(read=Mock(return_value=json.dumps(mock_response).encode()))
            }

            # When
            result = generate_chapter_title_with_nova(section_transcript, section_index)

            # Then
            assert result == "Machine Learning Algorithms"
            mock_bedrock.invoke_model.assert_called_once()

    def test_generate_title_fallback_on_error(self):
        """
        Given Nova API fails
        When generate_chapter_title_with_nova is called
        Then it should return fallback title
        """
        # Given
        section_transcript = "Test transcript"
        section_index = 2

        with patch("chapter_generator.boto3.client") as mock_boto:
            mock_bedrock = Mock()
            mock_boto.return_value = mock_bedrock
            mock_bedrock.invoke_model.side_effect = Exception("API error")

            # When
            result = generate_chapter_title_with_nova(section_transcript, section_index)

            # Then
            assert result == "Chapter 3"


class TestAlignChaptersWithEditedVideo:
    """Tests for align_chapters_with_edited_video function."""

    def test_align_chapters_simple_case(self):
        """
        Given thematic sections and keep segments
        When align_chapters_with_edited_video is called
        Then it should return aligned chapters with edited video timestamps
        """
        # Given
        thematic_sections = [
            TimeRange(start=0.0, end=300.0),
            TimeRange(start=300.0, end=600.0),
        ]
        keep_segments = [
            TimeRange(start=0.0, end=300.0),
            TimeRange(start=300.0, end=600.0),
        ]

        # When
        result = align_chapters_with_edited_video(thematic_sections, keep_segments)

        # Then
        assert len(result) == 2
        assert result[0].start == 0.0
        assert result[0].end == 300.0
        assert result[1].start == 300.0
        assert result[1].end == 600.0

    def test_align_chapters_with_gaps(self):
        """
        Given thematic sections with gaps (removed segments)
        When align_chapters_with_edited_video is called
        Then it should adjust timestamps to account for removed content
        """
        # Given
        thematic_sections = [
            TimeRange(start=0.0, end=200.0),
            TimeRange(start=400.0, end=600.0),  # Gap from 200-400 removed
        ]
        keep_segments = [
            TimeRange(start=0.0, end=200.0),
            TimeRange(start=400.0, end=600.0),
        ]

        # When
        result = align_chapters_with_edited_video(thematic_sections, keep_segments)

        # Then
        assert len(result) == 2
        assert result[0].start == 0.0
        assert result[0].end == 200.0
        assert result[1].start == 200.0  # Adjusted for removed gap
        assert result[1].end == 400.0


class TestGenerateChapters:
    """Tests for generate_chapters function."""

    def test_generate_chapters_success(self):
        """
        Given keep segments and transcript
        When generate_chapters is called
        Then it should return list of chapters with titles and timestamps
        """
        # Given
        keep_segments = [
            TimeRange(start=0.0, end=400.0),
            TimeRange(start=400.0, end=800.0),
        ]
        transcript_s3_path = "s3://test-bucket/job123/transcript.json"
        edited_duration = 800.0

        mock_transcript = {
            "segments": [
                {"start_time": 0.0, "end_time": 400.0, "text": "First section"},
                {"start_time": 400.0, "end_time": 800.0, "text": "Second section"},
            ]
        }

        with patch("chapter_generator.boto3.client") as mock_boto:
            mock_s3 = Mock()
            mock_bedrock = Mock()

            def client_factory(service_name):
                if service_name == "s3":
                    return mock_s3
                elif service_name == "bedrock-runtime":
                    return mock_bedrock
                return Mock()

            mock_boto.side_effect = client_factory

            mock_s3.get_object.return_value = {
                "Body": Mock(
                    read=Mock(return_value=json.dumps(mock_transcript).encode("utf-8"))
                )
            }

            mock_bedrock.invoke_model.return_value = {
                "body": Mock(
                    read=Mock(
                        return_value=json.dumps(
                            {
                                "output": {
                                    "message": {"content": [{"text": "Test Chapter"}]}
                                }
                            }
                        ).encode()
                    )
                )
            }

            # When
            result = generate_chapters(keep_segments, transcript_s3_path, edited_duration)

            # Then
            assert len(result) >= 1
            assert all(isinstance(chapter, Chapter) for chapter in result)
            assert all(chapter.timestamp >= 0 for chapter in result)
            assert all(len(chapter.title) > 0 for chapter in result)


class TestEmbedChaptersInVideo:
    """Tests for embed_chapters_in_video function."""

    def test_embed_chapters_success(self):
        """
        Given video path and chapters
        When embed_chapters_in_video is called
        Then it should embed chapters using FFmpeg
        """
        # Given
        chapters = [
            Chapter(timestamp=0.0, title="Introduction", duration=300.0),
            Chapter(timestamp=300.0, title="Main Content", duration=300.0),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = os.path.join(temp_dir, "input.mp4")
            output_path = os.path.join(temp_dir, "output.mp4")

            # Create dummy video file
            with open(video_path, "w") as f:
                f.write("dummy video")

            with patch("chapter_generator.subprocess.run") as mock_run:
                mock_run.return_value = Mock(returncode=0)

                # When
                embed_chapters_in_video(video_path, chapters, output_path)

                # Then
                mock_run.assert_called_once()
                call_args = mock_run.call_args[0][0]
                assert call_args[0] == "ffmpeg"
                assert "-map_metadata" in call_args


class TestSaveChaptersToS3:
    """Tests for save_chapters_to_s3 function."""

    def test_save_chapters_success(self):
        """
        Given chapters and S3 location
        When save_chapters_to_s3 is called
        Then it should save chapters as JSON to S3
        """
        # Given
        chapters = [
            Chapter(timestamp=0.0, title="Introduction", duration=300.0),
            Chapter(timestamp=300.0, title="Main Content", duration=300.0),
        ]
        s3_bucket = "test-bucket"
        s3_key = "job123/chapters.json"

        with patch("chapter_generator.boto3.client") as mock_boto:
            mock_s3 = Mock()
            mock_boto.return_value = mock_s3

            # When
            result = save_chapters_to_s3(chapters, s3_bucket, s3_key)

            # Then
            assert result == f"s3://{s3_bucket}/{s3_key}"
            mock_s3.put_object.assert_called_once()
            call_kwargs = mock_s3.put_object.call_args[1]
            assert call_kwargs["Bucket"] == s3_bucket
            assert call_kwargs["Key"] == s3_key
            assert call_kwargs["ContentType"] == "application/json"
