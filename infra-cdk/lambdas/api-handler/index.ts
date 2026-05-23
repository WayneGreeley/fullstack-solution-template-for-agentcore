/**
 * API Handler Lambda Function
 * 
 * Handles API Gateway requests for the YouTube Video Editor.
 * Manages job lifecycle: creation, status queries, and result retrieval.
 * Integrates with Step Functions for pipeline orchestration.
 */

import { SFNClient, StartExecutionCommand, DescribeExecutionCommand } from '@aws-sdk/client-sfn';
import {
  APIGatewayProxyEvent,
  APIGatewayProxyResult,
  CreateJobRequest,
  CreateJobResponse,
  GetJobStatusResponse,
  GetJobResultResponse,
  ErrorResponse,
  JobStatus,
  StepFunctionsInput,
} from './types';
import { createJob, getJobStatus, updateJobStatus } from './job-manager';

// Environment variables
const STATE_MACHINE_ARN = process.env.STATE_MACHINE_ARN;
const CLOUDFRONT_URL = process.env.CLOUDFRONT_URL;

// Validate required environment variables
if (!STATE_MACHINE_ARN) {
  throw new Error('STATE_MACHINE_ARN environment variable is required');
}

if (!CLOUDFRONT_URL) {
  throw new Error('CLOUDFRONT_URL environment variable is required');
}

// Initialize Step Functions client
const sfnClient = new SFNClient({});

/**
 * CORS headers for API responses.
 */
const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
  'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
  'Content-Type': 'application/json',
};

/**
 * Creates a standardized API Gateway response.
 * 
 * @param statusCode - HTTP status code
 * @param body - Response body object
 * @returns API Gateway proxy result
 */
function createResponse(statusCode: number, body: any): APIGatewayProxyResult {
  return {
    statusCode,
    headers: CORS_HEADERS,
    body: JSON.stringify(body),
  };
}

/**
 * Creates a standardized error response.
 * 
 * @param statusCode - HTTP status code
 * @param code - Error code
 * @param message - Error message
 * @param details - Optional error details
 * @param suggestedActions - Optional suggested actions for the user
 * @returns API Gateway proxy result with error
 */
function createErrorResponse(
  statusCode: number,
  code: string,
  message: string,
  details?: any,
  suggestedActions?: string[]
): APIGatewayProxyResult {
  const errorResponse: ErrorResponse = {
    error: {
      code,
      message,
      details,
      suggestedActions,
      timestamp: Date.now(),
    },
  };

  return createResponse(statusCode, errorResponse);
}

/**
 * Validates YouTube URL format.
 * 
 * @param url - URL to validate
 * @returns True if valid YouTube URL
 */
function isValidYouTubeUrl(url: string): boolean {
  if (!url) {
    return false;
  }

  try {
    const parsed = new URL(url);
    const validDomains = ['youtube.com', 'www.youtube.com', 'youtu.be', 'm.youtube.com'];
    
    if (!validDomains.includes(parsed.hostname)) {
      return false;
    }

    // Check for video ID
    if (parsed.hostname === 'youtu.be') {
      // Short URL format: https://youtu.be/VIDEO_ID
      const videoId = parsed.pathname.slice(1);
      return videoId.length === 11;
    } else {
      // Standard URL format: https://www.youtube.com/watch?v=VIDEO_ID
      const videoId = parsed.searchParams.get('v');
      return videoId !== null && videoId.length === 11;
    }
  } catch {
    return false;
  }
}

/**
 * Handles POST /jobs - Creates a new video processing job.
 * 
 * @param event - API Gateway proxy event
 * @returns API Gateway proxy result with job ID
 */
async function handleCreateJob(event: APIGatewayProxyEvent): Promise<APIGatewayProxyResult> {
  try {
    // Parse request body
    if (!event.body) {
      return createErrorResponse(
        400,
        'MISSING_BODY',
        'Request body is required',
        undefined,
        ['Provide a JSON body with youtubeUrl field']
      );
    }

    let requestBody: CreateJobRequest;
    try {
      requestBody = JSON.parse(event.body);
    } catch {
      return createErrorResponse(
        400,
        'INVALID_JSON',
        'Request body must be valid JSON',
        undefined,
        ['Check JSON syntax and try again']
      );
    }

    // Validate YouTube URL
    const { youtubeUrl } = requestBody;
    if (!youtubeUrl) {
      return createErrorResponse(
        400,
        'MISSING_URL',
        'youtubeUrl field is required',
        undefined,
        ['Provide a valid YouTube URL in the request body']
      );
    }

    if (!isValidYouTubeUrl(youtubeUrl)) {
      return createErrorResponse(
        400,
        'INVALID_URL',
        'Invalid YouTube URL format',
        { providedUrl: youtubeUrl },
        [
          'Ensure the URL is from youtube.com or youtu.be',
          'Verify the URL contains a valid video ID',
        ]
      );
    }

    // Create job in DynamoDB
    const jobId = await createJob(youtubeUrl);

    // Start Step Functions execution
    const input: StepFunctionsInput = {
      jobId,
      youtubeUrl,
    };

    const startExecutionCommand = new StartExecutionCommand({
      stateMachineArn: STATE_MACHINE_ARN,
      name: `job-${jobId}`,
      input: JSON.stringify(input),
    });

    const executionResult = await sfnClient.send(startExecutionCommand);
    const executionArn = executionResult.executionArn;

    if (!executionArn) {
      throw new Error('Failed to start Step Functions execution: no execution ARN returned');
    }

    // Update job with execution ARN and set status to processing
    await updateJobStatus(
      jobId,
      JobStatus.PROCESSING,
      0,
      'download',
      undefined,
      executionArn
    );

    console.log(`Started Step Functions execution for job ${jobId}: ${executionArn}`);

    // Return response
    const response: CreateJobResponse = {
      jobId,
      status: JobStatus.PROCESSING,
    };

    return createResponse(200, response);
  } catch (error) {
    console.error('Error creating job:', error);
    return createErrorResponse(
      500,
      'INTERNAL_ERROR',
      'Failed to create job',
      { error: error instanceof Error ? error.message : 'Unknown error' },
      ['Retry the request', 'Contact support if the issue persists']
    );
  }
}

/**
 * Handles GET /jobs/{jobId} - Retrieves job status.
 * 
 * @param event - API Gateway proxy event
 * @returns API Gateway proxy result with job status
 */
async function handleGetJobStatus(event: APIGatewayProxyEvent): Promise<APIGatewayProxyResult> {
  try {
    // Extract job ID from path parameters
    const jobId = event.pathParameters?.jobId;
    if (!jobId) {
      return createErrorResponse(
        400,
        'MISSING_JOB_ID',
        'Job ID is required in the path',
        undefined,
        ['Provide a valid job ID in the URL path']
      );
    }

    // Get job from DynamoDB
    const job = await getJobStatus(jobId);
    if (!job) {
      return createErrorResponse(
        404,
        'JOB_NOT_FOUND',
        `Job ${jobId} not found`,
        { jobId },
        ['Verify the job ID is correct', 'Check if the job has expired (24-hour TTL)']
      );
    }

    // If job has execution ARN, get execution status from Step Functions
    let estimatedTimeRemaining: number | undefined;
    if (job.executionArn && job.status === JobStatus.PROCESSING) {
      try {
        const describeCommand = new DescribeExecutionCommand({
          executionArn: job.executionArn,
        });
        const execution = await sfnClient.send(describeCommand);

        // Update job status based on execution status
        if (execution.status === 'SUCCEEDED') {
          await updateJobStatus(jobId, JobStatus.COMPLETE, 100, 'complete');
          job.status = JobStatus.COMPLETE;
          job.progress = 100;
          job.currentStage = 'complete';
        } else if (execution.status === 'FAILED' || execution.status === 'TIMED_OUT' || execution.status === 'ABORTED') {
          await updateJobStatus(
            jobId,
            JobStatus.FAILED,
            job.progress,
            job.currentStage,
            {
              stage: job.currentStage,
              message: `Step Functions execution ${execution.status.toLowerCase()}`,
              timestamp: Date.now(),
            }
          );
          job.status = JobStatus.FAILED;
        }

        // Estimate time remaining based on progress (rough estimate)
        if (job.status === JobStatus.PROCESSING && job.progress > 0) {
          const elapsed = Date.now() - job.createdAt;
          const estimatedTotal = (elapsed / job.progress) * 100;
          estimatedTimeRemaining = Math.max(0, Math.floor((estimatedTotal - elapsed) / 1000));
        }
      } catch (error) {
        console.error(`Failed to describe Step Functions execution for job ${jobId}:`, error);
        // Continue with DynamoDB data if Step Functions query fails
      }
    }

    // Return response
    const response: GetJobStatusResponse = {
      jobId: job.jobId,
      status: job.status,
      progress: job.progress,
      currentStage: job.currentStage,
      estimatedTimeRemaining,
    };

    return createResponse(200, response);
  } catch (error) {
    console.error('Error getting job status:', error);
    return createErrorResponse(
      500,
      'INTERNAL_ERROR',
      'Failed to get job status',
      { error: error instanceof Error ? error.message : 'Unknown error' },
      ['Retry the request', 'Contact support if the issue persists']
    );
  }
}

/**
 * Handles GET /jobs/{jobId}/result - Retrieves completed job results.
 * 
 * @param event - API Gateway proxy event
 * @returns API Gateway proxy result with job results
 */
async function handleGetJobResult(event: APIGatewayProxyEvent): Promise<APIGatewayProxyResult> {
  try {
    // Extract job ID from path parameters
    const jobId = event.pathParameters?.jobId;
    if (!jobId) {
      return createErrorResponse(
        400,
        'MISSING_JOB_ID',
        'Job ID is required in the path',
        undefined,
        ['Provide a valid job ID in the URL path']
      );
    }

    // Get job from DynamoDB
    const job = await getJobStatus(jobId);
    if (!job) {
      return createErrorResponse(
        404,
        'JOB_NOT_FOUND',
        `Job ${jobId} not found`,
        { jobId },
        ['Verify the job ID is correct', 'Check if the job has expired (24-hour TTL)']
      );
    }

    // Check if job is complete
    if (job.status !== JobStatus.COMPLETE) {
      return createErrorResponse(
        400,
        'JOB_NOT_COMPLETE',
        `Job is not complete yet (status: ${job.status})`,
        { jobId, status: job.status, progress: job.progress },
        ['Wait for the job to complete', 'Poll GET /jobs/{jobId} for status updates']
      );
    }

    // Verify required result data is present
    if (!job.editedVideoS3Path || !job.videoMetadata) {
      return createErrorResponse(
        500,
        'INCOMPLETE_RESULTS',
        'Job completed but results are incomplete',
        { jobId },
        ['Retry the job', 'Contact support if the issue persists']
      );
    }

    // Build CloudFront URLs for video access
    const editedVideoKey = job.editedVideoS3Path.split('/').slice(3).join('/');
    const streamingUrl = `${CLOUDFRONT_URL}/${editedVideoKey}`;
    const downloadUrl = `${CLOUDFRONT_URL}/${editedVideoKey}`;

    // TODO: Load segments, fluff report, and chapters from S3
    // For now, return placeholder data
    const response: GetJobResultResponse = {
      jobId: job.jobId,
      originalVideo: {
        url: job.youtubeUrl,
        metadata: job.videoMetadata,
      },
      editedVideo: {
        url: streamingUrl,
        downloadUrl,
        streamingUrl,
      },
      segments: [], // TODO: Load from S3
      fluffReport: {
        removedSegments: [],
        totalTimeSaved: 0,
        retentionPercentage: 100,
      },
      chapters: [], // TODO: Load from S3
    };

    return createResponse(200, response);
  } catch (error) {
    console.error('Error getting job result:', error);
    return createErrorResponse(
      500,
      'INTERNAL_ERROR',
      'Failed to get job result',
      { error: error instanceof Error ? error.message : 'Unknown error' },
      ['Retry the request', 'Contact support if the issue persists']
    );
  }
}

/**
 * Main Lambda handler for API Gateway requests.
 * Routes requests to appropriate handler based on HTTP method and path.
 * 
 * @param event - API Gateway proxy event
 * @returns API Gateway proxy result
 */
export async function handler(event: APIGatewayProxyEvent): Promise<APIGatewayProxyResult> {
  console.log('Received request:', JSON.stringify(event, null, 2));

  // Handle CORS preflight requests
  if (event.httpMethod === 'OPTIONS') {
    return createResponse(200, {});
  }

  try {
    // Route based on HTTP method and path
    const method = event.httpMethod;
    const path = event.path;

    if (method === 'POST' && path === '/jobs') {
      return await handleCreateJob(event);
    } else if (method === 'GET' && path.match(/^\/jobs\/[^/]+$/)) {
      return await handleGetJobStatus(event);
    } else if (method === 'GET' && path.match(/^\/jobs\/[^/]+\/result$/)) {
      return await handleGetJobResult(event);
    } else {
      return createErrorResponse(
        404,
        'NOT_FOUND',
        `Route not found: ${method} ${path}`,
        undefined,
        ['Check the API documentation for valid endpoints']
      );
    }
  } catch (error) {
    console.error('Unhandled error in Lambda handler:', error);
    return createErrorResponse(
      500,
      'INTERNAL_ERROR',
      'An unexpected error occurred',
      { error: error instanceof Error ? error.message : 'Unknown error' },
      ['Retry the request', 'Contact support if the issue persists']
    );
  }
}
