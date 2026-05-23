"""
Video Downloader Lambda Function

Downloads YouTube videos using yt-dlp, extracts audio, and uploads to S3.
Validates URLs, extracts metadata, and handles errors gracefully.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
"""

import json
import os
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import boto3
from botocore.exceptions import ClientError

# Environment variables
RAW_VIDEOS_BUCKET = os.environ.get("RAW_VIDEOS_BUCKET")
JOBS_TABLE = os.environ.get("JOBS_TABLE")

# AWS clients - initialized lazily to avoid credential issues during import
_s3_client = None
_dynamodb = None


def get_s3_client():
    """Get or create S3 client."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3")
    return _s3_client


def get_dynamodb_resource():
    """Get or create DynamoDB resource."""
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb


@dataclass
class VideoMetadata:
    """
    Metadata extracted from YouTube video.

    Attributes:
        title: Video title
        duration: Duration in seconds
        thumbnail: Thumbnail URL
        resolution: Video resolution (e.g., "1920x1080")
        format: Video format (e.g., "mp4")
    """

    title: str
    duration: float
    thumbnail: str
    resolution: str
    format: str


@dataclass
class DownloadResult:
    """
    Result of video download operation.

    Attributes:
        video_s3_path: S3 path to downloaded video
        audio_s3_path: S3 path to extracted audio
        metadata: Video metadata
        duration_seconds: Video duration in seconds
    """

    video_s3_path: str
    audio_s3_path: str
    metadata: VideoMetadata
    duration_seconds: float


class VideoDownloadError(Exception):
    """Base exception for video download errors."""

    pass


class InvalidURLError(VideoDownloadError):
    """Raised when YouTube URL is invalid."""

    pass


class VideoAccessError(VideoDownloadError):
    """Raised when video is restricted or unavailable."""

    pass


class VideoTooLongError(VideoDownloadError):
    """Raised when video exceeds maximum length."""

    pass


def validate_youtube_url(url: str) -> bool:
    """
    Validates YouTube URL format.

    Args:
        url: YouTube URL to validate

    Returns:
        True if URL is valid YouTube format

    Raises:
        InvalidURLError: If URL format is invalid

    Validates: Requirements 1.3
    """
    if not url:
        raise InvalidURLError("URL cannot be empty")

    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise InvalidURLError(f"Invalid URL format: {str(e)}")

    # Check if it's a YouTube URL
    valid_domains = ["youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"]
    if parsed.netloc not in valid_domains:
        raise InvalidURLError(
            f"URL must be from YouTube (youtube.com or youtu.be), got: {parsed.netloc}"
        )

    # Check for video ID
    if parsed.netloc == "youtu.be":
        # Short URL format: https://youtu.be/VIDEO_ID
        video_id = parsed.path.lstrip("/")
        if not video_id or len(video_id) != 11:
            raise InvalidURLError("Invalid YouTube short URL format")
    else:
        # Standard URL format: https://www.youtube.com/watch?v=VIDEO_ID
        query_params = parse_qs(parsed.query)
        if "v" not in query_params:
            raise InvalidURLError("YouTube URL must contain video ID (v parameter)")
        video_id = query_params["v"][0]
        if not video_id or len(video_id) != 11:
            raise InvalidURLError("Invalid YouTube video ID")

    return True


def check_video_accessibility(url: str) -> Tuple[bool, Optional[str]]:
    """
    Checks if video is accessible and not restricted.

    Args:
        url: YouTube URL to check

    Returns:
        Tuple of (is_accessible, error_message)

    Validates: Requirements 1.4
    """
    try:
        # Use yt-dlp to check video info without downloading
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-download", "--no-warnings", url],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip()

            # Check for common restriction patterns
            if "private video" in error_msg.lower():
                return False, "Video is private"
            elif "unavailable" in error_msg.lower():
                return False, "Video is unavailable"
            elif "removed" in error_msg.lower():
                return False, "Video has been removed"
            elif "age" in error_msg.lower() and "restrict" in error_msg.lower():
                return False, "Video is age-restricted"
            elif "copyright" in error_msg.lower():
                return False, "Video is blocked due to copyright"
            else:
                return False, f"Video is not accessible: {error_msg}"

        # Parse JSON to check duration
        video_info = json.loads(result.stdout)
        duration = video_info.get("duration", 0)

        # Check maximum length (2 hours = 7200 seconds)
        if duration > 7200:
            return (
                False,
                f"Video is too long ({duration}s). Maximum length is 2 hours (7200s)",
            )

        return True, None

    except subprocess.TimeoutExpired:
        return False, "Timeout while checking video accessibility"
    except json.JSONDecodeError:
        return False, "Failed to parse video information"
    except Exception as e:
        return False, f"Error checking video accessibility: {str(e)}"


def extract_metadata(url: str) -> VideoMetadata:
    """
    Extracts metadata from YouTube video.

    Args:
        url: YouTube URL

    Returns:
        VideoMetadata object with video information

    Raises:
        VideoDownloadError: If metadata extraction fails
    """
    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-download", "--no-warnings", url],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )

        video_info = json.loads(result.stdout)

        # Extract metadata
        title = video_info.get("title", "Unknown")
        duration = float(video_info.get("duration", 0))
        thumbnail = video_info.get("thumbnail", "")

        # Get resolution
        width = video_info.get("width", 0)
        height = video_info.get("height", 0)
        resolution = f"{width}x{height}" if width and height else "unknown"

        # Get format
        ext = video_info.get("ext", "mp4")

        return VideoMetadata(
            title=title,
            duration=duration,
            thumbnail=thumbnail,
            resolution=resolution,
            format=ext,
        )

    except subprocess.CalledProcessError as e:
        raise VideoDownloadError(f"Failed to extract metadata: {e.stderr}")
    except json.JSONDecodeError as e:
        raise VideoDownloadError(f"Failed to parse video metadata: {str(e)}")
    except Exception as e:
        raise VideoDownloadError(f"Error extracting metadata: {str(e)}")


def download_video(url: str, job_id: str) -> DownloadResult:
    """
    Downloads YouTube video and extracts audio.

    Args:
        url: YouTube URL to download
        job_id: Unique job identifier

    Returns:
        DownloadResult with S3 paths and metadata

    Raises:
        VideoDownloadError: If download fails

    Validates: Requirements 1.1, 1.2
    """
    # Create temporary directory for downloads
    with tempfile.TemporaryDirectory() as temp_dir:
        video_path = os.path.join(temp_dir, "video.mp4")
        audio_path = os.path.join(temp_dir, "audio.wav")

        try:
            # Download video
            print(f"Downloading video from {url}")
            subprocess.run(
                [
                    "yt-dlp",
                    "-f",
                    "best[ext=mp4]",
                    "-o",
                    video_path,
                    "--no-warnings",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes timeout
                check=True,
            )

            # Extract audio to WAV format (16kHz mono)
            print("Extracting audio to WAV format")
            subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    video_path,
                    "-vn",  # No video
                    "-acodec",
                    "pcm_s16le",  # PCM 16-bit
                    "-ar",
                    "16000",  # 16kHz sample rate
                    "-ac",
                    "1",  # Mono
                    "-y",  # Overwrite output
                    audio_path,
                ],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes timeout
                check=True,
            )

            # Upload video to S3
            video_s3_key = f"{job_id}/video.mp4"
            print(f"Uploading video to S3: {RAW_VIDEOS_BUCKET}/{video_s3_key}")
            s3_client = get_s3_client()
            s3_client.upload_file(video_path, RAW_VIDEOS_BUCKET, video_s3_key)

            # Upload audio to S3
            audio_s3_key = f"{job_id}/audio.wav"
            print(f"Uploading audio to S3: {RAW_VIDEOS_BUCKET}/{audio_s3_key}")
            s3_client.upload_file(audio_path, RAW_VIDEOS_BUCKET, audio_s3_key)

            # Extract metadata
            metadata = extract_metadata(url)

            return DownloadResult(
                video_s3_path=f"s3://{RAW_VIDEOS_BUCKET}/{video_s3_key}",
                audio_s3_path=f"s3://{RAW_VIDEOS_BUCKET}/{audio_s3_key}",
                metadata=metadata,
                duration_seconds=metadata.duration,
            )

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr if e.stderr else str(e)
            raise VideoDownloadError(f"Download failed: {error_msg}")
        except subprocess.TimeoutExpired:
            raise VideoDownloadError("Download timeout exceeded")
        except ClientError as e:
            raise VideoDownloadError(f"S3 upload failed: {str(e)}")
        except Exception as e:
            raise VideoDownloadError(f"Unexpected error during download: {str(e)}")


def update_job_status(
    job_id: str,
    status: str,
    progress: int,
    current_stage: str,
    error: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Updates job status in DynamoDB.

    Args:
        job_id: Job identifier
        status: Job status (queued, processing, complete, failed)
        progress: Progress percentage (0-100)
        current_stage: Current processing stage
        error: Optional error information
        result: Optional result data
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

    if result:
        update_expr += (
            ", videoMetadata = :metadata, videoS3Path = :video, audioS3Path = :audio"
        )
        expr_attr_values[":metadata"] = result.get("metadata")
        expr_attr_values[":video"] = result.get("video_s3_path")
        expr_attr_values[":audio"] = result.get("audio_s3_path")

    table.update_item(
        Key={"PK": f"JOB#{job_id}", "SK": "METADATA"},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_attr_names,
        ExpressionAttributeValues=expr_attr_values,
    )


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for video download.

    Args:
        event: Lambda event containing jobId and youtubeUrl
        context: Lambda context

    Returns:
        Response with download result or error
    """
    try:
        # Extract parameters
        job_id = event.get("jobId")
        youtube_url = event.get("youtubeUrl")

        if not job_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing jobId parameter"}),
            }

        if not youtube_url:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing youtubeUrl parameter"}),
            }

        print(f"Processing job {job_id} for URL: {youtube_url}")

        # Update status to processing
        update_job_status(job_id, "processing", 10, "download")

        # Validate URL
        try:
            validate_youtube_url(youtube_url)
        except InvalidURLError as e:
            error_info = {
                "stage": "download",
                "message": str(e),
                "timestamp": int(time.time() * 1000),
            }
            update_job_status(job_id, "failed", 0, "download", error=error_info)
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {
                        "error": "Invalid YouTube URL",
                        "details": str(e),
                        "suggestedActions": [
                            "Verify the URL is a valid YouTube link",
                            "Ensure the URL contains a video ID",
                        ],
                    }
                ),
            }

        # Check video accessibility
        is_accessible, access_error = check_video_accessibility(youtube_url)
        if not is_accessible:
            error_info = {
                "stage": "download",
                "message": access_error,
                "timestamp": int(time.time() * 1000),
            }
            update_job_status(job_id, "failed", 0, "download", error=error_info)
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {
                        "error": "Video not accessible",
                        "details": access_error,
                        "suggestedActions": [
                            "Verify the video is public",
                            "Check if the video is available in your region",
                            "Ensure the video is not age-restricted",
                        ],
                    }
                ),
            }

        # Download video
        update_job_status(job_id, "processing", 30, "download")
        result = download_video(youtube_url, job_id)

        # Update job with result
        result_data = {
            "metadata": asdict(result.metadata),
            "video_s3_path": result.video_s3_path,
            "audio_s3_path": result.audio_s3_path,
        }
        update_job_status(job_id, "processing", 100, "download", result=result_data)

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "jobId": job_id,
                    "status": "complete",
                    "result": {
                        "videoS3Path": result.video_s3_path,
                        "audioS3Path": result.audio_s3_path,
                        "metadata": asdict(result.metadata),
                        "durationSeconds": result.duration_seconds,
                    },
                }
            ),
        }

    except VideoDownloadError as e:
        error_info = {
            "stage": "download",
            "message": str(e),
            "timestamp": int(time.time() * 1000),
        }
        if job_id:
            update_job_status(job_id, "failed", 0, "download", error=error_info)

        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "error": "Video download failed",
                    "details": str(e),
                    "suggestedActions": [
                        "Retry the request",
                        "Check if the video is still available",
                        "Contact support if the issue persists",
                    ],
                }
            ),
        }

    except Exception as e:
        error_info = {
            "stage": "download",
            "message": f"Unexpected error: {str(e)}",
            "timestamp": int(time.time() * 1000),
        }
        if job_id:
            update_job_status(job_id, "failed", 0, "download", error=error_info)

        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error", "details": str(e)}),
        }
