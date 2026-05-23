"""
Transcription Lambda Function

Transcribes audio using Amazon Transcribe, segments by pauses, identifies speakers,
and aligns timestamps with video.

Requirements: 2.1, 2.2, 2.3, 2.4
"""

import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

# Environment variables
RAW_VIDEOS_BUCKET = os.environ.get("RAW_VIDEOS_BUCKET")
TRANSCRIPTS_BUCKET = os.environ.get("TRANSCRIPTS_BUCKET")
JOBS_TABLE = os.environ.get("JOBS_TABLE")

# AWS clients - initialized lazily
_s3_client = None
_transcribe_client = None
_dynamodb = None


def get_s3_client():
    """Get or create S3 client."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3")
    return _s3_client


def get_transcribe_client():
    """Get or create Transcribe client."""
    global _transcribe_client
    if _transcribe_client is None:
        _transcribe_client = boto3.client("transcribe")
    return _transcribe_client


def get_dynamodb_resource():
    """Get or create DynamoDB resource."""
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb


@dataclass
class TranscriptSegment:
    """
    A segment of transcribed text with timing information.

    Attributes:
        start_time: Start time in seconds
        end_time: End time in seconds
        text: Transcribed text
        confidence: Confidence score (0-1)
        speaker_id: Optional speaker identifier
    """

    start_time: float
    end_time: float
    text: str
    confidence: float
    speaker_id: Optional[str] = None


@dataclass
class Transcript:
    """
    Complete transcript with metadata.

    Attributes:
        full_text: Complete transcribed text
        segments: List of transcript segments
        language: Detected language code
        confidence: Overall confidence score
    """

    full_text: str
    segments: List[TranscriptSegment]
    language: str
    confidence: float


class TranscriptionError(Exception):
    """Base exception for transcription errors."""

    pass


def start_transcription_job(audio_s3_uri: str, job_id: str, job_name: str) -> str:
    """
    Starts an Amazon Transcribe job.

    Args:
        audio_s3_uri: S3 URI to audio file (s3://bucket/key)
        job_id: Unique job identifier
        job_name: Transcription job name

    Returns:
        Transcription job name

    Raises:
        TranscriptionError: If job creation fails

    Validates: Requirements 2.1
    """
    transcribe = get_transcribe_client()

    try:
        # Start transcription job with speaker identification
        response = transcribe.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={"MediaFileUri": audio_s3_uri},
            MediaFormat="wav",
            LanguageCode="en-US",  # Auto-detection can be added later
            Settings={
                "ShowSpeakerLabels": True,
                "MaxSpeakerLabels": 10,  # Support up to 10 speakers
                "ChannelIdentification": False,
            },
            OutputBucketName=TRANSCRIPTS_BUCKET,
            OutputKey=f"{job_id}/transcribe-output.json",
        )

        return response["TranscriptionJob"]["TranscriptionJobName"]

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        error_msg = e.response.get("Error", {}).get("Message", str(e))
        raise TranscriptionError(
            f"Failed to start transcription job: {error_code} - {error_msg}"
        )
    except Exception as e:
        raise TranscriptionError(f"Unexpected error starting transcription: {str(e)}")


def wait_for_transcription_job(job_name: str, timeout: int = 600) -> Dict[str, Any]:
    """
    Waits for transcription job to complete.

    Args:
        job_name: Transcription job name
        timeout: Maximum wait time in seconds (default: 10 minutes)

    Returns:
        Transcription job details

    Raises:
        TranscriptionError: If job fails or times out

    Validates: Requirements 2.5
    """
    transcribe = get_transcribe_client()
    start_time = time.time()

    while True:
        try:
            response = transcribe.get_transcription_job(TranscriptionJobName=job_name)
            job = response["TranscriptionJob"]
            status = job["TranscriptionJobStatus"]

            if status == "COMPLETED":
                return job
            elif status == "FAILED":
                failure_reason = job.get("FailureReason", "Unknown reason")
                raise TranscriptionError(f"Transcription job failed: {failure_reason}")

            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise TranscriptionError(
                    f"Transcription job timeout after {timeout} seconds"
                )

            # Wait before polling again
            time.sleep(5)

        except ClientError as e:
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            raise TranscriptionError(
                f"Error checking transcription status: {error_msg}"
            )


def download_transcript_from_s3(transcript_uri: str) -> Dict[str, Any]:
    """
    Downloads transcript JSON from S3.

    Args:
        transcript_uri: S3 URI to transcript file

    Returns:
        Parsed transcript JSON

    Raises:
        TranscriptionError: If download or parsing fails
    """
    s3 = get_s3_client()

    try:
        # Parse S3 URI
        if not transcript_uri.startswith("s3://"):
            raise TranscriptionError(f"Invalid S3 URI: {transcript_uri}")

        uri_parts = transcript_uri[5:].split("/", 1)
        bucket = uri_parts[0]
        key = uri_parts[1]

        # Download transcript
        response = s3.get_object(Bucket=bucket, Key=key)
        transcript_json = json.loads(response["Body"].read().decode("utf-8"))

        return transcript_json

    except ClientError as e:
        error_msg = e.response.get("Error", {}).get("Message", str(e))
        raise TranscriptionError(f"Failed to download transcript: {error_msg}")
    except json.JSONDecodeError as e:
        raise TranscriptionError(f"Failed to parse transcript JSON: {str(e)}")
    except Exception as e:
        raise TranscriptionError(f"Unexpected error downloading transcript: {str(e)}")


def segment_by_pauses(
    items: List[Dict[str, Any]], pause_threshold: float = 1.0
) -> List[TranscriptSegment]:
    """
    Segments transcript by pauses longer than threshold.

    Args:
        items: List of transcript items from Amazon Transcribe
        pause_threshold: Minimum pause duration in seconds to create new segment

    Returns:
        List of transcript segments

    Validates: Requirements 2.2
    """
    segments = []
    current_segment_words = []
    current_start_time = None
    current_end_time = None
    current_speaker = None
    last_end_time = None

    for item in items:
        if item["type"] != "pronunciation":
            continue

        start_time = float(item["start_time"])
        end_time = float(item["end_time"])
        content = item["alternatives"][0]["content"]

        # Get speaker label if available
        speaker = item.get("speaker_label")

        # Check if we should start a new segment
        should_segment = False

        if current_start_time is None:
            # First word - start new segment
            current_start_time = start_time
            current_speaker = speaker
        elif (
            last_end_time is not None and (start_time - last_end_time) > pause_threshold
        ):
            # Pause detected - segment here
            should_segment = True
        elif speaker != current_speaker and speaker is not None:
            # Speaker change - segment here
            should_segment = True

        if should_segment and current_segment_words:
            # Create segment from accumulated words
            segment_text = " ".join(current_segment_words)
            avg_confidence = sum(
                float(items[i]["alternatives"][0]["confidence"])
                for i in range(len(current_segment_words))
                if items[i]["type"] == "pronunciation"
            ) / len(current_segment_words)

            segments.append(
                TranscriptSegment(
                    start_time=current_start_time,
                    end_time=current_end_time,
                    text=segment_text,
                    confidence=avg_confidence,
                    speaker_id=current_speaker,
                )
            )

            # Start new segment
            current_segment_words = []
            current_start_time = start_time
            current_speaker = speaker

        # Add word to current segment
        current_segment_words.append(content)
        current_end_time = end_time
        last_end_time = end_time

    # Add final segment
    if current_segment_words:
        segment_text = " ".join(current_segment_words)
        segments.append(
            TranscriptSegment(
                start_time=current_start_time,
                end_time=current_end_time,
                text=segment_text,
                confidence=1.0,  # Default confidence for last segment
                speaker_id=current_speaker,
            )
        )

    return segments


def parse_transcribe_output(transcript_json: Dict[str, Any]) -> Transcript:
    """
    Parses Amazon Transcribe output into Transcript object.

    Args:
        transcript_json: Raw transcript JSON from Amazon Transcribe

    Returns:
        Transcript object with segments

    Validates: Requirements 2.1, 2.2, 2.3, 2.4
    """
    results = transcript_json.get("results", {})

    # Extract full text
    transcripts = results.get("transcripts", [])
    full_text = transcripts[0]["transcript"] if transcripts else ""

    # Extract language from job name (format: "en-US-test-job" or similar)
    job_name = transcript_json.get("jobName", "")
    # Try to extract language code (first two parts separated by dash)
    parts = job_name.split("-")
    if len(parts) >= 2 and len(parts[0]) == 2 and len(parts[1]) == 2:
        language_code = f"{parts[0]}-{parts[1]}"
    else:
        language_code = "en-US"  # Default

    # Extract items (words with timing)
    items = results.get("items", [])

    # Add speaker labels to items
    speaker_labels = results.get("speaker_labels", {})
    segments_with_speakers = speaker_labels.get("segments", [])

    # Map speaker labels to items
    for speaker_segment in segments_with_speakers:
        speaker_label = speaker_segment["speaker_label"]
        for item_info in speaker_segment.get("items", []):
            start_time = float(item_info["start_time"])
            end_time = float(item_info["end_time"])

            # Find matching item and add speaker label
            for item in items:
                if item["type"] == "pronunciation":
                    item_start = float(item["start_time"])
                    item_end = float(item["end_time"])
                    if (
                        abs(item_start - start_time) < 0.01
                        and abs(item_end - end_time) < 0.01
                    ):
                        item["speaker_label"] = speaker_label
                        break

    # Segment by pauses
    segments = segment_by_pauses(items)

    # Calculate overall confidence
    confidences = [seg.confidence for seg in segments]
    overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    return Transcript(
        full_text=full_text,
        segments=segments,
        language=language_code,
        confidence=overall_confidence,
    )


def transcribe_audio(audio_s3_path: str, job_id: str) -> Transcript:
    """
    Transcribes audio file using Amazon Transcribe.

    Args:
        audio_s3_path: S3 path to audio file (s3://bucket/key)
        job_id: Unique job identifier

    Returns:
        Transcript object with segments

    Raises:
        TranscriptionError: If transcription fails

    Validates: Requirements 2.1, 2.2, 2.3, 2.4
    """
    # Generate unique job name
    job_name = f"transcribe-{job_id}-{int(time.time())}"

    print(f"Starting transcription job: {job_name}")

    # Start transcription job
    start_transcription_job(audio_s3_path, job_id, job_name)

    # Wait for completion
    print("Waiting for transcription to complete...")
    job_details = wait_for_transcription_job(job_name)

    # Get transcript URI
    transcript_uri = job_details["Transcript"]["TranscriptFileUri"]
    print(f"Transcription complete. Downloading from: {transcript_uri}")

    # Download and parse transcript
    transcript_json = download_transcript_from_s3(transcript_uri)
    transcript = parse_transcribe_output(transcript_json)

    # Clean up transcription job
    try:
        transcribe = get_transcribe_client()
        transcribe.delete_transcription_job(TranscriptionJobName=job_name)
        print(f"Deleted transcription job: {job_name}")
    except Exception as e:
        print(f"Warning: Failed to delete transcription job: {str(e)}")

    return transcript


def store_transcript_to_s3(transcript: Transcript, job_id: str) -> str:
    """
    Stores transcript and segments to S3.

    Args:
        transcript: Transcript object to store
        job_id: Unique job identifier

    Returns:
        S3 path to stored transcript

    Raises:
        TranscriptionError: If storage fails
    """
    s3 = get_s3_client()

    try:
        # Prepare transcript data
        transcript_data = {
            "full_text": transcript.full_text,
            "language": transcript.language,
            "confidence": transcript.confidence,
            "segments": [asdict(seg) for seg in transcript.segments],
        }

        # Store to S3
        key = f"{job_id}/transcript.json"
        s3.put_object(
            Bucket=TRANSCRIPTS_BUCKET,
            Key=key,
            Body=json.dumps(transcript_data, indent=2),
            ContentType="application/json",
        )

        s3_path = f"s3://{TRANSCRIPTS_BUCKET}/{key}"
        print(f"Stored transcript to: {s3_path}")

        return s3_path

    except ClientError as e:
        error_msg = e.response.get("Error", {}).get("Message", str(e))
        raise TranscriptionError(f"Failed to store transcript: {error_msg}")
    except Exception as e:
        raise TranscriptionError(f"Unexpected error storing transcript: {str(e)}")


def update_job_status(
    job_id: str,
    status: str,
    progress: int,
    current_stage: str,
    error: Optional[Dict[str, Any]] = None,
    transcript_s3_path: Optional[str] = None,
) -> None:
    """
    Updates job status in DynamoDB.

    Args:
        job_id: Job identifier
        status: Job status (queued, processing, complete, failed)
        progress: Progress percentage (0-100)
        current_stage: Current processing stage
        error: Optional error information
        transcript_s3_path: Optional S3 path to transcript
    """
    dynamodb = get_dynamodb_resource()
    table = dynamodb.Table(JOBS_TABLE)

    update_expr = "SET #status = :status, progress = :progress, currentStage = :stage, updatedAt = :updated"
    expr_attr_names = {"#status": "status"}
    expr_attr_values = {
        ":status": status,
        ":progress": progress,
        ":stage": current_stage,
        ":updated": int(time.time() * 1000),
    }

    if error:
        update_expr += ", #error = :error"
        expr_attr_names["#error"] = "error"
        expr_attr_values[":error"] = error

    if transcript_s3_path:
        update_expr += ", transcriptS3Path = :transcript"
        expr_attr_values[":transcript"] = transcript_s3_path

    table.update_item(
        Key={"PK": f"JOB#{job_id}", "SK": "METADATA"},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_attr_names,
        ExpressionAttributeValues=expr_attr_values,
    )


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for audio transcription.

    Args:
        event: Lambda event containing jobId and audioS3Path
        context: Lambda context

    Returns:
        Response with transcription result or error
    """
    try:
        # Extract parameters
        job_id = event.get("jobId")
        audio_s3_path = event.get("audioS3Path")

        if not job_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing jobId parameter"}),
            }

        if not audio_s3_path:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing audioS3Path parameter"}),
            }

        print(f"Processing transcription for job {job_id}")
        print(f"Audio S3 path: {audio_s3_path}")

        # Update status to processing
        update_job_status(job_id, "processing", 10, "transcribe")

        # Transcribe audio
        transcript = transcribe_audio(audio_s3_path, job_id)

        # Store transcript to S3
        update_job_status(job_id, "processing", 80, "transcribe")
        transcript_s3_path = store_transcript_to_s3(transcript, job_id)

        # Update job with result
        update_job_status(
            job_id,
            "processing",
            100,
            "transcribe",
            transcript_s3_path=transcript_s3_path,
        )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "jobId": job_id,
                    "status": "complete",
                    "result": {
                        "transcriptS3Path": transcript_s3_path,
                        "language": transcript.language,
                        "confidence": transcript.confidence,
                        "segmentCount": len(transcript.segments),
                        "fullText": transcript.full_text[:500],  # First 500 chars
                    },
                }
            ),
        }

    except TranscriptionError as e:
        error_info = {
            "stage": "transcribe",
            "message": str(e),
            "timestamp": int(time.time() * 1000),
        }
        if job_id:
            update_job_status(job_id, "failed", 0, "transcribe", error=error_info)

        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "error": "Transcription failed",
                    "details": str(e),
                    "suggestedActions": [
                        "Verify audio file is accessible in S3",
                        "Check audio format is supported (WAV, 16kHz)",
                        "Retry the request",
                        "Contact support if the issue persists",
                    ],
                }
            ),
        }

    except Exception as e:
        error_info = {
            "stage": "transcribe",
            "message": f"Unexpected error: {str(e)}",
            "timestamp": int(time.time() * 1000),
        }
        if job_id:
            update_job_status(job_id, "failed", 0, "transcribe", error=error_info)

        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error", "details": str(e)}),
        }
