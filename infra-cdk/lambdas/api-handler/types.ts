/**
 * Type definitions for YouTube Video Editor API Handler
 * 
 * Defines interfaces for job management, pipeline stages, and API responses.
 */

/**
 * Pipeline stages in the video processing workflow.
 * Stages execute sequentially: download → transcribe → analyze → edit → finalize
 */
export enum PipelineStage {
  DOWNLOAD = 'download',
  TRANSCRIBE = 'transcribe',
  ANALYZE = 'analyze',
  EDIT = 'edit',
  FINALIZE = 'finalize'
}

/**
 * Job status values representing the current state of a video processing job.
 */
export enum JobStatus {
  QUEUED = 'queued',
  PROCESSING = 'processing',
  COMPLETE = 'complete',
  FAILED = 'failed'
}

/**
 * Video metadata extracted from YouTube.
 */
export interface VideoMetadata {
  title: string;
  duration: number;
  thumbnail: string;
  resolution: string;
  format: string;
}

/**
 * Error information captured when a job fails.
 */
export interface ErrorInfo {
  stage: string;
  message: string;
  timestamp: number;
}

/**
 * DynamoDB job record structure.
 * Stores job state, progress, and results.
 */
export interface JobRecord {
  PK: string;                    // Partition key: "JOB#{jobId}"
  SK: string;                    // Sort key: "METADATA"
  jobId: string;                 // Unique job identifier (UUID)
  youtubeUrl: string;            // YouTube video URL to process
  status: JobStatus;             // Current job status
  progress: number;              // Progress percentage (0-100)
  currentStage: string;          // Current pipeline stage
  createdAt: number;             // Creation timestamp (milliseconds)
  updatedAt: number;             // Last update timestamp (milliseconds)
  ttl: number;                   // Time-to-live for automatic cleanup (24 hours)
  executionArn?: string;         // Step Functions execution ARN
  videoMetadata?: VideoMetadata; // Video metadata (populated after download)
  transcriptS3Path?: string;     // S3 path to transcript (populated after transcription)
  analysisS3Path?: string;       // S3 path to analysis results (populated after analysis)
  editedVideoS3Path?: string;    // S3 path to edited video (populated after editing)
  error?: ErrorInfo;             // Error information (populated on failure)
}

/**
 * Input payload for Step Functions state machine execution.
 */
export interface StepFunctionsInput {
  jobId: string;
  youtubeUrl: string;
}

/**
 * API request body for POST /jobs endpoint.
 */
export interface CreateJobRequest {
  youtubeUrl: string;
}

/**
 * API response for POST /jobs endpoint.
 */
export interface CreateJobResponse {
  jobId: string;
  status: JobStatus;
}

/**
 * API response for GET /jobs/{jobId} endpoint.
 */
export interface GetJobStatusResponse {
  jobId: string;
  status: JobStatus;
  progress: number;
  currentStage: string;
  estimatedTimeRemaining?: number;
}

/**
 * Segment information for removed or kept video segments.
 */
export interface SegmentInfo {
  startTime: number;
  endTime: number;
  type: string;
  confidence?: number;
  transcript?: string;
}

/**
 * Fluff report showing what content was removed and why.
 */
export interface FluffReport {
  removedSegments: SegmentInfo[];
  totalTimeSaved: number;
  retentionPercentage: number;
}

/**
 * Chapter marker for video navigation.
 */
export interface Chapter {
  timestamp: number;
  title: string;
}

/**
 * API response for GET /jobs/{jobId}/result endpoint.
 */
export interface GetJobResultResponse {
  jobId: string;
  originalVideo: {
    url: string;
    metadata: VideoMetadata;
  };
  editedVideo: {
    url: string;
    downloadUrl: string;
    streamingUrl: string;
  };
  segments: SegmentInfo[];
  fluffReport: FluffReport;
  chapters: Chapter[];
}

/**
 * Standard error response format for API endpoints.
 */
export interface ErrorResponse {
  error: {
    code: string;
    message: string;
    details?: Record<string, any>;
    suggestedActions?: string[];
    timestamp: number;
  };
}

/**
 * Lambda handler event for API Gateway proxy integration.
 */
export interface APIGatewayProxyEvent {
  httpMethod: string;
  path: string;
  pathParameters: Record<string, string> | null;
  body: string | null;
  headers: Record<string, string>;
  requestContext: {
    requestId: string;
    [key: string]: any;
  };
}

/**
 * Lambda handler response for API Gateway proxy integration.
 */
export interface APIGatewayProxyResult {
  statusCode: number;
  headers?: Record<string, string>;
  body: string;
}
