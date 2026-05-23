import * as cdk from "aws-cdk-lib"
import { Template } from "aws-cdk-lib/assertions"
import { YouTubeVideoEditorStack } from "../lib/youtube-video-editor-stack"

/**
 * Unit tests for YouTube Video Editor Stack
 * 
 * Validates that all required infrastructure components are created:
 * - S3 buckets (raw-videos, transcripts, analysis, output)
 * - DynamoDB table with TTL
 * - API Gateway with REST endpoints
 * - CloudFront distribution
 * - IAM roles for Lambda functions
 */
describe("YouTubeVideoEditorStack", () => {
  let app: cdk.App
  let stack: cdk.Stack
  let template: Template

  beforeEach(() => {
    // Given: A CDK app and parent stack (nested stacks require a parent)
    app = new cdk.App()
    stack = new cdk.Stack(app, "TestStack")

    // When: YouTube Video Editor nested stack is created
    const videoEditorStack = new YouTubeVideoEditorStack(stack, "VideoEditorStack", {
      stackNameBase: "test-stack",
    })

    // Then: Get template from the nested stack
    template = Template.fromStack(videoEditorStack)
  })

  describe("S3 Buckets", () => {
    test("creates raw videos bucket with encryption and lifecycle", () => {
      // Then: Raw videos bucket should exist with proper configuration
      template.hasResourceProperties("AWS::S3::Bucket", {
        BucketEncryption: {
          ServerSideEncryptionConfiguration: [
            {
              ServerSideEncryptionByDefault: {
                SSEAlgorithm: "AES256",
              },
            },
          ],
        },
        PublicAccessBlockConfiguration: {
          BlockPublicAcls: true,
          BlockPublicPolicy: true,
          IgnorePublicAcls: true,
          RestrictPublicBuckets: true,
        },
        LifecycleConfiguration: {
          Rules: [
            {
              ExpirationInDays: 1,
              Id: "DeleteAfter24Hours",
              Status: "Enabled",
            },
          ],
        },
      })
    })

    test("creates transcripts bucket", () => {
      // Then: Transcripts bucket should exist
      template.resourceCountIs("AWS::S3::Bucket", 4) // raw, transcripts, analysis, output
    })

    test("creates output bucket with CORS configuration", () => {
      // Then: Output bucket should have CORS for video delivery
      template.hasResourceProperties("AWS::S3::Bucket", {
        CorsConfiguration: {
          CorsRules: [
            {
              AllowedMethods: ["GET", "HEAD"],
              AllowedOrigins: ["*"],
              AllowedHeaders: ["*"],
              MaxAge: 3000,
            },
          ],
        },
      })
    })
  })

  describe("DynamoDB Table", () => {
    test("creates jobs table with TTL", () => {
      // Then: DynamoDB table should exist with proper configuration
      template.hasResourceProperties("AWS::DynamoDB::Table", {
        KeySchema: [
          {
            AttributeName: "PK",
            KeyType: "HASH",
          },
          {
            AttributeName: "SK",
            KeyType: "RANGE",
          },
        ],
        BillingMode: "PAY_PER_REQUEST",
        TimeToLiveSpecification: {
          AttributeName: "ttl",
          Enabled: true,
        },
      })
    })
  })

  describe("API Gateway", () => {
    test("creates REST API with throttling", () => {
      // Then: API Gateway should exist with rate limiting
      template.hasResourceProperties("AWS::ApiGateway::RestApi", {
        Name: "test-stack-api",
        Description: "YouTube Video Editor API",
      })

      template.hasResourceProperties("AWS::ApiGateway::Stage", {
        StageName: "prod",
      })
    })

    test("creates jobs endpoints", () => {
      // Then: API should have /jobs resource
      template.hasResourceProperties("AWS::ApiGateway::Resource", {
        PathPart: "jobs",
      })
    })

    test("creates job ID endpoint", () => {
      // Then: API should have /jobs/{jobId} resource
      template.hasResourceProperties("AWS::ApiGateway::Resource", {
        PathPart: "{jobId}",
      })
    })

    test("creates result endpoint", () => {
      // Then: API should have /jobs/{jobId}/result resource
      template.hasResourceProperties("AWS::ApiGateway::Resource", {
        PathPart: "result",
      })
    })

    test("configures CORS", () => {
      // Then: API should have CORS configured
      template.hasResourceProperties("AWS::ApiGateway::Method", {
        HttpMethod: "OPTIONS",
      })
    })
  })

  describe("CloudFront Distribution", () => {
    test("creates distribution for video delivery", () => {
      // Then: CloudFront distribution should exist
      template.hasResourceProperties("AWS::CloudFront::Distribution", {
        DistributionConfig: {
          Comment: "test-stack - Video Delivery",
          DefaultCacheBehavior: {
            ViewerProtocolPolicy: "redirect-to-https",
            AllowedMethods: ["GET", "HEAD"],
            CachedMethods: ["GET", "HEAD"],
          },
          PriceClass: "PriceClass_100",
        },
      })
    })

    test("uses Origin Access Control for S3", () => {
      // Then: Distribution should use OAC for secure S3 access
      template.hasResourceProperties("AWS::CloudFront::OriginAccessControl", {
        OriginAccessControlConfig: {
          OriginAccessControlOriginType: "s3",
          SigningBehavior: "always",
          SigningProtocol: "sigv4",
        },
      })
    })
  })

  describe("IAM Roles", () => {
    test("creates orchestrator role with DynamoDB and Lambda permissions", () => {
      // Then: Orchestrator role should exist with proper permissions
      template.hasResourceProperties("AWS::IAM::Role", {
        AssumeRolePolicyDocument: {
          Statement: [
            {
              Action: "sts:AssumeRole",
              Effect: "Allow",
              Principal: {
                Service: "lambda.amazonaws.com",
              },
            },
          ],
        },
        ManagedPolicyArns: [
          {
            "Fn::Join": [
              "",
              [
                "arn:",
                { Ref: "AWS::Partition" },
                ":iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
              ],
            ],
          },
        ],
      })
    })

    test("creates downloader role", () => {
      // Then: Downloader role should exist
      template.hasResourceProperties("AWS::IAM::Role", {
        RoleName: "test-stack-downloader-role",
      })
    })

    test("creates transcriber role with Transcribe permissions", () => {
      // Then: Transcriber role should have Amazon Transcribe permissions
      const policies = template.findResources("AWS::IAM::Policy")
      const transcriberPolicy = Object.values(policies).find((policy: any) => 
        policy.Properties.PolicyDocument.Statement.some((stmt: any) =>
          stmt.Action && 
          Array.isArray(stmt.Action) &&
          stmt.Action.includes("transcribe:StartTranscriptionJob")
        )
      )
      expect(transcriberPolicy).toBeDefined()
    })

    test("creates analyzer role with Bedrock permissions", () => {
      // Then: Analyzer role should have Amazon Bedrock permissions
      const policies = template.findResources("AWS::IAM::Policy")
      const analyzerPolicy = Object.values(policies).find((policy: any) =>
        policy.Properties.PolicyDocument.Statement.some((stmt: any) =>
          stmt.Action &&
          Array.isArray(stmt.Action) &&
          stmt.Action.includes("bedrock:InvokeModel")
        )
      )
      expect(analyzerPolicy).toBeDefined()
    })

    test("creates editor role", () => {
      // Then: Editor role should exist
      template.hasResourceProperties("AWS::IAM::Role", {
        RoleName: "test-stack-editor-role",
      })
    })

    test("creates at least 5 Lambda roles", () => {
      // Then: Should have at least orchestrator, downloader, transcriber, analyzer, editor roles
      const allRoles = template.findResources("AWS::IAM::Role")
      const lambdaRoles = Object.values(allRoles).filter((role: any) => {
        const statements = role.Properties?.AssumeRolePolicyDocument?.Statement || []
        return statements.some((stmt: any) => 
          stmt.Principal?.Service === "lambda.amazonaws.com"
        )
      })
      expect(lambdaRoles.length).toBeGreaterThanOrEqual(5)
    })
  })

  describe("Stack Outputs", () => {
    test("exports bucket names", () => {
      // Then: Stack should export all bucket names
      template.hasOutput("RawVideosBucketName", {})
      template.hasOutput("TranscriptsBucketName", {})
      template.hasOutput("AnalysisBucketName", {})
      template.hasOutput("OutputBucketName", {})
    })

    test("exports API URL", () => {
      // Then: Stack should export API Gateway URL
      template.hasOutput("ApiUrl", {})
    })

    test("exports CloudFront URL", () => {
      // Then: Stack should export CloudFront distribution URL
      template.hasOutput("CloudFrontUrl", {})
    })

    test("exports DynamoDB table name", () => {
      // Then: Stack should export jobs table name
      template.hasOutput("JobsTableName", {})
    })
  })
})
