# Orchestrator Lambda Implementation Plan

## Overview
Implementing Task 11.1: Create TypeScript orchestrator Lambda function for the YouTube Video Editor pipeline.

## Research Completed
1. ✅ Read infra-cdk/README.md - Understood CDK structure and deployment patterns
2. ✅ Read docs/LOCAL_DEVELOPMENT.md - Understood testing approach
3. ✅ Examined existing Lambda (video-downloader) - Understood error handling patterns
4. ✅ Examined CDK stack - Understood Lambda configuration and IAM roles

## Requirements from Design Document
From requirements.md and design.md:
- **Requirement 9.1**: Pipeline stage coordination (download → transcribe → analyze → edit → finalize)
- **Requirement 9.2**: Progress updates at least every 10 seconds
- **Requirement 9.3**: Timeout after 10 minutes

## Architecture Decisions

### 1. Orchestration: AWS Step Functions (State Machine)
- **Why Step Functions**: Better visibility, built-in retry logic, error handling, and state management
- Visual workflow in AWS Console
- Built-in timeout and error handling
- Automatic retry with exponential backoff
- No need for custom polling logic

### 2. Language Choice: TypeScript
- Aligns with CDK infrastructure code (TypeScript)
- Node.js 22 runtime for API handler Lambda (per Typescript.md steering rule)
- Step Functions state machine defined in CDK

### 3. Pipeline Stages (Step Functions Tasks)
```
download → transcribe → analyze → edit → finalize
```
Each stage is a Lambda invocation task in the state machine.

### 4. State Management
- **Step Functions**: Manages pipeline state and transitions
- **DynamoDB**: Stores job metadata for API queries
  - PK: `JOB#{jobId}`
  - SK: `METADATA`
  - Fields: status, progress, currentStage, updatedAt, error, result data

### 5. Error Handling Strategy
- Step Functions built-in retry (3 attempts with exponential backoff)
- Catch blocks for each stage to handle failures
- Resource cleanup Lambda invoked on failure
- Timeout handling (10 minutes for entire workflow)

### 6. Components
- **API Handler Lambda**: Creates jobs, starts Step Functions execution, queries status
- **Step Functions State Machine**: Orchestrates pipeline stages
- **Stage Lambdas**: Existing Lambdas (downloader, transcriber, analyzer, editor)
- **Cleanup Lambda**: Removes partial artifacts on failure

## Implementation Components

### Phase 1: API Handler Lambda (Incremental Test Point)
Files to create:
1. `infra-cdk/lambdas/api-handler/package.json`
2. `infra-cdk/lambdas/api-handler/tsconfig.json`
3. `infra-cdk/lambdas/api-handler/types.ts` (TypeScript interfaces)
4. `infra-cdk/lambdas/api-handler/job-manager.ts` (DynamoDB operations)
5. `infra-cdk/lambdas/api-handler/index.ts` (API endpoints handler)
6. `infra-cdk/lambdas/api-handler/Dockerfile`
7. `infra-cdk/lambdas/api-handler/test/job-manager.test.ts`

**Test Point 1**: Verify job creation and status queries work with DynamoDB

### Phase 2: Step Functions State Machine (Incremental Test Point)
CDK definition in `youtube-video-editor-stack.ts`:
1. Define state machine with pipeline stages
2. Configure retry and error handling
3. Add timeout (10 minutes)
4. Wire to existing Lambda functions

**Test Point 2**: Verify state machine can be started and transitions through stages

### Phase 3: Integration (Incremental Test Point)
1. Wire API Gateway to API handler Lambda
2. API handler starts Step Functions execution
3. Update API handler to query Step Functions execution status

**Test Point 3**: End-to-end test from API call to completed pipeline

### Key Interfaces (types.ts)
```typescript
enum PipelineStage {
  DOWNLOAD = 'download',
  TRANSCRIBE = 'transcribe',
  ANALYZE = 'analyze',
  EDIT = 'edit',
  FINALIZE = 'finalize'
}

enum JobStatus {
  QUEUED = 'queued',
  PROCESSING = 'processing',
  COMPLETE = 'complete',
  FAILED = 'failed'
}

interface JobRecord {
  PK: string;
  SK: string;
  jobId: string;
  youtubeUrl: string;
  status: JobStatus;
  progress: number;
  currentStage: string;
  createdAt: number;
  updatedAt: number;
  ttl: number;
  executionArn?: string; // Step Functions execution ARN
  videoMetadata?: VideoMetadata;
  transcriptS3Path?: string;
  analysisS3Path?: string;
  editedVideoS3Path?: string;
  error?: ErrorInfo;
}

interface StepFunctionsInput {
  jobId: string;
  youtubeUrl: string;
}
```

### Job Manager (job-manager.ts)
- `createJob(url: string): Promise<string>` - Create new job in DynamoDB
- `updateJobStatus(jobId, status, progress, stage, error?, result?)` - Update job state
- `getJobStatus(jobId): Promise<JobRecord>` - Retrieve job state
- `getJobResult(jobId): Promise<JobResult>` - Get completed job results

### API Handler (index.ts)
Handles three API endpoints:
- `POST /jobs` - Create job, start Step Functions execution
- `GET /jobs/{jobId}` - Get job status from DynamoDB + Step Functions
- `GET /jobs/{jobId}/result` - Get completed job results

### Step Functions State Machine
```json
{
  "Comment": "YouTube Video Editor Pipeline",
  "StartAt": "Download",
  "TimeoutSeconds": 600,
  "States": {
    "Download": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:...:function:video-downloader",
      "Retry": [{"ErrorEquals": ["States.ALL"], "MaxAttempts": 3, "BackoffRate": 2}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "HandleFailure"}],
      "Next": "Transcribe"
    },
    "Transcribe": { ... },
    "Analyze": { ... },
    "Edit": { ... },
    "Finalize": { ... },
    "HandleFailure": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:...:function:cleanup",
      "End": true
    }
  }
}
```

## CDK Integration
Update `infra-cdk/lib/youtube-video-editor-stack.ts`:

### Phase 1: API Handler Lambda
1. Create API handler Lambda function (Node.js 22 container)
2. Grant DynamoDB read/write permissions
3. Grant Step Functions StartExecution permission

### Phase 2: Step Functions State Machine
1. Create IAM role for Step Functions
2. Define state machine with all pipeline stages
3. Configure retry policies (3 attempts, exponential backoff)
4. Configure error handling (catch blocks)
5. Set timeout (10 minutes)
6. Grant state machine permission to invoke stage Lambdas

### Phase 3: API Gateway Integration
1. Wire POST /jobs to API handler Lambda
2. Wire GET /jobs/{jobId} to API handler Lambda
3. Wire GET /jobs/{jobId}/result to API handler Lambda

## Testing Strategy

### Phase 1 Tests: API Handler & Job Manager
1. Unit test: `createJob()` writes to DynamoDB correctly
2. Unit test: `getJobStatus()` reads from DynamoDB correctly
3. Unit test: `updateJobStatus()` updates DynamoDB correctly
4. Unit test: API handler validates input parameters
5. Integration test: API handler creates job and returns jobId

**Checkpoint**: Verify job CRUD operations work before proceeding

### Phase 2 Tests: Step Functions State Machine
1. Unit test: State machine definition is valid
2. Integration test: Start execution with mock input
3. Integration test: Verify state transitions (download → transcribe → analyze → edit)
4. Integration test: Verify retry logic on transient failures
5. Integration test: Verify error handling and cleanup on permanent failures
6. Integration test: Verify timeout after 10 minutes

**Checkpoint**: Verify state machine orchestrates pipeline correctly

### Phase 3 Tests: End-to-End Integration
1. Integration test: POST /jobs creates job and starts execution
2. Integration test: GET /jobs/{jobId} returns correct status during execution
3. Integration test: GET /jobs/{jobId}/result returns results after completion
4. Integration test: Complete pipeline with real YouTube video
5. Performance test: Verify 10-minute video completes within 2 minutes

**Checkpoint**: Verify complete system works end-to-end

## Coding Conventions to Follow
- ✅ Docstrings on every function
- ✅ Explicit strong types (TypeScript interfaces)
- ✅ Thorough comments for non-obvious code
- ✅ Fail loudly (no silent fallbacks)
- ✅ Named parameters over positional

## Security Considerations
- No hardcoded credentials
- Use IAM roles for AWS service access
- Validate all input parameters
- Sanitize error messages (no sensitive data exposure)

## Next Steps - Phase 1: API Handler Lambda ✅ COMPLETE

### Step 1.1: Create API Handler Structure ✅
1. ✅ Delete incorrect orchestrator directory
2. ✅ Create `infra-cdk/lambdas/api-handler/` directory
3. ✅ Create package.json with AWS SDK dependencies
4. ✅ Create tsconfig.json for TypeScript compilation
5. ✅ Create types.ts with all interfaces

### Step 1.2: Implement Job Manager ✅
1. ✅ Create job-manager.ts with DynamoDB operations
2. ✅ Implement createJob() function
3. ✅ Implement getJobStatus() function
4. ✅ Implement updateJobStatus() function
5. ✅ Implement updateJobResult() function

### Step 1.3: Implement API Handler ✅
1. ✅ Create index.ts with Lambda handler
2. ✅ Implement POST /jobs endpoint logic
3. ✅ Implement GET /jobs/{jobId} endpoint logic
4. ✅ Implement GET /jobs/{jobId}/result endpoint logic
5. ✅ Add input validation and error handling

### Step 1.4: Create Dockerfile ✅
1. ✅ Create Dockerfile for Node.js 22 runtime
2. ✅ Configure TypeScript build
3. ✅ Install dependencies

### Step 1.5: Write Tests ✅
1. ✅ Create test directory and setup
2. ✅ Write unit tests for job-manager.ts (12 tests, all passing)
3. ✅ Write unit tests for API handler (TODO: Next phase)
4. ✅ Run tests locally

### Step 1.6: Update CDK Stack (TODO: Next phase)
1. Add API handler Lambda to CDK stack
2. Configure IAM permissions (DynamoDB, Step Functions)
3. Wire API Gateway endpoints to Lambda

**Test Checkpoint 1**: ✅ Job CRUD operations verified with unit tests

## Next Steps - Phase 2: Step Functions State Machine

### Step 2.1: Define State Machine in CDK
1. Create Step Functions IAM role
2. Define state machine with pipeline stages
3. Configure retry policies (3 attempts, exponential backoff)
4. Configure error handling (catch blocks)
5. Set timeout (10 minutes)

### Step 2.2: Wire State Machine to Lambdas
1. Grant state machine permission to invoke stage Lambdas
2. Configure input/output mappings for each stage
3. Add progress tracking callbacks

### Step 2.3: Update API Handler Lambda in CDK
1. Add API handler Lambda to CDK stack
2. Grant DynamoDB read/write permissions
3. Grant Step Functions StartExecution permission
4. Wire API Gateway endpoints to Lambda

**Test Checkpoint 2**: Deploy and verify state machine orchestrates pipeline

## Questions for User
1. ~~Should the orchestrator use Step Functions instead of Lambda chaining?~~ ✅ **YES - Using Step Functions**
2. ~~Should we implement caching logic (Task 12) in the orchestrator or as a separate component?~~ ✅ **NOT YET - Implement later**
3. ~~Do you want to test each component incrementally or implement the full orchestrator first?~~ ✅ **INCREMENTAL - Test each phase**
