"""
Fluff Detection Module

Detects and classifies fluff content in video transcripts and audio.
Implements pattern matching, silence detection, and tangent detection.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11
"""

import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


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


# Fluff detection patterns
# Requirements: 4.1, 4.2, 4.5, 4.6, 4.7, 4.8, 4.9
FLUFF_PATTERNS = {
    "CTA": [
        r"like\s+and\s+subscribe",
        r"hit\s+the\s+bell",
        r"smash\s+that\s+like",
        r"comment\s+below",
        r"leave\s+a\s+comment",
        r"don't\s+forget\s+to\s+subscribe",
        r"subscribe\s+to\s+(?:my|the)\s+channel",
        r"turn\s+on\s+notifications",
    ],
    "AD": [
        r"sponsor(?:ed|ship)?",
        r"promo\s+code",
        r"affiliate\s+link",
        r"discount\s+code",
        r"use\s+code",
        r"check\s+out\s+the\s+link",
        r"link\s+in\s+(?:the\s+)?description",
        r"this\s+video\s+is\s+sponsored",
    ],
    "INTRO": [
        r"hey\s+guys",
        r"what's\s+up\s+(?:guys|everyone)",
        r"welcome\s+back",
        r"hello\s+(?:everyone|guys)",
        r"good\s+(?:morning|afternoon|evening)",
        r"hi\s+(?:everyone|guys|there)",
        r"yo\s+what's\s+up",
    ],
    "OUTRO": [
        r"see\s+you\s+(?:next|in\s+the\s+next)",
        r"that's\s+all\s+for\s+(?:today|now)",
        r"thanks\s+for\s+watching",
        r"catch\s+you\s+(?:later|next\s+time)",
        r"until\s+next\s+time",
        r"peace\s+out",
        r"take\s+care",
    ],
    "FILLER": [
        r"(?:um|uh|er|ah){2,}",
        r"you\s+know\s+what\s+I\s+mean",
        r"like\s+I\s+said",
        r"as\s+I\s+mentioned",
        r"long\s+story\s+short",
        r"to\s+be\s+honest",
        r"at\s+the\s+end\s+of\s+the\s+day",
    ],
}


class FluffDetectionError(Exception):
    """Base exception for fluff detection errors."""

    pass


def detect_cta_patterns(text: str) -> List[Tuple[str, float]]:
    """
    Detects call-to-action patterns in text.

    Args:
        text: Text to analyze (should be lowercase)

    Returns:
        List of (matched_text, confidence) tuples

    Validates: Requirements 4.1
    """
    matches = []
    for pattern in FLUFF_PATTERNS["CTA"]:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matches.append((match.group(0), 0.9))
    return matches


def detect_ad_patterns(text: str) -> List[Tuple[str, float]]:
    """
    Detects advertisement and sponsorship patterns in text.

    Args:
        text: Text to analyze (should be lowercase)

    Returns:
        List of (matched_text, confidence) tuples

    Validates: Requirements 4.2
    """
    matches = []
    for pattern in FLUFF_PATTERNS["AD"]:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matches.append((match.group(0), 0.9))
    return matches


def detect_intro_patterns(text: str) -> List[Tuple[str, float]]:
    """
    Detects intro greeting patterns in text.

    Args:
        text: Text to analyze (should be lowercase)

    Returns:
        List of (matched_text, confidence) tuples

    Validates: Requirements 4.6
    """
    matches = []
    for pattern in FLUFF_PATTERNS["INTRO"]:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matches.append((match.group(0), 0.85))
    return matches


def detect_outro_patterns(text: str) -> List[Tuple[str, float]]:
    """
    Detects outro closing patterns in text.

    Args:
        text: Text to analyze (should be lowercase)

    Returns:
        List of (matched_text, confidence) tuples

    Validates: Requirements 4.7
    """
    matches = []
    for pattern in FLUFF_PATTERNS["OUTRO"]:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matches.append((match.group(0), 0.85))
    return matches


def detect_filler_patterns(text: str) -> List[Tuple[str, float]]:
    """
    Detects filler phrase patterns in text.

    Args:
        text: Text to analyze (should be lowercase)

    Returns:
        List of (matched_text, confidence) tuples

    Validates: Requirements 4.5, 4.8, 4.9
    """
    matches = []
    for pattern in FLUFF_PATTERNS["FILLER"]:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matches.append((match.group(0), 0.8))
    return matches


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
                    # Determine confidence based on pattern type
                    confidence = 0.9 if pattern_type in ["CTA", "AD"] else 0.85

                    detections.append(
                        FluffDetection(
                            pattern_type=pattern_type,
                            start_time=start_time,
                            end_time=end_time,
                            confidence=confidence,
                            matched_text=match.group(0),
                        )
                    )

    return detections


def detect_silence(
    audio_path: str, threshold_seconds: float = 2.0
) -> List[Tuple[float, float]]:
    """
    Detects silence periods in audio using FFmpeg silencedetect filter.

    Args:
        audio_path: Path to audio file
        threshold_seconds: Minimum silence duration to detect (default: 2.0)

    Returns:
        List of (start_time, end_time) tuples for silence periods

    Raises:
        FluffDetectionError: If silence detection fails

    Validates: Requirements 4.4
    """
    try:
        # Use FFmpeg silencedetect filter
        # -30dB is a reasonable threshold for detecting silence
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

        # Parse silence periods from stderr (FFmpeg outputs to stderr)
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
        raise FluffDetectionError("Silence detection timeout exceeded (300s)")
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        raise FluffDetectionError(f"FFmpeg silence detection failed: {error_msg}")
    except Exception as e:
        raise FluffDetectionError(f"Error detecting silence: {str(e)}")


def detect_tangents(relevance_scores: List[float], threshold: float = 0.4) -> List[int]:
    """
    Detects tangent segments based on relevance scores.

    Args:
        relevance_scores: List of relevance scores (0-1) for each segment
        threshold: Relevance threshold below which segments are tangents (default: 0.4)

    Returns:
        List of segment indices that are tangents

    Validates: Requirements 4.3
    """
    tangent_indices = []

    for i, score in enumerate(relevance_scores):
        if score < threshold:
            tangent_indices.append(i)

    return tangent_indices


def classify_segments(
    segments: List[Dict[str, Any]],
    relevance_scores: List[float],
    pattern_detections: List[FluffDetection],
    silence_periods: List[Tuple[float, float]],
    main_topic: str,
    tangent_threshold: float = 0.4,
) -> List[SegmentClassification]:
    """
    Classifies segments as fluff or keep based on all detection signals.

    Combines pattern matching, silence detection, and relevance scoring
    to produce final classifications with confidence scores.

    Args:
        segments: List of transcript segments with text and timestamps
        relevance_scores: Relevance scores for each segment (0-1)
        pattern_detections: Detected fluff patterns from regex
        silence_periods: Detected silence periods from audio analysis
        main_topic: Main topic of the video
        tangent_threshold: Relevance threshold for tangent detection (default: 0.4)

    Returns:
        List of segment classifications with fluff type and confidence

    Validates: Requirements 4.3, 4.10, 4.11
    """
    classifications = []

    for i, segment in enumerate(segments):
        start_time = segment.get("start_time", 0.0)
        end_time = segment.get("end_time", 0.0)
        segment_id = f"segment_{i}"

        relevance_score = relevance_scores[i] if i < len(relevance_scores) else 0.5

        # Check for pattern matches in this segment
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

        elif relevance_score < tangent_threshold:
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


def calculate_fluff_statistics(
    classifications: List[SegmentClassification],
) -> Tuple[float, Dict[str, float]]:
    """
    Calculates fluff duration statistics from classifications.

    Args:
        classifications: List of segment classifications

    Returns:
        Tuple of (total_fluff_duration, fluff_by_type)
        - total_fluff_duration: Total duration of all fluff in seconds
        - fluff_by_type: Dictionary mapping fluff type to duration in seconds

    Validates: Requirements 4.10, 4.11
    """
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

    return total_fluff_duration, fluff_by_type
