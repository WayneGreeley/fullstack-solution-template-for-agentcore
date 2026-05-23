"""
Video Editor Lambda Function

Generates edited video with fluff segments removed using FFmpeg.
Selects keep segments, merges adjacent segments, and re-encodes video.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
"""

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError
from chapter_generator import (
    Chapter,
    embed_chapters_in_video,
    generate_chapters,
    save_chapters_to_s3,
)
from fluff_report import (
    generate_fluff_report,
    save_fluff_report_to_s3,
)

# Environment variables
RAW_VIDEOS_BUCKET = os.environ.get("RAW_VIDEOS_BUCKET")
ANALYSIS_BUCKET = os.environ.get("ANALYSIS_BUCKET")
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET")
JOBS_TABLE = os.environ.get("JOBS_TABLE")

# AWS clients - initialized lazily
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
class TimeRange:
    """
    Time range with start and end timestamps.

    Attributes:
        start: Start time in seconds
        end: End time in seconds
    """

    start: float
    end: float


@dataclass
class EditResult:
    """
    Result of video editing operation.

    Attributes:
        edited_video_s3_path: S3 path to edited video
        keep_segments: List of kept time ranges
        removed_segments: List of removed time ranges
        original_duration: Original video duration in seconds
        edited_duration: Edited video duration in seconds
        time_saved: Time saved by removing fluff in seconds
        chapters: List of chapter markers
        chapters_s3_path: S3 path to chapters JSON
    """

    edited_video_s3_path: str
    keep_segments: List[TimeRange]
    removed_segments: List[TimeRange]
    original_duration: float
    edited_duration: float
    time_saved: float
    chapters: List[Chapter]
    chapters_s3_path: str


class VideoEditError(Exception):
    """Base exception for video editing errors."""

    pass


class SegmentSelectionError(VideoEditError):
    """Raised when segment selection fails."""

    pass


class VideoEncodingError(VideoEditError):
    """Raised when video encoding fails."""

    pass


def select_keep_segments(classifications: List[Dict[str, Any]]) -> List[TimeRange]:
    """
    Selects segments to keep based on fluff classification.

    Args:
        classifications: List of segment classifications from analysis

    Returns:
        List of TimeRange objects for segments to keep

    Raises:
        SegmentSelectionError: If segment selection fails

    Validates: Requirements 5.1
    """
    try:
        keep_segments = []

        for classification in classifications:
            is_fluff = classification.get("is_fluff", False)

            if not is_fluff:
                # Keep this segment
                start_time = float(classification.get("start_time", 0.0))
                end_time = float(classification.get("end_time", 0.0))

                if end_time > start_time:
                    keep_segments.append(TimeRange(start=start_time, end=end_time))

        if not keep_segments:
            raise SegmentSelectionError(
                "No keep segments found - entire video classified as fluff"
            )

        print(f"Selected {len(keep_segments)} segments to keep")
        return keep_segments

    except Exception as e:
        raise SegmentSelectionError(f"Failed to select keep segments: {str(e)}")


def merge_adjacent_segments(
    segments: List[TimeRange], gap_threshold: float = 1.0
) -> List[TimeRange]:
    """
    Merges adjacent segments separated by less than gap_threshold.

    Args:
        segments: List of time ranges to merge
        gap_threshold: Maximum gap in seconds to merge (default: 1.0)

    Returns:
        List of merged time ranges

    Validates: Requirements 5.3
    """
    if not segments:
        return []

    # Sort segments by start time
    sorted_segments = sorted(segments, key=lambda s: s.start)

    merged = []
    current = sorted_segments[0]

    for next_segment in sorted_segments[1:]:
        gap = next_segment.start - current.end

        if gap <= gap_threshold:
            # Merge segments
            current = TimeRange(start=current.start, end=next_segment.end)
        else:
            # Gap too large, save current and start new
            merged.append(current)
            current = next_segment

    # Add final segment
    merged.append(current)

    print(
        f"Merged {len(segments)} segments into {len(merged)} segments "
        f"(gap threshold: {gap_threshold}s)"
    )

    return merged


def validate_chronological_order(segments: List[TimeRange]) -> bool:
    """
    Validates that segments are in chronological order.

    Args:
        segments: List of time ranges to validate

    Returns:
        True if segments are in chronological order

    Raises:
        SegmentSelectionError: If segments are not in chronological order

    Validates: Requirements 5.4
    """
    for i in range(len(segments) - 1):
        current = segments[i]
        next_seg = segments[i + 1]

        if current.end > next_seg.start:
            raise SegmentSelectionError(
                f"Segments not in chronological order: "
                f"segment {i} ends at {current.end}s but "
                f"segment {i + 1} starts at {next_seg.start}s"
            )

    print(f"Validated {len(segments)} segments are in chronological order")
    return True


def create_ffmpeg_concat_file(
    segments: List[TimeRange], video_path: str, temp_dir: str
) -> Tuple[str, List[str]]:
    """
    Creates FFmpeg concat demuxer file and extracts segment files.

    Args:
        segments: List of time ranges to extract
        video_path: Path to original video file
        temp_dir: Temporary directory for segment files

    Returns:
        Tuple of (concat_file_path, list of segment file paths)

    Raises:
        VideoEncodingError: If segment extraction fails
    """
    try:
        segment_files = []
        concat_lines = []

        for i, segment in enumerate(segments):
            segment_file = os.path.join(temp_dir, f"segment_{i:04d}.mp4")
            duration = segment.end - segment.start

            # Extract segment using FFmpeg
            # Use -c copy for fast extraction without re-encoding
            subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    video_path,
                    "-ss",
                    str(segment.start),
                    "-t",
                    str(duration),
                    "-c",
                    "copy",
                    "-avoid_negative_ts",
                    "1",
                    "-y",
                    segment_file,
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=True,
            )

            segment_files.append(segment_file)
            concat_lines.append(f"file '{segment_file}'")

        # Create concat file
        concat_file = os.path.join(temp_dir, "concat.txt")
        with open(concat_file, "w") as f:
            f.write("\n".join(concat_lines))

        print(f"Created concat file with {len(segment_files)} segments")
        return concat_file, segment_files

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        raise VideoEncodingError(f"Failed to extract segments: {error_msg}")
    except subprocess.TimeoutExpired:
        raise VideoEncodingError("Segment extraction timeout exceeded")
    except Exception as e:
        raise VideoEncodingError(f"Unexpected error creating concat file: {str(e)}")


def reencode_video(
    concat_file: str, output_path: str, add_crossfade: bool = True
) -> None:
    """
    Re-encodes video using FFmpeg concat demuxer.

    Args:
        concat_file: Path to FFmpeg concat file
        output_path: Path to output video file
        add_crossfade: Whether to add audio crossfade between segments

    Raises:
        VideoEncodingError: If re-encoding fails

    Validates: Requirements 5.5, 5.6
    """
    try:
        # Build FFmpeg command
        # Use concat demuxer for segment stitching
        # Maintain original quality with -c copy or re-encode with same settings
        ffmpeg_cmd = [
            "ffmpeg",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_file,
        ]

        if add_crossfade:
            # Add audio crossfade filter (0.5s crossfade between segments)
            # Note: This requires re-encoding audio
            ffmpeg_cmd.extend(
                [
                    "-af",
                    "acrossfade=d=0.5",
                    "-c:v",
                    "copy",  # Copy video without re-encoding
                    "-c:a",
                    "aac",  # Re-encode audio with AAC
                    "-b:a",
                    "192k",  # Audio bitrate
                ]
            )
        else:
            # Copy both video and audio without re-encoding
            ffmpeg_cmd.extend(["-c", "copy"])

        ffmpeg_cmd.extend(["-y", output_path])

        # Execute FFmpeg
        print("Re-encoding video with FFmpeg...")
        subprocess.run(
            ffmpeg_cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minutes timeout
            check=True,
        )

        print(f"Video re-encoded successfully: {output_path}")

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        raise VideoEncodingError(f"FFmpeg re-encoding failed: {error_msg}")
    except subprocess.TimeoutExpired:
        raise VideoEncodingError("Video re-encoding timeout exceeded")
    except Exception as e:
        raise VideoEncodingError(f"Unexpected error re-encoding video: {str(e)}")


def get_video_resolution(video_path: str) -> str:
    """
    Gets video resolution using FFprobe.

    Args:
        video_path: Path to video file

    Returns:
        Resolution string (e.g., "1920x1080")

    Raises:
        VideoEditError: If resolution detection fails
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                video_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )

        data = json.loads(result.stdout)
        streams = data.get("streams", [])

        if not streams:
            raise VideoEditError("No video stream found")

        width = streams[0].get("width", 0)
        height = streams[0].get("height", 0)

        return f"{width}x{height}"

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        raise VideoEditError(f"Failed to get video resolution: {error_msg}")
    except Exception as e:
        raise VideoEditError(f"Unexpected error getting resolution: {str(e)}")


def get_video_duration(video_path: str) -> float:
    """
    Gets video duration using FFprobe.

    Args:
        video_path: Path to video file

    Returns:
        Duration in seconds

    Raises:
        VideoEditError: If duration detection fails
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                video_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )

        data = json.loads(result.stdout)
        duration = float(data.get("format", {}).get("duration", 0.0))

        return duration

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        raise VideoEditError(f"Failed to get video duration: {error_msg}")
    except Exception as e:
        raise VideoEditError(f"Unexpected error getting duration: {str(e)}")


def download_from_s3(s3_path: str, local_path: str) -> None:
    """
    Downloads file from S3 to local path.

    Args:
        s3_path: S3 URI (s3://bucket/key)
        local_path: Local file path to save to

    Raises:
        VideoEditError: If download fails
    """
    s3 = get_s3_client()

    try:
        # Parse S3 URI
        if not s3_path.startswith("s3://"):
            raise VideoEditError(f"Invalid S3 URI: {s3_path}")

        uri_parts = s3_path[5:].split("/", 1)
        bucket = uri_parts[0]
        key = uri_parts[1]

        # Download file
        s3.download_file(bucket, key, local_path)
        print(f"Downloaded {s3_path} to {local_path}")

    except ClientError as e:
        error_msg = e.response.get("Error", {}).get("Message", str(e))
        raise VideoEditError(f"Failed to download from S3: {error_msg}")
    except Exception as e:
        raise VideoEditError(f"Unexpected error downloading from S3: {str(e)}")


def upload_to_s3(local_path: str, s3_bucket: str, s3_key: str) -> str:
    """
    Uploads file from local path to S3.

    Args:
        local_path: Local file path
        s3_bucket: S3 bucket name
        s3_key: S3 object key

    Returns:
        S3 URI (s3://bucket/key)

    Raises:
        VideoEditError: If upload fails
    """
    s3 = get_s3_client()

    try:
        s3.upload_file(local_path, s3_bucket, s3_key)
        s3_path = f"s3://{s3_bucket}/{s3_key}"
        print(f"Uploaded {local_path} to {s3_path}")
        return s3_path

    except ClientError as e:
        error_msg = e.response.get("Error", {}).get("Message", str(e))
        raise VideoEditError(f"Failed to upload to S3: {error_msg}")
    except Exception as e:
        raise VideoEditError(f"Unexpected error uploading to S3: {str(e)}")


def load_analysis_result(analysis_s3_path: str) -> Dict[str, Any]:
    """
    Loads analysis result from S3.

    Args:
        analysis_s3_path: S3 path to analysis JSON

    Returns:
        Parsed analysis data

    Raises:
        VideoEditError: If loading fails
    """
    s3 = get_s3_client()

    try:
        # Parse S3 URI
        if not analysis_s3_path.startswith("s3://"):
            raise VideoEditError(f"Invalid S3 URI: {analysis_s3_path}")

        uri_parts = analysis_s3_path[5:].split("/", 1)
        bucket = uri_parts[0]
        key = uri_parts[1]

        # Download and parse analysis
        response = s3.get_object(Bucket=bucket, Key=key)
        analysis_data = json.loads(response["Body"].read().decode("utf-8"))

        return analysis_data

    except ClientError as e:
        error_msg = e.response.get("Error", {}).get("Message", str(e))
        raise VideoEditError(f"Failed to load analysis: {error_msg}")
    except json.JSONDecodeError as e:
        raise VideoEditError(f"Failed to parse analysis JSON: {str(e)}")
    except Exception as e:
        raise VideoEditError(f"Unexpected error loading analysis: {str(e)}")


def create_cut(
    video_s3_path: str, analysis_s3_path: str, transcript_s3_path: str, job_id: str
) -> EditResult:
    """
    Creates edited video with fluff segments removed.

    Args:
        video_s3_path: S3 path to original video
        analysis_s3_path: S3 path to analysis results
        transcript_s3_path: S3 path to transcript JSON
        job_id: Unique job identifier

    Returns:
        EditResult with edited video details

    Raises:
        VideoEditError: If editing fails

    Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
    """
    # Create temporary directory for processing
    with tempfile.TemporaryDirectory() as temp_dir:
        # Download video
        video_path = os.path.join(temp_dir, "original.mp4")
        print(f"Downloading video from {video_s3_path}")
        download_from_s3(video_s3_path, video_path)

        # Get original video properties
        original_duration = get_video_duration(video_path)
        original_resolution = get_video_resolution(video_path)
        print(
            f"Original video: {original_duration}s, resolution: {original_resolution}"
        )

        # Load analysis results
        print(f"Loading analysis from {analysis_s3_path}")
        analysis_data = load_analysis_result(analysis_s3_path)
        classifications = analysis_data.get("segments", [])

        if not classifications:
            raise VideoEditError("No segment classifications found in analysis")

        # Select keep segments
        print("Selecting keep segments...")
        keep_segments = select_keep_segments(classifications)

        # Merge adjacent segments
        print("Merging adjacent segments...")
        merged_segments = merge_adjacent_segments(
            segments=keep_segments, gap_threshold=1.0
        )

        # Validate chronological order
        validate_chronological_order(merged_segments)

        # Calculate removed segments
        removed_segments = []
        last_end = 0.0

        for keep_seg in merged_segments:
            if keep_seg.start > last_end:
                # Gap between segments = removed content
                removed_segments.append(TimeRange(start=last_end, end=keep_seg.start))
            last_end = keep_seg.end

        # Add final removed segment if video continues after last keep segment
        if last_end < original_duration:
            removed_segments.append(TimeRange(start=last_end, end=original_duration))

        # Create FFmpeg concat file and extract segments
        print("Extracting video segments...")
        concat_file, segment_files = create_ffmpeg_concat_file(
            segments=merged_segments, video_path=video_path, temp_dir=temp_dir
        )

        # Re-encode video
        output_path = os.path.join(temp_dir, "edited.mp4")
        print("Re-encoding video with segment stitching...")
        reencode_video(concat_file=concat_file, output_path=output_path)

        # Verify output video properties
        edited_duration = get_video_duration(output_path)
        edited_resolution = get_video_resolution(output_path)
        print(f"Edited video: {edited_duration}s, resolution: {edited_resolution}")

        # Validate resolution preservation (Requirement 5.6)
        if edited_resolution != original_resolution:
            raise VideoEditError(
                f"Resolution not preserved: original={original_resolution}, "
                f"edited={edited_resolution}"
            )

        # Generate chapters (Requirements 7.1, 7.2, 7.3, 7.4)
        print("Generating chapter markers...")
        chapters = generate_chapters(
            keep_segments=merged_segments,
            transcript_s3_path=transcript_s3_path,
            edited_duration=edited_duration,
        )

        # Embed chapters in video (Requirement 7.5)
        if chapters:
            print("Embedding chapters in video metadata...")
            output_with_chapters = os.path.join(temp_dir, "edited_with_chapters.mp4")
            embed_chapters_in_video(
                video_path=output_path,
                chapters=chapters,
                output_path=output_with_chapters,
            )
            # Use video with chapters as final output
            output_path = output_with_chapters
        else:
            print("No chapters generated, skipping chapter embedding")

        # Upload edited video to S3
        s3_key = f"{job_id}/edited-video.mp4"
        print("Uploading edited video to S3...")
        edited_video_s3_path = upload_to_s3(
            local_path=output_path, s3_bucket=OUTPUT_BUCKET, s3_key=s3_key
        )

        # Calculate time saved
        time_saved = original_duration - edited_duration

        # Generate fluff report (Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6)
        print("Generating fluff report...")
        fluff_report = generate_fluff_report(
            job_id=job_id,
            classifications=classifications,
            transcript_s3_path=transcript_s3_path,
            original_duration=original_duration,
            edited_duration=edited_duration,
        )

        # Save fluff report to S3
        report_s3_key = f"{job_id}/fluff-report.json"
        fluff_report_s3_path = save_fluff_report_to_s3(
            report=fluff_report, s3_bucket=OUTPUT_BUCKET, s3_key=report_s3_key
        )
        print(f"Fluff report saved to {fluff_report_s3_path}")

        # Save chapters to S3
        chapters_s3_path = ""
        if chapters:
            chapters_s3_key = f"{job_id}/chapters.json"
            chapters_s3_path = save_chapters_to_s3(
                chapters=chapters, s3_bucket=OUTPUT_BUCKET, s3_key=chapters_s3_key
            )
            print(f"Chapters saved to {chapters_s3_path}")

        return EditResult(
            edited_video_s3_path=edited_video_s3_path,
            keep_segments=merged_segments,
            removed_segments=removed_segments,
            original_duration=original_duration,
            edited_duration=edited_duration,
            time_saved=time_saved,
            chapters=chapters,
            chapters_s3_path=chapters_s3_path,
        )


def update_job_status(
    job_id: str,
    status: str,
    progress: int,
    current_stage: str,
    error: Optional[Dict[str, Any]] = None,
    edited_video_s3_path: Optional[str] = None,
) -> None:
    """
    Updates job status in DynamoDB.

    Args:
        job_id: Job identifier
        status: Job status (queued, processing, complete, failed)
        progress: Progress percentage (0-100)
        current_stage: Current processing stage
        error: Optional error information
        edited_video_s3_path: Optional S3 path to edited video
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

    if edited_video_s3_path:
        update_expr += ", editedVideoS3Path = :edited"
        expr_attr_values[":edited"] = edited_video_s3_path

    table.update_item(
        Key={"PK": f"JOB#{job_id}", "SK": "METADATA"},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_attr_names,
        ExpressionAttributeValues=expr_attr_values,
    )


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for video editing.

    Args:
        event: Lambda event containing jobId, videoS3Path, analysisS3Path
        context: Lambda context

    Returns:
        Response with edit result or error
    """
    try:
        # Extract parameters
        job_id = event.get("jobId")
        video_s3_path = event.get("videoS3Path")
        analysis_s3_path = event.get("analysisS3Path")
        transcript_s3_path = event.get("transcriptS3Path")

        if not job_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing jobId parameter"}),
            }

        if not video_s3_path:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing videoS3Path parameter"}),
            }

        if not analysis_s3_path:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing analysisS3Path parameter"}),
            }

        if not transcript_s3_path:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing transcriptS3Path parameter"}),
            }

        print(f"Processing video editing for job {job_id}")
        print(f"Video S3 path: {video_s3_path}")
        print(f"Analysis S3 path: {analysis_s3_path}")
        print(f"Transcript S3 path: {transcript_s3_path}")

        # Update status to processing
        update_job_status(job_id, "processing", 10, "edit")

        # Create edited video
        edit_result = create_cut(
            video_s3_path, analysis_s3_path, transcript_s3_path, job_id
        )

        # Update job with result
        update_job_status(
            job_id,
            "processing",
            100,
            "edit",
            edited_video_s3_path=edit_result.edited_video_s3_path,
        )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "jobId": job_id,
                    "status": "complete",
                    "result": {
                        "editedVideoS3Path": edit_result.edited_video_s3_path,
                        "originalDuration": edit_result.original_duration,
                        "editedDuration": edit_result.edited_duration,
                        "timeSaved": edit_result.time_saved,
                        "keepSegmentCount": len(edit_result.keep_segments),
                        "removedSegmentCount": len(edit_result.removed_segments),
                        "chapterCount": len(edit_result.chapters),
                        "chaptersS3Path": edit_result.chapters_s3_path,
                    },
                }
            ),
        }

    except VideoEditError as e:
        error_info = {
            "stage": "edit",
            "message": str(e),
            "timestamp": int(time.time() * 1000),
        }
        if job_id:
            update_job_status(job_id, "failed", 0, "edit", error=error_info)

        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "error": "Video editing failed",
                    "details": str(e),
                    "suggestedActions": [
                        "Verify video and analysis files are accessible in S3",
                        "Check FFmpeg is available in Lambda environment",
                        "Retry the request",
                        "Contact support if the issue persists",
                    ],
                }
            ),
        }

    except Exception as e:
        error_info = {
            "stage": "edit",
            "message": f"Unexpected error: {str(e)}",
            "timestamp": int(time.time() * 1000),
        }
        if job_id:
            update_job_status(job_id, "failed", 0, "edit", error=error_info)

        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error", "details": str(e)}),
        }
