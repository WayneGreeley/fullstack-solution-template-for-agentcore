/**
 * Unit tests for Job Manager
 * 
 * Tests DynamoDB operations for job lifecycle management.
 */

// Set environment variables BEFORE importing modules
process.env.JOBS_TABLE = 'test-jobs-table';

import { mockClient } from 'aws-sdk-client-mock';
import { DynamoDBDocumentClient, PutCommand, GetCommand, UpdateCommand } from '@aws-sdk/lib-dynamodb';
import { createJob, getJobStatus, updateJobStatus, updateJobResult } from './job-manager';
import { JobStatus } from './types';

// Mock DynamoDB Document Client
const ddbMock = mockClient(DynamoDBDocumentClient);

describe('Job Manager', () => {
  beforeEach(() => {
    // Reset mock before each test
    ddbMock.reset();
  });

  describe('createJob', () => {
    it('should create a new job with queued status', async () => {
      // Given: DynamoDB put command will succeed
      ddbMock.on(PutCommand).resolves({});

      // When: Creating a new job
      const youtubeUrl = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';
      const jobId = await createJob(youtubeUrl);

      // Then: Job ID should be returned
      expect(jobId).toBeDefined();
      expect(typeof jobId).toBe('string');
      expect(jobId.length).toBeGreaterThan(0);

      // Then: DynamoDB put should be called with correct parameters
      const putCalls = ddbMock.commandCalls(PutCommand);
      expect(putCalls.length).toBe(1);

      const putItem = putCalls[0].args[0].input.Item;
      expect(putItem).toBeDefined();
      expect(putItem).toMatchObject({
        PK: `JOB#${jobId}`,
        SK: 'METADATA',
        jobId,
        youtubeUrl,
        status: JobStatus.QUEUED,
        progress: 0,
        currentStage: 'queued',
      });
      expect(putItem?.createdAt).toBeDefined();
      expect(putItem?.updatedAt).toBeDefined();
      expect(putItem?.ttl).toBeDefined();
    });

    it('should throw error when DynamoDB put fails', async () => {
      // Given: DynamoDB put command will fail
      ddbMock.on(PutCommand).rejects(new Error('DynamoDB error'));

      // When/Then: Creating a job should throw error
      await expect(createJob('https://www.youtube.com/watch?v=test')).rejects.toThrow('Failed to create job');
    });
  });

  describe('getJobStatus', () => {
    it('should retrieve existing job', async () => {
      // Given: DynamoDB get command will return a job
      const mockJob = {
        PK: 'JOB#test-job-id',
        SK: 'METADATA',
        jobId: 'test-job-id',
        youtubeUrl: 'https://www.youtube.com/watch?v=test',
        status: JobStatus.PROCESSING,
        progress: 50,
        currentStage: 'transcribe',
        createdAt: Date.now(),
        updatedAt: Date.now(),
        ttl: Math.floor(Date.now() / 1000) + 86400,
      };
      ddbMock.on(GetCommand).resolves({ Item: mockJob });

      // When: Getting job status
      const job = await getJobStatus('test-job-id');

      // Then: Job should be returned
      expect(job).toEqual(mockJob);

      // Then: DynamoDB get should be called with correct key
      const getCalls = ddbMock.commandCalls(GetCommand);
      expect(getCalls.length).toBe(1);
      expect(getCalls[0].args[0].input.Key).toEqual({
        PK: 'JOB#test-job-id',
        SK: 'METADATA',
      });
    });

    it('should return null when job not found', async () => {
      // Given: DynamoDB get command will return no item
      ddbMock.on(GetCommand).resolves({});

      // When: Getting job status for non-existent job
      const job = await getJobStatus('non-existent-job');

      // Then: Null should be returned
      expect(job).toBeNull();
    });

    it('should throw error when DynamoDB get fails', async () => {
      // Given: DynamoDB get command will fail
      ddbMock.on(GetCommand).rejects(new Error('DynamoDB error'));

      // When/Then: Getting job status should throw error
      await expect(getJobStatus('test-job-id')).rejects.toThrow('Failed to get job status');
    });
  });

  describe('updateJobStatus', () => {
    it('should update job status without error', async () => {
      // Given: DynamoDB update command will succeed
      ddbMock.on(UpdateCommand).resolves({});

      // When: Updating job status
      await updateJobStatus(
        'test-job-id',
        JobStatus.PROCESSING,
        75,
        'analyze'
      );

      // Then: DynamoDB update should be called with correct parameters
      const updateCalls = ddbMock.commandCalls(UpdateCommand);
      expect(updateCalls.length).toBe(1);

      const updateInput = updateCalls[0].args[0].input;
      expect(updateInput.Key).toEqual({
        PK: 'JOB#test-job-id',
        SK: 'METADATA',
      });
      expect(updateInput.ExpressionAttributeValues).toMatchObject({
        ':status': JobStatus.PROCESSING,
        ':progress': 75,
        ':stage': 'analyze',
      });
    });

    it('should update job status with execution ARN', async () => {
      // Given: DynamoDB update command will succeed
      ddbMock.on(UpdateCommand).resolves({});

      // When: Updating job status with execution ARN
      const executionArn = 'arn:aws:states:us-east-1:123456789012:execution:test';
      await updateJobStatus(
        'test-job-id',
        JobStatus.PROCESSING,
        10,
        'download',
        undefined,
        executionArn
      );

      // Then: Execution ARN should be included in update
      const updateCalls = ddbMock.commandCalls(UpdateCommand);
      expect(updateCalls[0].args[0].input.ExpressionAttributeValues).toMatchObject({
        ':executionArn': executionArn,
      });
    });

    it('should update job status with error information', async () => {
      // Given: DynamoDB update command will succeed
      ddbMock.on(UpdateCommand).resolves({});

      // When: Updating job status with error
      const error = {
        stage: 'download',
        message: 'Video not accessible',
        timestamp: Date.now(),
      };
      await updateJobStatus(
        'test-job-id',
        JobStatus.FAILED,
        0,
        'download',
        error
      );

      // Then: Error should be included in update
      const updateCalls = ddbMock.commandCalls(UpdateCommand);
      expect(updateCalls[0].args[0].input.ExpressionAttributeValues).toMatchObject({
        ':error': error,
      });
    });

    it('should throw error when DynamoDB update fails', async () => {
      // Given: DynamoDB update command will fail
      ddbMock.on(UpdateCommand).rejects(new Error('DynamoDB error'));

      // When/Then: Updating job status should throw error
      await expect(
        updateJobStatus('test-job-id', JobStatus.PROCESSING, 50, 'transcribe')
      ).rejects.toThrow('Failed to update job status');
    });
  });

  describe('updateJobResult', () => {
    it('should update job with video metadata', async () => {
      // Given: DynamoDB update command will succeed
      ddbMock.on(UpdateCommand).resolves({});

      // When: Updating job with video metadata
      const metadata = {
        title: 'Test Video',
        duration: 600,
        thumbnail: 'https://example.com/thumb.jpg',
        resolution: '1920x1080',
        format: 'mp4',
      };
      await updateJobResult('test-job-id', { videoMetadata: metadata });

      // Then: Metadata should be included in update
      const updateCalls = ddbMock.commandCalls(UpdateCommand);
      expect(updateCalls[0].args[0].input.ExpressionAttributeValues).toMatchObject({
        ':metadata': metadata,
      });
    });

    it('should update job with S3 paths', async () => {
      // Given: DynamoDB update command will succeed
      ddbMock.on(UpdateCommand).resolves({});

      // When: Updating job with S3 paths
      await updateJobResult('test-job-id', {
        transcriptS3Path: 's3://bucket/transcripts/job-id/transcript.json',
        analysisS3Path: 's3://bucket/analysis/job-id/analysis.json',
        editedVideoS3Path: 's3://bucket/output/job-id/edited.mp4',
      });

      // Then: S3 paths should be included in update
      const updateCalls = ddbMock.commandCalls(UpdateCommand);
      expect(updateCalls[0].args[0].input.ExpressionAttributeValues).toMatchObject({
        ':transcript': 's3://bucket/transcripts/job-id/transcript.json',
        ':analysis': 's3://bucket/analysis/job-id/analysis.json',
        ':edited': 's3://bucket/output/job-id/edited.mp4',
      });
    });

    it('should throw error when DynamoDB update fails', async () => {
      // Given: DynamoDB update command will fail
      ddbMock.on(UpdateCommand).rejects(new Error('DynamoDB error'));

      // When/Then: Updating job result should throw error
      await expect(
        updateJobResult('test-job-id', { transcriptS3Path: 's3://bucket/test' })
      ).rejects.toThrow('Failed to update job result');
    });
  });
});
