"""
Fluff Report Generation Module

Generates comprehensive fluff reports with removed segments, classifications,
time metrics, and before/after comparison data.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
"""

import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List

import boto3
from botocore.exceptions import ClientError


@dataclass
class RemovedSegment:
    """
    Information about a removed segment.

    Attributes:
        start_time: Start time in seconds
        end_time: End time in seconds
        duration: Duration in seconds
        fluff_type: Type of fluff (CTA, ad, tangent, silence, filler, intro, outro)
        confidence: Classification confidence score (0-1)
        transcript: Transcript text for this segment
    """

    start_time: float
    end_time: float
    duration: float
    fluff_type: str
    confidence: float
    transcript: str


@dataclass
class TimeMetrics:
    """
    Time-based metrics for video editing.

    Attributes:
        original_duration: Original video duration in seconds
        edited_duration: Edited video duration in seconds
        time_saved: Time saved by removing fluff in seconds
        retention_percentage: Percentage of original video retained
    """

    original_duration: float
    edited_duration: float
    time_saved: float
    retention_percentage: float


@dataclass
class FluffReport:
    """
    Comprehensive fluff report for a video editing job.

    Attributes:
        job_id: Unique job identifier
        removed_segments: List of removed segments with details
        time_metrics: Time-based metrics
        fluff_by_type: Duration of fluff by type in seconds
        total_segments_removed: Total number of segments removed
        total_segments_kept: Total number of segments kept
    """

    job_id: str
    removed_segments: List[RemovedSegment]
    time_metrics: TimeMetrics
    fluff_by_type: Dict[str, float]
    total_segments_removed: int
    total_segments_kept: int


class FluffReportError(Exception):
    """Base exception for fluff report generation errors."""

    pass


def load_transcript_segments(transcript_s3_path: str) -> List[Dict[str, Any]]:
    """
    Loads transcript segments from S3.

    Args:
        transcript_s3_path: S3 path to transcript JSON

    Returns:
        List of transcript segments

    Raises:
        FluffReportError: If loading fails
    """
    s3 = boto3.client("s3")

    try:
        # Parse S3 URI
        if not transcript_s3_path.startswith("s3://"):
            raise FluffReportError(f"Invalid S3 URI: {transcript_s3_path}")

        uri_parts = transcript_s3_path[5:].split("/", 1)
        bucket = uri_parts[0]
        key = uri_parts[1]

        # Download and parse transcript
        response = s3.get_object(Bucket=bucket, Key=key)
        transcript_data = json.loads(response["Body"].read().decode("utf-8"))

        return transcript_data.get("segments", [])

    except ClientError as e:
        error_msg = e.response.get("Error", {}).get("Message", str(e))
        raise FluffReportError(f"Failed to load transcript: {error_msg}")
    except json.JSONDecodeError as e:
        raise FluffReportError(f"Failed to parse transcript JSON: {str(e)}")
    except Exception as e:
        raise FluffReportError(f"Unexpected error loading transcript: {str(e)}")


def find_transcript_for_segment(
    start_time: float, end_time: float, transcript_segments: List[Dict[str, Any]]
) -> str:
    """
    Finds transcript text for a given time range.

    Args:
        start_time: Segment start time in seconds
        end_time: Segment end time in seconds
        transcript_segments: List of transcript segments with timestamps

    Returns:
        Concatenated transcript text for the time range
    """
    matching_text = []

    for segment in transcript_segments:
        seg_start = segment.get("start_time", 0.0)
        seg_end = segment.get("end_time", 0.0)

        # Check if segment overlaps with time range
        if seg_start < end_time and seg_end > start_time:
            text = segment.get("text", "").strip()
            if text:
                matching_text.append(text)

    return " ".join(matching_text) if matching_text else "[No transcript available]"


def generate_removed_segments(
    classifications: List[Dict[str, Any]], transcript_segments: List[Dict[str, Any]]
) -> List[RemovedSegment]:
    """
    Generates list of removed segments with classifications and transcripts.

    Args:
        classifications: List of segment classifications from analysis
        transcript_segments: List of transcript segments with text

    Returns:
        List of RemovedSegment objects

    Validates: Requirements 6.2, 6.3, 6.4
    """
    removed_segments = []

    for classification in classifications:
        is_fluff = classification.get("is_fluff", False)

        if is_fluff:
            start_time = float(classification.get("start_time", 0.0))
            end_time = float(classification.get("end_time", 0.0))
            duration = end_time - start_time

            fluff_type = classification.get("fluff_type", "unknown")
            confidence = float(classification.get("confidence", 0.0))

            # Find transcript for this segment
            transcript = find_transcript_for_segment(
                start_time=start_time,
                end_time=end_time,
                transcript_segments=transcript_segments,
            )

            removed_segments.append(
                RemovedSegment(
                    start_time=start_time,
                    end_time=end_time,
                    duration=duration,
                    fluff_type=fluff_type,
                    confidence=confidence,
                    transcript=transcript,
                )
            )

    return removed_segments


def calculate_time_metrics(
    original_duration: float, edited_duration: float
) -> TimeMetrics:
    """
    Calculates time-based metrics for video editing.

    Args:
        original_duration: Original video duration in seconds
        edited_duration: Edited video duration in seconds

    Returns:
        TimeMetrics object with calculated values

    Validates: Requirements 6.5, 6.6
    """
    time_saved = original_duration - edited_duration
    retention_percentage = (
        (edited_duration / original_duration) * 100.0 if original_duration > 0 else 0.0
    )

    return TimeMetrics(
        original_duration=original_duration,
        edited_duration=edited_duration,
        time_saved=time_saved,
        retention_percentage=retention_percentage,
    )


def calculate_fluff_by_type(removed_segments: List[RemovedSegment]) -> Dict[str, float]:
    """
    Calculates total duration of fluff by type.

    Args:
        removed_segments: List of removed segments

    Returns:
        Dictionary mapping fluff type to total duration in seconds
    """
    fluff_by_type = {}

    for segment in removed_segments:
        fluff_type = segment.fluff_type
        duration = segment.duration

        fluff_by_type[fluff_type] = fluff_by_type.get(fluff_type, 0.0) + duration

    return fluff_by_type


def generate_fluff_report(
    job_id: str,
    classifications: List[Dict[str, Any]],
    transcript_s3_path: str,
    original_duration: float,
    edited_duration: float,
) -> FluffReport:
    """
    Generates comprehensive fluff report.

    Args:
        job_id: Unique job identifier
        classifications: List of segment classifications from analysis
        transcript_s3_path: S3 path to transcript JSON
        original_duration: Original video duration in seconds
        edited_duration: Edited video duration in seconds

    Returns:
        FluffReport object with all report data

    Raises:
        FluffReportError: If report generation fails

    Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
    """
    try:
        # Load transcript segments
        print(f"Loading transcript from {transcript_s3_path}")
        transcript_segments = load_transcript_segments(transcript_s3_path)

        # Generate removed segments list
        print("Generating removed segments list...")
        removed_segments = generate_removed_segments(
            classifications=classifications, transcript_segments=transcript_segments
        )

        # Calculate time metrics
        print("Calculating time metrics...")
        time_metrics = calculate_time_metrics(
            original_duration=original_duration, edited_duration=edited_duration
        )

        # Calculate fluff by type
        fluff_by_type = calculate_fluff_by_type(removed_segments)

        # Count segments
        total_segments_removed = len(removed_segments)
        total_segments_kept = sum(
            1 for c in classifications if not c.get("is_fluff", False)
        )

        print(
            f"Report generated: {total_segments_removed} removed, "
            f"{total_segments_kept} kept, "
            f"{time_metrics.time_saved:.1f}s saved "
            f"({time_metrics.retention_percentage:.1f}% retained)"
        )

        return FluffReport(
            job_id=job_id,
            removed_segments=removed_segments,
            time_metrics=time_metrics,
            fluff_by_type=fluff_by_type,
            total_segments_removed=total_segments_removed,
            total_segments_kept=total_segments_kept,
        )

    except FluffReportError:
        raise
    except Exception as e:
        raise FluffReportError(f"Failed to generate fluff report: {str(e)}")


def save_fluff_report_to_s3(
    report: FluffReport, s3_bucket: str, s3_key: str
) -> str:
    """
    Saves fluff report to S3 as JSON.

    Args:
        report: FluffReport object to save
        s3_bucket: S3 bucket name
        s3_key: S3 object key

    Returns:
        S3 URI (s3://bucket/key)

    Raises:
        FluffReportError: If save fails

    Validates: Requirements 6.1
    """
    s3 = boto3.client("s3")

    try:
        # Convert report to dictionary
        report_dict = {
            "job_id": report.job_id,
            "removed_segments": [asdict(seg) for seg in report.removed_segments],
            "time_metrics": asdict(report.time_metrics),
            "fluff_by_type": report.fluff_by_type,
            "total_segments_removed": report.total_segments_removed,
            "total_segments_kept": report.total_segments_kept,
        }

        # Convert to JSON
        report_json = json.dumps(report_dict, indent=2)

        # Upload to S3
        s3.put_object(
            Bucket=s3_bucket, Key=s3_key, Body=report_json, ContentType="application/json"
        )

        s3_path = f"s3://{s3_bucket}/{s3_key}"
        print(f"Fluff report saved to {s3_path}")

        return s3_path

    except ClientError as e:
        error_msg = e.response.get("Error", {}).get("Message", str(e))
        raise FluffReportError(f"Failed to save report to S3: {error_msg}")
    except Exception as e:
        raise FluffReportError(f"Unexpected error saving report: {str(e)}")
