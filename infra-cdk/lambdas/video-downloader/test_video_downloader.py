"""
Unit tests for Video Downloader Lambda function.

Tests URL validation, metadata extraction, and error handling.
"""

import json
import subprocess
from unittest.mock import Mock, patch

import pytest
from video_downloader import (
    InvalidURLError,
    VideoAccessError,
    VideoDownloadError,
    VideoMetadata,
    check_video_accessibility,
    extract_metadata,
    validate_youtube_url,
)


class TestURLValidation:
    """Tests for YouTube URL validation."""

    def test_valid_standard_youtube_url(self):
        """
        Given: A valid standard YouTube URL
        When: validate_youtube_url is called
        Then: Returns True without raising exception
        """
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert validate_youtube_url(url) is True

    def test_valid_short_youtube_url(self):
        """
        Given: A valid short YouTube URL (youtu.be)
        When: validate_youtube_url is called
        Then: Returns True without raising exception
        """
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert validate_youtube_url(url) is True

    def test_valid_mobile_youtube_url(self):
        """
        Given: A valid mobile YouTube URL
        When: validate_youtube_url is called
        Then: Returns True without raising exception
        """
        url = "https://m.youtube.com/watch?v=dQw4w9WgXcQ"
        assert validate_youtube_url(url) is True

    def test_empty_url(self):
        """
        Given: An empty URL string
        When: validate_youtube_url is called
        Then: Raises InvalidURLError
        """
        with pytest.raises(InvalidURLError, match="URL cannot be empty"):
            validate_youtube_url("")

    def test_non_youtube_domain(self):
        """
        Given: A URL from a non-YouTube domain
        When: validate_youtube_url is called
        Then: Raises InvalidURLError with domain message
        """
        url = "https://vimeo.com/123456789"
        with pytest.raises(InvalidURLError, match="must be from YouTube"):
            validate_youtube_url(url)

    def test_missing_video_id_standard_url(self):
        """
        Given: A YouTube URL without video ID parameter
        When: validate_youtube_url is called
        Then: Raises InvalidURLError
        """
        url = "https://www.youtube.com/watch"
        with pytest.raises(InvalidURLError, match="must contain video ID"):
            validate_youtube_url(url)

    def test_invalid_video_id_length(self):
        """
        Given: A YouTube URL with invalid video ID length
        When: validate_youtube_url is called
        Then: Raises InvalidURLError
        """
        url = "https://www.youtube.com/watch?v=short"
        with pytest.raises(InvalidURLError, match="Invalid YouTube video ID"):
            validate_youtube_url(url)

    def test_malformed_url(self):
        """
        Given: A malformed URL string
        When: validate_youtube_url is called
        Then: Raises InvalidURLError
        """
        url = "not a url at all"
        with pytest.raises(InvalidURLError):
            validate_youtube_url(url)


class TestVideoAccessibility:
    """Tests for video accessibility checking."""

    @patch("video_downloader.subprocess.run")
    def test_accessible_video(self, mock_run):
        """
        Given: A valid accessible YouTube video
        When: check_video_accessibility is called
        Then: Returns (True, None)
        """
        # Mock yt-dlp response with video info
        mock_run.return_value = Mock(
            returncode=0,
            stdout=json.dumps({"duration": 300, "title": "Test Video"}),
            stderr="",
        )

        is_accessible, error = check_video_accessibility(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )

        assert is_accessible is True
        assert error is None

    @patch("video_downloader.subprocess.run")
    def test_private_video(self, mock_run):
        """
        Given: A private YouTube video
        When: check_video_accessibility is called
        Then: Returns (False, "Video is private")
        """
        mock_run.return_value = Mock(
            returncode=1, stdout="", stderr="ERROR: This is a private video"
        )

        is_accessible, error = check_video_accessibility(
            "https://www.youtube.com/watch?v=private123"
        )

        assert is_accessible is False
        assert "private" in error.lower()

    @patch("video_downloader.subprocess.run")
    def test_unavailable_video(self, mock_run):
        """
        Given: An unavailable YouTube video
        When: check_video_accessibility is called
        Then: Returns (False, "Video is unavailable")
        """
        mock_run.return_value = Mock(
            returncode=1, stdout="", stderr="ERROR: Video unavailable"
        )

        is_accessible, error = check_video_accessibility(
            "https://www.youtube.com/watch?v=unavail123"
        )

        assert is_accessible is False
        assert "unavailable" in error.lower()

    @patch("video_downloader.subprocess.run")
    def test_video_too_long(self, mock_run):
        """
        Given: A YouTube video longer than 2 hours
        When: check_video_accessibility is called
        Then: Returns (False, error message about length)
        """
        # Mock video with duration > 7200 seconds (2 hours)
        mock_run.return_value = Mock(
            returncode=0,
            stdout=json.dumps({"duration": 8000, "title": "Long Video"}),
            stderr="",
        )

        is_accessible, error = check_video_accessibility(
            "https://www.youtube.com/watch?v=longvid123"
        )

        assert is_accessible is False
        assert "too long" in error.lower()
        assert "7200" in error

    @patch("video_downloader.subprocess.run")
    def test_age_restricted_video(self, mock_run):
        """
        Given: An age-restricted YouTube video
        When: check_video_accessibility is called
        Then: Returns (False, "Video is age-restricted")
        """
        mock_run.return_value = Mock(
            returncode=1, stdout="", stderr="ERROR: This video is age restricted"
        )

        is_accessible, error = check_video_accessibility(
            "https://www.youtube.com/watch?v=age123"
        )

        assert is_accessible is False
        assert "age-restricted" in error.lower()

    @patch("video_downloader.subprocess.run")
    def test_timeout_checking_video(self, mock_run):
        """
        Given: A timeout occurs while checking video
        When: check_video_accessibility is called
        Then: Returns (False, timeout error message)
        """
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="yt-dlp", timeout=30)

        is_accessible, error = check_video_accessibility(
            "https://www.youtube.com/watch?v=timeout123"
        )

        assert is_accessible is False
        assert "timeout" in error.lower()


class TestMetadataExtraction:
    """Tests for video metadata extraction."""

    @patch("video_downloader.subprocess.run")
    def test_extract_complete_metadata(self, mock_run):
        """
        Given: A valid YouTube video with complete metadata
        When: extract_metadata is called
        Then: Returns VideoMetadata with all fields populated
        """
        video_info = {
            "title": "Test Video Title",
            "duration": 300.5,
            "thumbnail": "https://i.ytimg.com/vi/test/maxresdefault.jpg",
            "width": 1920,
            "height": 1080,
            "ext": "mp4",
        }

        mock_run.return_value = Mock(
            returncode=0, stdout=json.dumps(video_info), stderr=""
        )

        metadata = extract_metadata("https://www.youtube.com/watch?v=test123")

        assert isinstance(metadata, VideoMetadata)
        assert metadata.title == "Test Video Title"
        assert metadata.duration == 300.5
        assert metadata.thumbnail == "https://i.ytimg.com/vi/test/maxresdefault.jpg"
        assert metadata.resolution == "1920x1080"
        assert metadata.format == "mp4"

    @patch("video_downloader.subprocess.run")
    def test_extract_metadata_missing_fields(self, mock_run):
        """
        Given: A YouTube video with some missing metadata fields
        When: extract_metadata is called
        Then: Returns VideoMetadata with default values for missing fields
        """
        video_info = {"title": "Minimal Video", "duration": 120}

        mock_run.return_value = Mock(
            returncode=0, stdout=json.dumps(video_info), stderr=""
        )

        metadata = extract_metadata("https://www.youtube.com/watch?v=minimal123")

        assert metadata.title == "Minimal Video"
        assert metadata.duration == 120
        assert metadata.thumbnail == ""
        assert metadata.resolution == "unknown"
        assert metadata.format == "mp4"  # Default format

    @patch("video_downloader.subprocess.run")
    def test_extract_metadata_subprocess_error(self, mock_run):
        """
        Given: yt-dlp command fails
        When: extract_metadata is called
        Then: Raises VideoDownloadError
        """
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd="yt-dlp", stderr="ERROR: Failed to extract info"
        )

        with pytest.raises(VideoDownloadError, match="Failed to extract metadata"):
            extract_metadata("https://www.youtube.com/watch?v=error123")

    @patch("video_downloader.subprocess.run")
    def test_extract_metadata_invalid_json(self, mock_run):
        """
        Given: yt-dlp returns invalid JSON
        When: extract_metadata is called
        Then: Raises VideoDownloadError
        """
        mock_run.return_value = Mock(returncode=0, stdout="not valid json", stderr="")

        with pytest.raises(VideoDownloadError, match="Failed to parse video metadata"):
            extract_metadata("https://www.youtube.com/watch?v=badjson123")


class TestErrorHandling:
    """Tests for error handling edge cases."""

    def test_invalid_url_error_inheritance(self):
        """
        Given: InvalidURLError exception
        When: Checking exception type
        Then: Is instance of VideoDownloadError
        """
        error = InvalidURLError("test error")
        assert isinstance(error, VideoDownloadError)

    def test_video_access_error_inheritance(self):
        """
        Given: VideoAccessError exception
        When: Checking exception type
        Then: Is instance of VideoDownloadError
        """
        error = VideoAccessError("test error")
        assert isinstance(error, VideoDownloadError)
