"""
Unit tests for Transcriber Lambda function.

Tests transcription, segmentation, speaker identification, and error handling.
"""

from unittest.mock import Mock, patch

import pytest
from transcriber import (
    Transcript,
    TranscriptionError,
    TranscriptSegment,
    parse_transcribe_output,
    segment_by_pauses,
    start_transcription_job,
    wait_for_transcription_job,
)


class TestTranscriptionJobManagement:
    """Tests for Amazon Transcribe job management."""

    @patch("transcriber.get_transcribe_client")
    def test_start_transcription_job_success(self, mock_get_client):
        """
        Given: Valid audio S3 URI and job parameters
        When: start_transcription_job is called
        Then: Returns transcription job name
        """
        # Mock Transcribe client
        mock_client = Mock()
        mock_client.start_transcription_job.return_value = {
            "TranscriptionJob": {"TranscriptionJobName": "test-job-123"}
        }
        mock_get_client.return_value = mock_client

        job_name = start_transcription_job(
            audio_s3_uri="s3://bucket/audio.wav",
            job_id="job-123",
            job_name="test-job-123",
        )

        assert job_name == "test-job-123"
        mock_client.start_transcription_job.assert_called_once()

        # Verify call parameters
        call_args = mock_client.start_transcription_job.call_args[1]
        assert call_args["TranscriptionJobName"] == "test-job-123"
        assert call_args["Media"]["MediaFileUri"] == "s3://bucket/audio.wav"
        assert call_args["MediaFormat"] == "wav"
        assert call_args["Settings"]["ShowSpeakerLabels"] is True
        assert call_args["Settings"]["MaxSpeakerLabels"] == 10

    @patch("transcriber.get_transcribe_client")
    def test_start_transcription_job_client_error(self, mock_get_client):
        """
        Given: Transcribe client raises ClientError
        When: start_transcription_job is called
        Then: Raises TranscriptionError with details
        """
        from botocore.exceptions import ClientError

        mock_client = Mock()
        mock_client.start_transcription_job.side_effect = ClientError(
            error_response={
                "Error": {"Code": "LimitExceededException", "Message": "Rate limit"}
            },
            operation_name="StartTranscriptionJob",
        )
        mock_get_client.return_value = mock_client

        with pytest.raises(TranscriptionError, match="Failed to start transcription"):
            start_transcription_job(
                audio_s3_uri="s3://bucket/audio.wav",
                job_id="job-123",
                job_name="test-job-123",
            )

    @patch("transcriber.get_transcribe_client")
    @patch("transcriber.time.sleep")
    def test_wait_for_transcription_job_completed(self, mock_sleep, mock_get_client):
        """
        Given: Transcription job completes successfully
        When: wait_for_transcription_job is called
        Then: Returns job details
        """
        mock_client = Mock()
        mock_client.get_transcription_job.return_value = {
            "TranscriptionJob": {
                "TranscriptionJobName": "test-job-123",
                "TranscriptionJobStatus": "COMPLETED",
                "Transcript": {"TranscriptFileUri": "s3://bucket/transcript.json"},
            }
        }
        mock_get_client.return_value = mock_client

        job_details = wait_for_transcription_job(job_name="test-job-123", timeout=60)

        assert job_details["TranscriptionJobStatus"] == "COMPLETED"
        assert "TranscriptFileUri" in job_details["Transcript"]

    @patch("transcriber.get_transcribe_client")
    @patch("transcriber.time.sleep")
    def test_wait_for_transcription_job_failed(self, mock_sleep, mock_get_client):
        """
        Given: Transcription job fails
        When: wait_for_transcription_job is called
        Then: Raises TranscriptionError with failure reason
        """
        mock_client = Mock()
        mock_client.get_transcription_job.return_value = {
            "TranscriptionJob": {
                "TranscriptionJobName": "test-job-123",
                "TranscriptionJobStatus": "FAILED",
                "FailureReason": "Audio quality too low",
            }
        }
        mock_get_client.return_value = mock_client

        with pytest.raises(TranscriptionError, match="Audio quality too low"):
            wait_for_transcription_job(job_name="test-job-123", timeout=60)

    @patch("transcriber.get_transcribe_client")
    @patch("transcriber.time.time")
    @patch("transcriber.time.sleep")
    def test_wait_for_transcription_job_timeout(
        self, mock_sleep, mock_time, mock_get_client
    ):
        """
        Given: Transcription job takes too long
        When: wait_for_transcription_job is called with timeout
        Then: Raises TranscriptionError with timeout message
        """
        mock_client = Mock()
        mock_client.get_transcription_job.return_value = {
            "TranscriptionJob": {
                "TranscriptionJobName": "test-job-123",
                "TranscriptionJobStatus": "IN_PROGRESS",
            }
        }
        mock_get_client.return_value = mock_client

        # Simulate timeout by advancing time
        mock_time.side_effect = [0, 700]  # Start time, then past timeout

        with pytest.raises(TranscriptionError, match="timeout"):
            wait_for_transcription_job(job_name="test-job-123", timeout=600)


class TestSegmentation:
    """Tests for transcript segmentation by pauses."""

    def test_segment_by_pauses_single_segment(self):
        """
        Given: Transcript items with no pauses > 1 second
        When: segment_by_pauses is called
        Then: Returns single segment with all words
        """
        items = [
            {
                "type": "pronunciation",
                "start_time": "0.0",
                "end_time": "0.5",
                "alternatives": [{"content": "Hello", "confidence": "0.99"}],
            },
            {
                "type": "pronunciation",
                "start_time": "0.6",
                "end_time": "1.0",
                "alternatives": [{"content": "world", "confidence": "0.98"}],
            },
        ]

        segments = segment_by_pauses(items, pause_threshold=1.0)

        assert len(segments) == 1
        assert segments[0].text == "Hello world"
        assert segments[0].start_time == 0.0
        assert segments[0].end_time == 1.0

    def test_segment_by_pauses_multiple_segments(self):
        """
        Given: Transcript items with pauses > 1 second
        When: segment_by_pauses is called
        Then: Returns multiple segments split at pauses
        """
        items = [
            {
                "type": "pronunciation",
                "start_time": "0.0",
                "end_time": "0.5",
                "alternatives": [{"content": "Hello", "confidence": "0.99"}],
            },
            {
                "type": "pronunciation",
                "start_time": "0.6",
                "end_time": "1.0",
                "alternatives": [{"content": "world", "confidence": "0.98"}],
            },
            # Pause of 1.5 seconds
            {
                "type": "pronunciation",
                "start_time": "2.5",
                "end_time": "3.0",
                "alternatives": [{"content": "How", "confidence": "0.97"}],
            },
            {
                "type": "pronunciation",
                "start_time": "3.1",
                "end_time": "3.5",
                "alternatives": [{"content": "are", "confidence": "0.96"}],
            },
            {
                "type": "pronunciation",
                "start_time": "3.6",
                "end_time": "4.0",
                "alternatives": [{"content": "you", "confidence": "0.95"}],
            },
        ]

        segments = segment_by_pauses(items, pause_threshold=1.0)

        assert len(segments) == 2
        assert segments[0].text == "Hello world"
        assert segments[0].start_time == 0.0
        assert segments[0].end_time == 1.0
        assert segments[1].text == "How are you"
        assert segments[1].start_time == 2.5
        assert segments[1].end_time == 4.0

    def test_segment_by_pauses_with_speaker_changes(self):
        """
        Given: Transcript items with speaker changes
        When: segment_by_pauses is called
        Then: Returns segments split at speaker changes
        """
        items = [
            {
                "type": "pronunciation",
                "start_time": "0.0",
                "end_time": "0.5",
                "alternatives": [{"content": "Hello", "confidence": "0.99"}],
                "speaker_label": "spk_0",
            },
            {
                "type": "pronunciation",
                "start_time": "0.6",
                "end_time": "1.0",
                "alternatives": [{"content": "there", "confidence": "0.98"}],
                "speaker_label": "spk_0",
            },
            # Speaker change
            {
                "type": "pronunciation",
                "start_time": "1.1",
                "end_time": "1.5",
                "alternatives": [{"content": "Hi", "confidence": "0.97"}],
                "speaker_label": "spk_1",
            },
            {
                "type": "pronunciation",
                "start_time": "1.6",
                "end_time": "2.0",
                "alternatives": [{"content": "back", "confidence": "0.96"}],
                "speaker_label": "spk_1",
            },
        ]

        segments = segment_by_pauses(items, pause_threshold=1.0)

        assert len(segments) == 2
        assert segments[0].text == "Hello there"
        assert segments[0].speaker_id == "spk_0"
        assert segments[1].text == "Hi back"
        assert segments[1].speaker_id == "spk_1"

    def test_segment_by_pauses_ignores_punctuation(self):
        """
        Given: Transcript items including punctuation items
        When: segment_by_pauses is called
        Then: Ignores punctuation items and only processes pronunciation
        """
        items = [
            {
                "type": "pronunciation",
                "start_time": "0.0",
                "end_time": "0.5",
                "alternatives": [{"content": "Hello", "confidence": "0.99"}],
            },
            {"type": "punctuation", "alternatives": [{"content": ","}]},
            {
                "type": "pronunciation",
                "start_time": "0.6",
                "end_time": "1.0",
                "alternatives": [{"content": "world", "confidence": "0.98"}],
            },
        ]

        segments = segment_by_pauses(items, pause_threshold=1.0)

        assert len(segments) == 1
        assert segments[0].text == "Hello world"


class TestTranscriptParsing:
    """Tests for parsing Amazon Transcribe output."""

    def test_parse_transcribe_output_basic(self):
        """
        Given: Valid Amazon Transcribe output JSON
        When: parse_transcribe_output is called
        Then: Returns Transcript object with segments
        """
        transcript_json = {
            "jobName": "en-US-test-job",
            "results": {
                "transcripts": [{"transcript": "Hello world"}],
                "items": [
                    {
                        "type": "pronunciation",
                        "start_time": "0.0",
                        "end_time": "0.5",
                        "alternatives": [{"content": "Hello", "confidence": "0.99"}],
                    },
                    {
                        "type": "pronunciation",
                        "start_time": "0.6",
                        "end_time": "1.0",
                        "alternatives": [{"content": "world", "confidence": "0.98"}],
                    },
                ],
                "speaker_labels": {"segments": []},
            },
        }

        transcript = parse_transcribe_output(transcript_json)

        assert isinstance(transcript, Transcript)
        assert transcript.full_text == "Hello world"
        assert transcript.language == "en-US"
        assert len(transcript.segments) == 1
        assert transcript.segments[0].text == "Hello world"

    def test_parse_transcribe_output_with_speakers(self):
        """
        Given: Amazon Transcribe output with speaker labels
        When: parse_transcribe_output is called
        Then: Returns Transcript with speaker IDs in segments
        """
        transcript_json = {
            "jobName": "en-US-test-job",
            "results": {
                "transcripts": [{"transcript": "Hello there Hi back"}],
                "items": [
                    {
                        "type": "pronunciation",
                        "start_time": "0.0",
                        "end_time": "0.5",
                        "alternatives": [{"content": "Hello", "confidence": "0.99"}],
                    },
                    {
                        "type": "pronunciation",
                        "start_time": "0.6",
                        "end_time": "1.0",
                        "alternatives": [{"content": "there", "confidence": "0.98"}],
                    },
                    {
                        "type": "pronunciation",
                        "start_time": "1.1",
                        "end_time": "1.5",
                        "alternatives": [{"content": "Hi", "confidence": "0.97"}],
                    },
                    {
                        "type": "pronunciation",
                        "start_time": "1.6",
                        "end_time": "2.0",
                        "alternatives": [{"content": "back", "confidence": "0.96"}],
                    },
                ],
                "speaker_labels": {
                    "segments": [
                        {
                            "speaker_label": "spk_0",
                            "items": [
                                {"start_time": "0.0", "end_time": "0.5"},
                                {"start_time": "0.6", "end_time": "1.0"},
                            ],
                        },
                        {
                            "speaker_label": "spk_1",
                            "items": [
                                {"start_time": "1.1", "end_time": "1.5"},
                                {"start_time": "1.6", "end_time": "2.0"},
                            ],
                        },
                    ]
                },
            },
        }

        transcript = parse_transcribe_output(transcript_json)

        assert len(transcript.segments) == 2
        assert transcript.segments[0].speaker_id == "spk_0"
        assert transcript.segments[1].speaker_id == "spk_1"

    def test_parse_transcribe_output_calculates_confidence(self):
        """
        Given: Amazon Transcribe output with varying confidence scores
        When: parse_transcribe_output is called
        Then: Returns Transcript with overall confidence calculated
        """
        transcript_json = {
            "jobName": "en-US-test-job",
            "results": {
                "transcripts": [{"transcript": "Test"}],
                "items": [
                    {
                        "type": "pronunciation",
                        "start_time": "0.0",
                        "end_time": "0.5",
                        "alternatives": [{"content": "Test", "confidence": "0.80"}],
                    }
                ],
                "speaker_labels": {"segments": []},
            },
        }

        transcript = parse_transcribe_output(transcript_json)

        # Confidence should be calculated from segments
        assert 0.0 <= transcript.confidence <= 1.0


class TestErrorHandling:
    """Tests for error handling edge cases."""

    def test_transcription_error_inheritance(self):
        """
        Given: TranscriptionError exception
        When: Checking exception type
        Then: Is instance of Exception
        """
        error = TranscriptionError("test error")
        assert isinstance(error, Exception)

    def test_segment_by_pauses_empty_items(self):
        """
        Given: Empty items list
        When: segment_by_pauses is called
        Then: Returns empty segments list
        """
        segments = segment_by_pauses([], pause_threshold=1.0)
        assert segments == []

    def test_segment_by_pauses_only_punctuation(self):
        """
        Given: Items list with only punctuation
        When: segment_by_pauses is called
        Then: Returns empty segments list
        """
        items = [
            {"type": "punctuation", "alternatives": [{"content": "."}]},
            {"type": "punctuation", "alternatives": [{"content": "!"}]},
        ]

        segments = segment_by_pauses(items, pause_threshold=1.0)
        assert segments == []


class TestDataClasses:
    """Tests for data class structures."""

    def test_transcript_segment_creation(self):
        """
        Given: Valid segment parameters
        When: TranscriptSegment is created
        Then: All fields are set correctly
        """
        segment = TranscriptSegment(
            start_time=0.0,
            end_time=1.0,
            text="Hello world",
            confidence=0.99,
            speaker_id="spk_0",
        )

        assert segment.start_time == 0.0
        assert segment.end_time == 1.0
        assert segment.text == "Hello world"
        assert segment.confidence == 0.99
        assert segment.speaker_id == "spk_0"

    def test_transcript_segment_optional_speaker(self):
        """
        Given: Segment without speaker ID
        When: TranscriptSegment is created
        Then: speaker_id is None
        """
        segment = TranscriptSegment(
            start_time=0.0, end_time=1.0, text="Hello", confidence=0.99
        )

        assert segment.speaker_id is None

    def test_transcript_creation(self):
        """
        Given: Valid transcript parameters
        When: Transcript is created
        Then: All fields are set correctly
        """
        segments = [
            TranscriptSegment(
                start_time=0.0, end_time=1.0, text="Hello", confidence=0.99
            )
        ]

        transcript = Transcript(
            full_text="Hello", segments=segments, language="en-US", confidence=0.99
        )

        assert transcript.full_text == "Hello"
        assert len(transcript.segments) == 1
        assert transcript.language == "en-US"
        assert transcript.confidence == 0.99
