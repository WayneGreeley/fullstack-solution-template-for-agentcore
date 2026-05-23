/**
 * Job Manager Module
 * 
 * Handles all DynamoDB operations for job lifecycle management.
 * Provides functions to create, read, and update job records.
 */

import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import { DynamoDBDocumentClient, PutCommand, GetCommand, UpdateCommand } from '@aws-sdk/lib-dynamodb';
import { v4 as uuidv4 } from 'uuid';
import { JobRecord, JobStatus, ErrorInfo, VideoMetadata } from './types';

// Environment variables
const JOBS_TABLE = process.env.JOBS_TABLE;

// Validate required environment variables
if (!JOBS_TABLE) {
  throw new Error('JOBS_TABLE environment variable is required');
}

// Initialize DynamoDB client
const dynamoClient = new DynamoDBClient({});
const docClient = DynamoDBDocumentClient.from(dynamoClient);

/**
 * Creates a new job record in DynamoDB.
 * 
 * Initializes a job with queued status and generates a unique job ID.
 * Sets TTL to 24 hours from creation for automatic cleanup.
 * 
 * @param youtubeUrl - YouTube video URL to process
 * @returns Promise resolving to the created job ID
 * @throws Error if DynamoDB operation fails
 */
export async function createJob(youtubeUrl: string): Promise<string> {
  const jobId = uuidv4();
  const now = Date.now();
  const ttl = Math.floor(now / 1000) + (24 * 60 * 60); // 24 hours from now

  const jobRecord: JobRecord = {
    PK: `JOB#${jobId}`,
    SK: 'METADATA',
    jobId,
    youtubeUrl,
    status: JobStatus.QUEUED,
    progress: 0,
    currentStage: 'queued',
    createdAt: now,
    updatedAt: now,
    ttl,
  };

  try {
    await docClient.send(new PutCommand({
      TableName: JOBS_TABLE,
      Item: jobRecord,
    }));

    console.log(`Created job ${jobId} for URL: ${youtubeUrl}`);
    return jobId;
  } catch (error) {
    console.error('Failed to create job:', error);
    throw new Error(`Failed to create job: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

/**
 * Retrieves a job record from DynamoDB.
 * 
 * @param jobId - Unique job identifier
 * @returns Promise resolving to the job record, or null if not found
 * @throws Error if DynamoDB operation fails
 */
export async function getJobStatus(jobId: string): Promise<JobRecord | null> {
  try {
    const response = await docClient.send(new GetCommand({
      TableName: JOBS_TABLE,
      Key: {
        PK: `JOB#${jobId}`,
        SK: 'METADATA',
      },
    }));

    if (!response.Item) {
      console.log(`Job ${jobId} not found`);
      return null;
    }

    return response.Item as JobRecord;
  } catch (error) {
    console.error(`Failed to get job status for ${jobId}:`, error);
    throw new Error(`Failed to get job status: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

/**
 * Updates job status and progress in DynamoDB.
 * 
 * @param jobId - Unique job identifier
 * @param status - New job status
 * @param progress - Progress percentage (0-100)
 * @param currentStage - Current pipeline stage
 * @param error - Optional error information (for failed jobs)
 * @param executionArn - Optional Step Functions execution ARN
 * @returns Promise that resolves when update is complete
 * @throws Error if DynamoDB operation fails
 */
export async function updateJobStatus(
  jobId: string,
  status: JobStatus,
  progress: number,
  currentStage: string,
  error?: ErrorInfo,
  executionArn?: string
): Promise<void> {
  const now = Date.now();

  // Build update expression dynamically based on provided parameters
  let updateExpression = 'SET #status = :status, progress = :progress, currentStage = :stage, updatedAt = :updated';
  const expressionAttributeNames: Record<string, string> = {
    '#status': 'status',
  };
  const expressionAttributeValues: Record<string, any> = {
    ':status': status,
    ':progress': progress,
    ':stage': currentStage,
    ':updated': now,
  };

  // Add execution ARN if provided
  if (executionArn) {
    updateExpression += ', executionArn = :executionArn';
    expressionAttributeValues[':executionArn'] = executionArn;
  }

  // Add error information if provided
  if (error) {
    updateExpression += ', #error = :error';
    expressionAttributeNames['#error'] = 'error';
    expressionAttributeValues[':error'] = error;
  }

  try {
    await docClient.send(new UpdateCommand({
      TableName: JOBS_TABLE,
      Key: {
        PK: `JOB#${jobId}`,
        SK: 'METADATA',
      },
      UpdateExpression: updateExpression,
      ExpressionAttributeNames: expressionAttributeNames,
      ExpressionAttributeValues: expressionAttributeValues,
    }));

    console.log(`Updated job ${jobId}: status=${status}, progress=${progress}, stage=${currentStage}`);
  } catch (error) {
    console.error(`Failed to update job status for ${jobId}:`, error);
    throw new Error(`Failed to update job status: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

/**
 * Updates job with result data from completed pipeline stages.
 * 
 * @param jobId - Unique job identifier
 * @param resultData - Result data to store (videoMetadata, transcriptS3Path, etc.)
 * @returns Promise that resolves when update is complete
 * @throws Error if DynamoDB operation fails
 */
export async function updateJobResult(
  jobId: string,
  resultData: {
    videoMetadata?: VideoMetadata;
    transcriptS3Path?: string;
    analysisS3Path?: string;
    editedVideoS3Path?: string;
  }
): Promise<void> {
  const now = Date.now();

  // Build update expression dynamically based on provided result data
  const updateParts: string[] = ['updatedAt = :updated'];
  const expressionAttributeValues: Record<string, any> = {
    ':updated': now,
  };

  if (resultData.videoMetadata) {
    updateParts.push('videoMetadata = :metadata');
    expressionAttributeValues[':metadata'] = resultData.videoMetadata;
  }

  if (resultData.transcriptS3Path) {
    updateParts.push('transcriptS3Path = :transcript');
    expressionAttributeValues[':transcript'] = resultData.transcriptS3Path;
  }

  if (resultData.analysisS3Path) {
    updateParts.push('analysisS3Path = :analysis');
    expressionAttributeValues[':analysis'] = resultData.analysisS3Path;
  }

  if (resultData.editedVideoS3Path) {
    updateParts.push('editedVideoS3Path = :edited');
    expressionAttributeValues[':edited'] = resultData.editedVideoS3Path;
  }

  const updateExpression = 'SET ' + updateParts.join(', ');

  try {
    await docClient.send(new UpdateCommand({
      TableName: JOBS_TABLE,
      Key: {
        PK: `JOB#${jobId}`,
        SK: 'METADATA',
      },
      UpdateExpression: updateExpression,
      ExpressionAttributeValues: expressionAttributeValues,
    }));

    console.log(`Updated job ${jobId} with result data`);
  } catch (error) {
    console.error(`Failed to update job result for ${jobId}:`, error);
    throw new Error(`Failed to update job result: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}
