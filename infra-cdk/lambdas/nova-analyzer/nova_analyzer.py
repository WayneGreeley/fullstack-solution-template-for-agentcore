"""
Nova Analysis Lambda Function

Analyzes video content using Amazon Nova for multimodal embeddings and semantic analysis.
Extracts video frames, generates embeddings, computes semantic similarity, and detects fluff.

Requirements: 3.1, 3.2, 3.3, 3.4
"""

import base64
import io
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import boto3
import numpy as np
from botocore.exceptions import ClientError
from PIL import Image

# Environment variables
RAW_VIDEOS_BUCKET = os.environ.get("RAW_VIDEOS_BUCKET")
TRANSCRIPTS_BUCKET = os.environ.get("TRANSCRIPTS_BUCKET")
ANALYSIS_BUCKET = os.environ.get("ANALYSIS_BUCKET")
JOBS_TABLE = os.environ.get("JOBS_TABLE")

# AWS clients - initialized lazily
_s3_client = None
_bedrock_runtime = None
_dynamodb = None


def get_s3_client():
    """Get or create S3 client."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3")
    return _s3_client


def get_bedrock_runtime():
    """Get or create Bedrock Runtime client."""
    global _bedrock_runtime
    if _bedrock_runtime is None:
        _bedrock_runtime = boto3.client("bedrock-runtime")
    return _bedrock_runtime


def get_dynamodb_resource():
    """Get or create DynamoDB resource."""
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb


class FluffType(Enum):
    """Enumeration of fluff content types."""

    CTA = "call_to_action"
    AD = "advertisement"
    TANGENT = "tangent"
    SILENCE = "silence"
    FILLER = "filler"
    INTRO = "intro"
    OUTRO = "outro"


@dataclass
class Embedding:
    """
    Multimodal embedding for a video segment.

    Attributes:
        segment_id: Unique identifier for the segment
        embedding_vector: Embedding vector (1024 dimensions for Nova)
        modalities: List of modalities included (visual, audio, text)
    """

    segment_id: str
    embedding_vector: List[float]
    modalities: List[str]


@dataclass
class FluffDetection:
    """
    Detected fluff pattern in transcript.

    Attributes:
        pattern_type: Type of fluff (CTA, ad, intro, outro, filler)
        start_time: Start time in seconds
        end_time: End time in seconds
        confidence: Confidence score (0-1)
        matched_text: Text that matched the pattern
    """

    pattern_type: str
    start_time: float
    end_time: float
    confidence: float
    matched_text: str


@dataclass
class SegmentClassification:
    """
    Classification result for a video segment.

    Attributes:
        segment_id: Unique identifier for the segment
        start_time: Start time in seconds
        end_time: End time in seconds
        is_fluff: Whether segment is classified as fluff
        fluff_type: Type of fluff if is_fluff is True
        confidence: Classification confidence (0-1)
        relevance_score: Relevance to main topic (0-1)
        reasoning: Explanation of classification decision
    """

    segment_id: str
    start_time: float
    end_time: float
    is_fluff: bool
    fluff_type: Optional[str]
    confidence: float
    relevance_score: float
    reasoning: str


@dataclass
class AnalysisResult:
    """
    Complete analysis result for a video.

    Attributes:
        segments: List of classified segments
        main_topic: Extracted main topic of the video
        total_fluff_duration: Total duration of fluff in seconds
        fluff_by_type: Duration of each fluff type
    """

    segments: List[SegmentClassification]
    main_topic: str
    total_fluff_duration: float
    fluff_by_type: Dict[str, float]


class NovaAnalysisError(Exception):
    """Base exception for Nova analysis errors."""

    pass


class EmbeddingError(NovaAnalysisError):
    """Raised when embedding generation fails."""

    pass


class FrameExtractionError(NovaAnalysisError):
    """Raised when video frame extraction fails."""

    pass


# Fluff detection patterns
FLUFF_PATTERNS = {
    "CTA": [
        r"like\s+and\s+subscribe",
        r"hit\s+the\s+bell",
        r"smash\s+that\s+like",
        r"comment\s+below",
        r"leave\s+a\s+comment",
        r"don't\s+forget\s+to\s+subscribe",
    ],
    "AD": [
        r"sponsor(?:ed|ship)?",
        r"promo\s+code",
        r"affiliate\s+link",
        r"discount\s+code",
        r"use\s+code",
        r"check\s+out\s+the\s+link",
    ],
    "INTRO": [
        r"hey\s+guys",
        r"what's\s+up\s+(?:guys|everyone)",
        r"welcome\s+back",
        r"hello\s+(?:everyone|guys)",
        r"good\s+(?:morning|afternoon|evening)",
    ],
    "OUTRO": [
        r"see\s+you\s+(?:next|in\s+the\s+next)",
        r"that's\s+all\s+for\s+(?:today|now)",
        r"thanks\s+for\s+watching",
        r"catch\s+you\s+(?:later|next\s+time)",
        r"until\s+next\s+time",
    ],
    "FILLER": [
        r"(?:um|uh|er|ah){2,}",
        r"you\s+know\s+what\s+I\s+mean",
        r"like\s+I\s+said",
        r"as\s+I\s+mentioned",
    ],
}


def extract_video_frames(video_path: str, fps: int = 1) -> List[str]:
    """
    Extracts video frames at specified FPS using FFmpeg.

    Args:
        video_path: Path to video file
        fps: Frames per second to extract (default: 1)

    Returns:
        List of paths to extracted frame images

    Raises:
        FrameExtractionError: If frame extraction fails

    Validates: Requirements 3.1, 3.2
    """
    try:
        # Create temporary directory for frames
        frames_dir = tempfile.mkdtemp()
        frame_pattern = os.path.join(frames_dir, "frame_%04d.jpg")

        # Extract frames using FFmpeg
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                video_path,
                "-vf",
                f"fps={fps}",
                "-q:v",
                "2",  # High quality JPEG
                frame_pattern,
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )

        # Get list of extracted frames
        frame_files = sorted(
            [
                os.path.join(frames_dir, f)
                for f in os.listdir(frames_dir)
                if f.startswith("frame_") and f.endswith(".jpg")
            ]
        )

        if not frame_files:
            raise FrameExtractionError("No frames extracted from video")

        print(f"Extracted {len(frame_files)} frames at {fps} FPS")
        return frame_files

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        raise FrameExtractionError(f"FFmpeg frame extraction failed: {error_msg}")
    except subprocess.TimeoutExpired:
        raise FrameExtractionError("Frame extraction timeout exceeded")
    except Exception as e:
        raise FrameExtractionError(f"Unexpected error extracting frames: {str(e)}")


def encode_image_to_base64(image_path: str) -> str:
    """
    Encodes image file to base64 string.

    Args:
        image_path: Path to image file

    Returns:
        Base64 encoded image string
    """
    with Image.open(image_path) as img:
        # Resize if too large (max 2048x2048 for Nova)
        max_size = 2048
        if img.width > max_size or img.height > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

        # Convert to RGB if needed
        if img.mode != "RGB":
            img = img.convert("RGB")

        # Encode to base64
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")


def generate_multimodal_embedding(
    frame_path: str, transcript_text: str, bedrock_client
) -> List[float]:
    """
    Generates Nova multimodal embedding for a segment.

    Args:
        frame_path: Path to video frame image
        transcript_text: Transcript text for the segment
        bedrock_client: Bedrock Runtime client

    Returns:
        Embedding vector (1024 dimensions)

    Raises:
        EmbeddingError: If embedding generation fails

    Validates: Requirements 3.1, 3.2
    """
    try:
        # Encode frame to base64
        frame_base64 = encode_image_to_base64(frame_path)

        # Prepare multimodal input for Nova
        # Note: Using Nova Canvas for multimodal embeddings
        request_body = {
            "inputText": transcript_text,
            "inputImage": frame_base64,
            "embeddingConfig": {"outputEmbeddingLength": 1024},
        }

        # Call Nova embedding model
        response = bedrock_client.invoke_model(
            modelId="amazon.nova-canvas-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps(request_body),
        )

        # Parse response
        response_body = json.loads(response["body"].read())
        embedding = response_body.get("embedding", [])

        if not embedding or len(embedding) != 1024:
            raise EmbeddingError(f"Invalid embedding dimension: {len(embedding)}")

        return embedding

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        error_msg = e.response.get("Error", {}).get("Message", str(e))
        raise EmbeddingError(f"Bedrock API error: {error_code} - {error_msg}")
    except Exception as e:
        raise EmbeddingError(f"Unexpected error generating embedding: {str(e)}")


def compute_semantic_similarity(
    embedding1: List[float], embedding2: List[float]
) -> float:
    """
    Computes cosine similarity between two embeddings.

    Args:
        embedding1: First embedding vector
        embedding2: Second embedding vector

    Returns:
        Similarity score between 0 and 1

    Validates: Requirements 3.3
    """
    vec1 = np.array(embedding1)
    vec2 = np.array(embedding2)

    # Compute cosine similarity
    dot_product = np.dot(vec1, vec2)
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)

    if norm1 == 0 or norm2 == 0:
        return 0.0

    similarity = dot_product / (norm1 * norm2)

    # Normalize to 0-1 range (cosine similarity is -1 to 1)
    return (similarity + 1) / 2


def extract_main_topic(transcript_text: str, bedrock_client) -> str:
    """
    Extracts main topic from transcript using Nova 2 Lite.

    Args:
        transcript_text: Full transcript text
        bedrock_client: Bedrock Runtime client

    Returns:
        Main topic string

    Raises:
        NovaAnalysisError: If topic extraction fails

    Validates: Requirements 3.4
    """
    try:
        # Prepare prompt for Nova 2 Lite
        prompt = f"""Analyze this video transcript and identify the main topic in 1-2 sentences.
Be specific and concise.

Transcript:
{transcript_text[:2000]}  # First 2000 chars to stay within limits

Main topic:"""

        request_body = {
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {
                "maxTokens": 100,
                "temperature": 0.1,
            },
        }

        # Call Nova 2 Lite
        response = bedrock_client.invoke_model(
            modelId="us.amazon.nova-lite-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps(request_body),
        )

        # Parse response
        response_body = json.loads(response["body"].read())
        main_topic = (
            response_body.get("output", {})
            .get("message", {})
            .get("content", [{}])[0]
            .get("text", "")
            .strip()
        )

        if not main_topic:
            raise NovaAnalysisError("Failed to extract main topic from response")

        return main_topic

    except ClientError as e:
        error_msg = e.response.get("Error", {}).get("Message", str(e))
        raise NovaAnalysisError(f"Failed to extract main topic: {error_msg}")
    except Exception as e:
        raise NovaAnalysisError(f"Unexpected error extracting topic: {str(e)}")


def score_segment_relevance(
    segment_text: str,
    main_topic: str,
    segment_embedding: List[float],
    topic_embedding: List[float],
    bedrock_client,
) -> float:
    """
    Scores segment relevance to main topic using embeddings and Nova reasoning.

    Args:
        segment_text: Segment transcript text
        main_topic: Main topic of the video
        segment_embedding: Embedding for the segment
        topic_embedding: Embedding for the main topic
        bedrock_client: Bedrock Runtime client

    Returns:
        Relevance score between 0 and 1

    Validates: Requirements 3.4
    """
    # Compute embedding similarity
    embedding_similarity = compute_semantic_similarity(
        segment_embedding, topic_embedding
    )

    # Use Nova 2 Lite for semantic reasoning
    try:
        prompt = f"""Rate how relevant this segment is to the main topic on a scale of 0.0 to 1.0.
Only respond with a number.

Main topic: {main_topic}

Segment: {segment_text[:500]}

Relevance score (0.0-1.0):"""

        request_body = {
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {
                "maxTokens": 10,
                "temperature": 0.0,
            },
        }

        response = bedrock_client.invoke_model(
            modelId="us.amazon.nova-lite-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps(request_body),
        )

        response_body = json.loads(response["body"].read())
        score_text = (
            response_body.get("output", {})
            .get("message", {})
            .get("content", [{}])[0]
            .get("text", "")
            .strip()
        )

        # Parse score
        try:
            nova_score = float(score_text)
            nova_score = max(0.0, min(1.0, nova_score))  # Clamp to 0-1
        except ValueError:
            # Fallback to embedding similarity if parsing fails
            nova_score = embedding_similarity

        # Combine embedding similarity and Nova reasoning (weighted average)
        final_score = 0.6 * embedding_similarity + 0.4 * nova_score

        return final_score

    except Exception as e:
        print(
            f"Warning: Nova reasoning failed, using embedding similarity only: {str(e)}"
        )
        return embedding_similarity


def detect_fluff_patterns(
    transcript_segments: List[Dict[str, Any]],
) -> List[FluffDetection]:
    """
    Detects fluff patterns in transcript using regex.

    Args:
        transcript_segments: List of transcript segments with text and timestamps

    Returns:
        List of detected fluff patterns

    Validates: Requirements 4.1, 4.2, 4.5, 4.6, 4.7, 4.8, 4.9
    """
    detections = []

    for segment in transcript_segments:
        text = segment.get("text", "").lower()
        start_time = segment.get("start_time", 0.0)
        end_time = segment.get("end_time", 0.0)

        # Check each pattern type
        for pattern_type, patterns in FLUFF_PATTERNS.items():
            for pattern in patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    detections.append(
                        FluffDetection(
                            pattern_type=pattern_type,
                            start_time=start_time,
                            end_time=end_time,
                            confidence=0.9,  # High confidence for regex matches
                            matched_text=match.group(0),
                        )
                    )

    return detections


def detect_silence(
    audio_path: str, threshold_seconds: float = 2.0
) -> List[Tuple[float, float]]:
    """
    Detects silence periods in audio using FFmpeg.

    Args:
        audio_path: Path to audio file
        threshold_seconds: Minimum silence duration to detect

    Returns:
        List of (start_time, end_time) tuples for silence periods

    Raises:
        NovaAnalysisError: If silence detection fails

    Validates: Requirements 4.4
    """
    try:
        # Use FFmpeg silencedetect filter
        result = subprocess.run(
            [
                "ffmpeg",
                "-i",
                audio_path,
                "-af",
                f"silencedetect=noise=-30dB:d={threshold_seconds}",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )

        # Parse silence periods from stderr
        silence_periods = []
        silence_start = None

        for line in result.stderr.split("\n"):
            if "silence_start" in line:
                match = re.search(r"silence_start:\s+([\d.]+)", line)
                if match:
                    silence_start = float(match.group(1))
            elif "silence_end" in line and silence_start is not None:
                match = re.search(r"silence_end:\s+([\d.]+)", line)
                if match:
                    silence_end = float(match.group(1))
                    silence_periods.append((silence_start, silence_end))
                    silence_start = None

        print(f"Detected {len(silence_periods)} silence periods")
        return silence_periods

    except subprocess.TimeoutExpired:
        raise NovaAnalysisError("Silence detection timeout exceeded")
    except Exception as e:
        raise NovaAnalysisError(f"Error detecting silence: {str(e)}")


def classify_segments(
    segments: List[Dict[str, Any]],
    embeddings: List[Embedding],
    relevance_scores: List[float],
    pattern_detections: List[FluffDetection],
    silence_periods: List[Tuple[float, float]],
    main_topic: str,
) -> List[SegmentClassification]:
    """
    Classifies segments as fluff or keep based on all signals.

    Args:
        segments: List of transcript segments
        embeddings: List of embeddings for each segment
        relevance_scores: Relevance scores for each segment
        pattern_detections: Detected fluff patterns
        silence_periods: Detected silence periods
        main_topic: Main topic of the video

    Returns:
        List of segment classifications

    Validates: Requirements 4.3, 4.10, 4.11
    """
    classifications = []

    for i, segment in enumerate(segments):
        start_time = segment.get("start_time", 0.0)
        end_time = segment.get("end_time", 0.0)
        segment_id = f"segment_{i}"

        relevance_score = relevance_scores[i] if i < len(relevance_scores) else 0.5

        # Check for pattern matches
        pattern_match = None
        for detection in pattern_detections:
            if detection.start_time <= start_time < detection.end_time:
                pattern_match = detection
                break

        # Check for silence overlap
        in_silence = False
        for silence_start, silence_end in silence_periods:
            if silence_start <= start_time < silence_end:
                in_silence = True
                break

        # Determine classification
        is_fluff = False
        fluff_type = None
        confidence = 0.0
        reasoning = ""

        if pattern_match:
            # Pattern detected - classify as fluff
            is_fluff = True
            fluff_type = pattern_match.pattern_type
            confidence = pattern_match.confidence
            reasoning = f"Matched {pattern_match.pattern_type} pattern: '{pattern_match.matched_text}'"

        elif in_silence:
            # Silence detected
            is_fluff = True
            fluff_type = FluffType.SILENCE.value
            confidence = 0.95
            reasoning = "Silence period detected (>2 seconds)"

        elif relevance_score < 0.4:
            # Low relevance - tangent
            is_fluff = True
            fluff_type = FluffType.TANGENT.value
            confidence = (
                1.0 - relevance_score
            )  # Lower relevance = higher confidence it's a tangent
            reasoning = f"Low relevance to main topic ({relevance_score:.2f})"

        else:
            # Keep segment
            is_fluff = False
            fluff_type = None
            confidence = relevance_score
            reasoning = f"Relevant to main topic: {main_topic}"

        classifications.append(
            SegmentClassification(
                segment_id=segment_id,
                start_time=start_time,
                end_time=end_time,
                is_fluff=is_fluff,
                fluff_type=fluff_type,
                confidence=confidence,
                relevance_score=relevance_score,
                reasoning=reasoning,
            )
        )

    return classifications


def download_from_s3(s3_path: str, local_path: str) -> None:
    """
    Downloads file from S3 to local path.

    Args:
        s3_path: S3 URI (s3://bucket/key)
        local_path: Local file path to save to

    Raises:
        NovaAnalysisError: If download fails
    """
    s3 = get_s3_client()

    try:
        # Parse S3 URI
        if not s3_path.startswith("s3://"):
            raise NovaAnalysisError(f"Invalid S3 URI: {s3_path}")

        uri_parts = s3_path[5:].split("/", 1)
        bucket = uri_parts[0]
        key = uri_parts[1]

        # Download file
        s3.download_file(bucket, key, local_path)
        print(f"Downloaded {s3_path} to {local_path}")

    except ClientError as e:
        error_msg = e.response.get("Error", {}).get("Message", str(e))
        raise NovaAnalysisError(f"Failed to download from S3: {error_msg}")
    except Exception as e:
        raise NovaAnalysisError(f"Unexpected error downloading from S3: {str(e)}")


def load_transcript(transcript_s3_path: str) -> Dict[str, Any]:
    """
    Loads transcript from S3.

    Args:
        transcript_s3_path: S3 path to transcript JSON

    Returns:
        Parsed transcript data

    Raises:
        NovaAnalysisError: If loading fails
    """
    s3 = get_s3_client()

    try:
        # Parse S3 URI
        if not transcript_s3_path.startswith("s3://"):
            raise NovaAnalysisError(f"Invalid S3 URI: {transcript_s3_path}")

        uri_parts = transcript_s3_path[5:].split("/", 1)
        bucket = uri_parts[0]
        key = uri_parts[1]

        # Download and parse transcript
        response = s3.get_object(Bucket=bucket, Key=key)
        transcript_data = json.loads(response["Body"].read().decode("utf-8"))

        return transcript_data

    except ClientError as e:
        error_msg = e.response.get("Error", {}).get("Message", str(e))
        raise NovaAnalysisError(f"Failed to load transcript: {error_msg}")
    except json.JSONDecodeError as e:
        raise NovaAnalysisError(f"Failed to parse transcript JSON: {str(e)}")
    except Exception as e:
        raise NovaAnalysisError(f"Unexpected error loading transcript: {str(e)}")


def store_analysis_to_s3(analysis: AnalysisResult, job_id: str) -> str:
    """
    Stores analysis results to S3.

    Args:
        analysis: Analysis result to store
        job_id: Job identifier

    Returns:
        S3 path to stored analysis

    Raises:
        NovaAnalysisError: If storage fails
    """
    s3 = get_s3_client()

    try:
        # Prepare analysis data
        analysis_data = {
            "main_topic": analysis.main_topic,
            "total_fluff_duration": analysis.total_fluff_duration,
            "fluff_by_type": analysis.fluff_by_type,
            "segments": [asdict(seg) for seg in analysis.segments],
        }

        # Store to S3
        key = f"{job_id}/analysis-result.json"
        s3.put_object(
            Bucket=ANALYSIS_BUCKET,
            Key=key,
            Body=json.dumps(analysis_data, indent=2),
            ContentType="application/json",
        )

        s3_path = f"s3://{ANALYSIS_BUCKET}/{key}"
        print(f"Stored analysis to: {s3_path}")

        return s3_path

    except ClientError as e:
        error_msg = e.response.get("Error", {}).get("Message", str(e))
        raise NovaAnalysisError(f"Failed to store analysis: {error_msg}")
    except Exception as e:
        raise NovaAnalysisError(f"Unexpected error storing analysis: {str(e)}")


def update_job_status(
    job_id: str,
    status: str,
    progress: int,
    current_stage: str,
    error: Optional[Dict[str, Any]] = None,
    analysis_s3_path: Optional[str] = None,
) -> None:
    """
    Updates job status in DynamoDB.

    Args:
        job_id: Job identifier
        status: Job status (queued, processing, complete, failed)
        progress: Progress percentage (0-100)
        current_stage: Current processing stage
        error: Optional error information
        analysis_s3_path: Optional S3 path to analysis results
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

    if analysis_s3_path:
        update_expr += ", analysisS3Path = :analysis"
        expr_attr_values[":analysis"] = analysis_s3_path

    table.update_item(
        Key={"PK": f"JOB#{job_id}", "SK": "METADATA"},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_attr_names,
        ExpressionAttributeValues=expr_attr_values,
    )


def analyze_video(
    video_s3_path: str, transcript_s3_path: str, job_id: str
) -> AnalysisResult:
    """
    Performs complete Nova analysis on video.

    Args:
        video_s3_path: S3 path to video file
        transcript_s3_path: S3 path to transcript JSON
        job_id: Job identifier

    Returns:
        AnalysisResult with classified segments

    Raises:
        NovaAnalysisError: If analysis fails

    Validates: Requirements 3.1, 3.2, 3.3, 3.4
    """
    bedrock = get_bedrock_runtime()

    # Create temporary directory for processing
    with tempfile.TemporaryDirectory() as temp_dir:
        # Download video
        video_path = os.path.join(temp_dir, "video.mp4")
        audio_path = os.path.join(temp_dir, "audio.wav")

        print(f"Downloading video from {video_s3_path}")
        download_from_s3(video_s3_path, video_path)

        # Download audio (should already exist from downloader Lambda)
        audio_s3_path = video_s3_path.replace("/video.mp4", "/audio.wav")
        print(f"Downloading audio from {audio_s3_path}")
        download_from_s3(audio_s3_path, audio_path)

        # Load transcript
        print(f"Loading transcript from {transcript_s3_path}")
        transcript_data = load_transcript(transcript_s3_path)
        segments = transcript_data.get("segments", [])
        full_text = transcript_data.get("full_text", "")

        if not segments:
            raise NovaAnalysisError("No segments found in transcript")

        # Extract video frames at 1 FPS
        print("Extracting video frames...")
        update_job_status(job_id, "processing", 20, "analyze")
        frame_paths = extract_video_frames(video_path, fps=1)

        # Extract main topic
        print("Extracting main topic...")
        update_job_status(job_id, "processing", 30, "analyze")
        main_topic = extract_main_topic(full_text, bedrock)
        print(f"Main topic: {main_topic}")

        # Generate embeddings for each segment
        print(f"Generating embeddings for {len(segments)} segments...")
        update_job_status(job_id, "processing", 40, "analyze")
        embeddings = []

        for i, segment in enumerate(segments):
            # Find corresponding frame (1 FPS, so frame index = floor(start_time))
            frame_idx = min(int(segment["start_time"]), len(frame_paths) - 1)
            frame_path = frame_paths[frame_idx]

            # Generate embedding
            embedding_vector = generate_multimodal_embedding(
                frame_path=frame_path,
                transcript_text=segment["text"],
                bedrock_client=bedrock,
            )

            embeddings.append(
                Embedding(
                    segment_id=f"segment_{i}",
                    embedding_vector=embedding_vector,
                    modalities=["visual", "audio", "text"],
                )
            )

            # Update progress periodically
            if i % 10 == 0:
                progress = 40 + int((i / len(segments)) * 20)
                update_job_status(job_id, "processing", progress, "analyze")

        # Generate embedding for main topic
        print("Generating main topic embedding...")
        update_job_status(job_id, "processing", 60, "analyze")
        # Use first frame as representative visual
        topic_embedding_vector = generate_multimodal_embedding(
            frame_path=frame_paths[0],
            transcript_text=main_topic,
            bedrock_client=bedrock,
        )

        # Compute relevance scores
        print("Computing relevance scores...")
        update_job_status(job_id, "processing", 70, "analyze")
        relevance_scores = []

        for i, segment in enumerate(segments):
            score = score_segment_relevance(
                segment_text=segment["text"],
                main_topic=main_topic,
                segment_embedding=embeddings[i].embedding_vector,
                topic_embedding=topic_embedding_vector,
                bedrock_client=bedrock,
            )
            relevance_scores.append(score)

        # Detect fluff patterns
        print("Detecting fluff patterns...")
        update_job_status(job_id, "processing", 80, "analyze")
        pattern_detections = detect_fluff_patterns(segments)
        print(f"Found {len(pattern_detections)} pattern matches")

        # Detect silence
        print("Detecting silence periods...")
        silence_periods = detect_silence(audio_path, threshold_seconds=2.0)
        print(f"Found {len(silence_periods)} silence periods")

        # Classify segments
        print("Classifying segments...")
        update_job_status(job_id, "processing", 90, "analyze")
        classifications = classify_segments(
            segments=segments,
            embeddings=embeddings,
            relevance_scores=relevance_scores,
            pattern_detections=pattern_detections,
            silence_periods=silence_periods,
            main_topic=main_topic,
        )

        # Calculate statistics
        total_fluff_duration = sum(
            seg.end_time - seg.start_time for seg in classifications if seg.is_fluff
        )

        fluff_by_type = {}
        for seg in classifications:
            if seg.is_fluff and seg.fluff_type:
                duration = seg.end_time - seg.start_time
                fluff_by_type[seg.fluff_type] = (
                    fluff_by_type.get(seg.fluff_type, 0.0) + duration
                )

        return AnalysisResult(
            segments=classifications,
            main_topic=main_topic,
            total_fluff_duration=total_fluff_duration,
            fluff_by_type=fluff_by_type,
        )


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for Nova video analysis.

    Args:
        event: Lambda event containing jobId, videoS3Path, transcriptS3Path
        context: Lambda context

    Returns:
        Response with analysis result or error
    """
    try:
        # Extract parameters
        job_id = event.get("jobId")
        video_s3_path = event.get("videoS3Path")
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

        if not transcript_s3_path:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing transcriptS3Path parameter"}),
            }

        print(f"Processing Nova analysis for job {job_id}")
        print(f"Video S3 path: {video_s3_path}")
        print(f"Transcript S3 path: {transcript_s3_path}")

        # Update status to processing
        update_job_status(job_id, "processing", 10, "analyze")

        # Analyze video
        analysis = analyze_video(video_s3_path, transcript_s3_path, job_id)

        # Store analysis results
        update_job_status(job_id, "processing", 95, "analyze")
        analysis_s3_path = store_analysis_to_s3(analysis, job_id)

        # Update job with result
        update_job_status(
            job_id,
            "processing",
            100,
            "analyze",
            analysis_s3_path=analysis_s3_path,
        )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "jobId": job_id,
                    "status": "complete",
                    "result": {
                        "analysisS3Path": analysis_s3_path,
                        "mainTopic": analysis.main_topic,
                        "totalFluffDuration": analysis.total_fluff_duration,
                        "fluffByType": analysis.fluff_by_type,
                        "segmentCount": len(analysis.segments),
                        "fluffSegmentCount": sum(
                            1 for s in analysis.segments if s.is_fluff
                        ),
                    },
                }
            ),
        }

    except NovaAnalysisError as e:
        error_info = {
            "stage": "analyze",
            "message": str(e),
            "timestamp": int(time.time() * 1000),
        }
        if job_id:
            update_job_status(job_id, "failed", 0, "analyze", error=error_info)

        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "error": "Nova analysis failed",
                    "details": str(e),
                    "suggestedActions": [
                        "Verify video and transcript files are accessible in S3",
                        "Check Bedrock service availability",
                        "Retry the request",
                        "Contact support if the issue persists",
                    ],
                }
            ),
        }

    except Exception as e:
        error_info = {
            "stage": "analyze",
            "message": f"Unexpected error: {str(e)}",
            "timestamp": int(time.time() * 1000),
        }
        if job_id:
            update_job_status(job_id, "failed", 0, "analyze", error=error_info)

        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error", "details": str(e)}),
        }
