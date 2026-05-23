"""
Chapter Generation Module

Analyzes keep segments to identify thematic sections and generates
descriptive chapter titles using Amazon Nova 2 Lite. Aligns chapter
timestamps with edited video and embeds markers in video metadata.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
"""

import json
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from typing import Any, Dict, List

import boto3
from botocore.exceptions import ClientError


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
class Chapter:
    """
    Chapter marker with timestamp and title.

    Attributes:
        timestamp: Chapter start time in seconds (relative to edited video)
        title: Descriptive chapter title
        duration: Chapter duration in seconds
    """

    timestamp: float
    title: str
    duration: float


class ChapterGenerationError(Exception):
    """Base exception for chapter generation errors."""

    pass


def load_transcript_segments(transcript_s3_path: str) -> List[Dict[str, Any]]:
    """
    Loads transcript segments from S3.

    Args:
        transcript_s3_path: S3 path to transcript JSON

    Returns:
        List of transcript segments

    Raises:
        ChapterGenerationError: If loading fails
    """
    s3 = boto3.client("s3")

    try:
        # Parse S3 URI
        if not transcript_s3_path.startswith("s3://"):
            raise ChapterGenerationError(f"Invalid S3 URI: {transcript_s3_path}")

        uri_parts = transcript_s3_path[5:].split("/", 1)
        bucket = uri_parts[0]
        key = uri_parts[1]

        # Download and parse transcript
        response = s3.get_object(Bucket=bucket, Key=key)
        transcript_data = json.loads(response["Body"].read().decode("utf-8"))

        return transcript_data.get("segments", [])

    except ClientError as e:
        error_msg = e.response.get("Error", {}).get("Message", str(e))
        raise ChapterGenerationError(f"Failed to load transcript: {error_msg}")
    except json.JSONDecodeError as e:
        raise ChapterGenerationError(f"Failed to parse transcript JSON: {str(e)}")
    except Exception as e:
        raise ChapterGenerationError(f"Unexpected error loading transcript: {str(e)}")


def get_transcript_for_segment(
    start_time: float, end_time: float, transcript_segments: List[Dict[str, Any]]
) -> str:
    """
    Gets transcript text for a given time range.

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

    return " ".join(matching_text) if matching_text else ""


def identify_thematic_sections(
    keep_segments: List[TimeRange],
    transcript_segments: List[Dict[str, Any]],
    min_chapter_duration: float = 300.0,
) -> List[TimeRange]:
    """
    Identifies thematic sections from keep segments.

    Groups keep segments into larger thematic sections based on
    minimum chapter duration (default: 5 minutes = 300 seconds).

    Args:
        keep_segments: List of keep segments from video editing
        transcript_segments: List of transcript segments
        min_chapter_duration: Minimum duration for a chapter in seconds

    Returns:
        List of TimeRange objects representing thematic sections

    Validates: Requirements 7.1, 7.4
    """
    if not keep_segments:
        return []

    thematic_sections = []
    current_section_start = keep_segments[0].start
    current_section_end = keep_segments[0].end

    for i in range(1, len(keep_segments)):
        segment = keep_segments[i]
        current_duration = current_section_end - current_section_start

        # Check if we should start a new section
        if current_duration >= min_chapter_duration:
            # Save current section and start new one
            thematic_sections.append(
                TimeRange(start=current_section_start, end=current_section_end)
            )
            current_section_start = segment.start
            current_section_end = segment.end
        else:
            # Extend current section
            current_section_end = segment.end

    # Add final section
    thematic_sections.append(
        TimeRange(start=current_section_start, end=current_section_end)
    )

    print(
        f"Identified {len(thematic_sections)} thematic sections "
        f"(min duration: {min_chapter_duration}s)"
    )

    return thematic_sections


def generate_chapter_title_with_nova(
    section_transcript: str, section_index: int
) -> str:
    """
    Generates descriptive chapter title using Amazon Nova 2 Lite.

    Args:
        section_transcript: Transcript text for the section
        section_index: Index of the section (for fallback)

    Returns:
        Descriptive chapter title

    Validates: Requirements 7.2
    """
    try:
        # Use Amazon Bedrock with Nova 2 Lite model
        bedrock = boto3.client("bedrock-runtime")

        # Truncate transcript if too long (max 1000 chars for title generation)
        truncated_transcript = (
            section_transcript[:1000] + "..."
            if len(section_transcript) > 1000
            else section_transcript
        )

        # Prompt for chapter title generation
        prompt = f"""Based on the following video transcript excerpt, generate a concise, descriptive chapter title (maximum 60 characters).
The title should capture the main topic or theme discussed in this section.

Transcript:
{truncated_transcript}

Generate only the chapter title, nothing else."""

        # Call Nova 2 Lite
        request_body = {
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {"maxTokens": 50, "temperature": 0.7},
        }

        response = bedrock.invoke_model(
            modelId="us.amazon.nova-lite-v1:0",
            body=json.dumps(request_body),
            contentType="application/json",
            accept="application/json",
        )

        response_body = json.loads(response["body"].read())
        title = response_body.get("output", {}).get("message", {}).get("content", [{}])[0].get("text", "").strip()

        # Clean up title
        title = title.replace('"', "").replace("'", "").strip()

        # Limit title length
        if len(title) > 60:
            title = title[:57] + "..."

        # Validate title is not empty
        if not title:
            raise ChapterGenerationError("Nova returned empty title")

        print(f"Generated chapter title: {title}")
        return title

    except Exception as e:
        # Fallback to generic title if Nova fails
        fallback_title = f"Chapter {section_index + 1}"
        print(f"Failed to generate title with Nova: {e}. Using fallback: {fallback_title}")
        return fallback_title


def align_chapters_with_edited_video(
    thematic_sections: List[TimeRange], keep_segments: List[TimeRange]
) -> List[TimeRange]:
    """
    Aligns chapter timestamps with edited video timeline.

    Converts original video timestamps to edited video timestamps
    by calculating cumulative duration of keep segments.

    Args:
        thematic_sections: Thematic sections with original timestamps
        keep_segments: Keep segments from video editing

    Returns:
        List of TimeRange objects with edited video timestamps

    Validates: Requirements 7.3
    """
    aligned_chapters = []

    for section in thematic_sections:
        # Calculate edited video timestamp for section start
        edited_timestamp = 0.0

        for keep_seg in keep_segments:
            if keep_seg.end <= section.start:
                # This keep segment is entirely before the section
                edited_timestamp += keep_seg.end - keep_seg.start
            elif keep_seg.start < section.start < keep_seg.end:
                # Section starts within this keep segment
                edited_timestamp += section.start - keep_seg.start
                break
            else:
                # Section starts after this keep segment
                break

        # Calculate duration in edited video
        edited_duration = 0.0
        for keep_seg in keep_segments:
            if keep_seg.start >= section.end:
                # Keep segment is after section
                break
            elif keep_seg.end <= section.start:
                # Keep segment is before section
                continue
            else:
                # Keep segment overlaps with section
                overlap_start = max(keep_seg.start, section.start)
                overlap_end = min(keep_seg.end, section.end)
                edited_duration += overlap_end - overlap_start

        aligned_chapters.append(
            TimeRange(start=edited_timestamp, end=edited_timestamp + edited_duration)
        )

    print(f"Aligned {len(aligned_chapters)} chapters with edited video timeline")
    return aligned_chapters


def generate_chapters(
    keep_segments: List[TimeRange],
    transcript_s3_path: str,
    edited_duration: float,
) -> List[Chapter]:
    """
    Generates chapter markers for edited video.

    Args:
        keep_segments: List of keep segments from video editing
        transcript_s3_path: S3 path to transcript JSON
        edited_duration: Total duration of edited video in seconds

    Returns:
        List of Chapter objects with timestamps and titles

    Raises:
        ChapterGenerationError: If chapter generation fails

    Validates: Requirements 7.1, 7.2, 7.3, 7.4
    """
    try:
        # Load transcript segments
        print(f"Loading transcript from {transcript_s3_path}")
        transcript_segments = load_transcript_segments(transcript_s3_path)

        # Identify thematic sections (minimum 5 minutes per chapter)
        print("Identifying thematic sections...")
        thematic_sections = identify_thematic_sections(
            keep_segments=keep_segments,
            transcript_segments=transcript_segments,
            min_chapter_duration=300.0,  # 5 minutes
        )

        # Align chapters with edited video timeline
        print("Aligning chapters with edited video...")
        aligned_sections = align_chapters_with_edited_video(
            thematic_sections=thematic_sections, keep_segments=keep_segments
        )

        # Generate chapter titles using Nova
        chapters = []
        for i, (original_section, aligned_section) in enumerate(
            zip(thematic_sections, aligned_sections)
        ):
            # Get transcript for this section
            section_transcript = get_transcript_for_segment(
                start_time=original_section.start,
                end_time=original_section.end,
                transcript_segments=transcript_segments,
            )

            # Generate title using Nova
            title = generate_chapter_title_with_nova(
                section_transcript=section_transcript, section_index=i
            )

            # Create chapter
            chapter = Chapter(
                timestamp=aligned_section.start,
                title=title,
                duration=aligned_section.end - aligned_section.start,
            )
            chapters.append(chapter)

        # Validate minimum chapter density (1 per 5 minutes)
        expected_min_chapters = max(1, int(edited_duration / 300.0))
        if len(chapters) < expected_min_chapters:
            print(
                f"Warning: Generated {len(chapters)} chapters, "
                f"expected at least {expected_min_chapters} "
                f"for {edited_duration}s video"
            )

        print(f"Generated {len(chapters)} chapters for edited video")
        return chapters

    except ChapterGenerationError:
        raise
    except Exception as e:
        raise ChapterGenerationError(f"Failed to generate chapters: {str(e)}")


def embed_chapters_in_video(
    video_path: str, chapters: List[Chapter], output_path: str
) -> None:
    """
    Embeds chapter markers in video metadata using FFmpeg.

    Args:
        video_path: Path to input video file
        chapters: List of Chapter objects
        output_path: Path to output video file with chapters

    Raises:
        ChapterGenerationError: If embedding fails

    Validates: Requirements 7.5
    """
    try:
        # Create FFmpeg metadata file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as metadata_file:
            metadata_path = metadata_file.name

            # Write metadata in FFmpeg format
            metadata_file.write(";FFMETADATA1\n")

            for chapter in chapters:
                # Convert timestamp to milliseconds
                start_ms = int(chapter.timestamp * 1000)
                end_ms = int((chapter.timestamp + chapter.duration) * 1000)

                # Write chapter metadata
                metadata_file.write("[CHAPTER]\n")
                metadata_file.write("TIMEBASE=1/1000\n")
                metadata_file.write(f"START={start_ms}\n")
                metadata_file.write(f"END={end_ms}\n")
                metadata_file.write(f"title={chapter.title}\n")

        # Embed metadata using FFmpeg
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                video_path,
                "-i",
                metadata_path,
                "-map_metadata",
                "1",
                "-codec",
                "copy",
                "-y",
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )

        # Clean up metadata file
        os.unlink(metadata_path)

        print(f"Embedded {len(chapters)} chapters in video metadata")

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        raise ChapterGenerationError(f"Failed to embed chapters: {error_msg}")
    except subprocess.TimeoutExpired:
        raise ChapterGenerationError("Chapter embedding timeout exceeded")
    except Exception as e:
        raise ChapterGenerationError(f"Unexpected error embedding chapters: {str(e)}")


def save_chapters_to_s3(
    chapters: List[Chapter], s3_bucket: str, s3_key: str
) -> str:
    """
    Saves chapters to S3 as JSON.

    Args:
        chapters: List of Chapter objects
        s3_bucket: S3 bucket name
        s3_key: S3 object key

    Returns:
        S3 URI (s3://bucket/key)

    Raises:
        ChapterGenerationError: If save fails
    """
    s3 = boto3.client("s3")

    try:
        # Convert chapters to dictionary
        chapters_dict = {"chapters": [asdict(chapter) for chapter in chapters]}

        # Convert to JSON
        chapters_json = json.dumps(chapters_dict, indent=2)

        # Upload to S3
        s3.put_object(
            Bucket=s3_bucket,
            Key=s3_key,
            Body=chapters_json,
            ContentType="application/json",
        )

        s3_path = f"s3://{s3_bucket}/{s3_key}"
        print(f"Chapters saved to {s3_path}")

        return s3_path

    except ClientError as e:
        error_msg = e.response.get("Error", {}).get("Message", str(e))
        raise ChapterGenerationError(f"Failed to save chapters to S3: {error_msg}")
    except Exception as e:
        raise ChapterGenerationError(f"Unexpected error saving chapters: {str(e)}")
