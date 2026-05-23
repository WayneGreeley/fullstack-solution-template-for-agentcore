import * as cdk from "aws-cdk-lib"
import * as s3 from "aws-cdk-lib/aws-s3"
import * as dynamodb from "aws-cdk-lib/aws-dynamodb"
import * as apigateway from "aws-cdk-lib/aws-apigateway"
import * as cloudfront from "aws-cdk-lib/aws-cloudfront"
import * as origins from "aws-cdk-lib/aws-cloudfront-origins"
import * as iam from "aws-cdk-lib/aws-iam"
import * as lambda from "aws-cdk-lib/aws-lambda"
import * as path from "path"
import { Construct } from "constructs"

export interface YouTubeVideoEditorStackProps extends cdk.NestedStackProps {
  stackNameBase: string
}

/**
 * YouTube Video Editor Stack
 * 
 * Creates infrastructure for serverless video editing:
 * - S3 buckets for video storage (raw, transcripts, analysis, output)
 * - DynamoDB table for job state tracking with TTL
 * - API Gateway for REST endpoints
 * - CloudFront distribution for video delivery
 * - IAM roles and policies for Lambda functions
 */
export class YouTubeVideoEditorStack extends cdk.NestedStack {
  public readonly rawVideosBucket: s3.Bucket
  public readonly transcriptsBucket: s3.Bucket
  public readonly analysisBucket: s3.Bucket
  public readonly outputBucket: s3.Bucket
  public readonly jobsTable: dynamodb.Table
  public readonly api: apigateway.RestApi
  public readonly distribution: cloudfront.Distribution
  public readonly orchestratorRole: iam.Role
  public readonly downloaderRole: iam.Role
  public readonly transcriberRole: iam.Role
  public readonly analyzerRole: iam.Role
  public readonly editorRole: iam.Role
  public readonly videoDownloaderFunction: lambda.DockerImageFunction
  public readonly transcriberFunction: lambda.DockerImageFunction

  constructor(scope: Construct, id: string, props: YouTubeVideoEditorStackProps) {
    super(scope, id, props)

    const { stackNameBase } = props

    // ========================================
    // S3 Buckets for Video Processing Pipeline
    // ========================================

    // Raw videos bucket - stores downloaded videos and extracted audio
    this.rawVideosBucket = new s3.Bucket(this, "RawVideosBucket", {
      bucketName: `${stackNameBase}-raw-videos-${cdk.Aws.ACCOUNT_ID}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      lifecycleRules: [
        {
          id: "DeleteAfter24Hours",
          expiration: cdk.Duration.days(1),
        },
      ],
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    })

    // Transcripts bucket - stores transcription results
    this.transcriptsBucket = new s3.Bucket(this, "TranscriptsBucket", {
      bucketName: `${stackNameBase}-transcripts-${cdk.Aws.ACCOUNT_ID}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      lifecycleRules: [
        {
          id: "DeleteAfter24Hours",
          expiration: cdk.Duration.days(1),
        },
      ],
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    })

    // Analysis bucket - stores Nova embeddings and analysis results
    this.analysisBucket = new s3.Bucket(this, "AnalysisBucket", {
      bucketName: `${stackNameBase}-analysis-${cdk.Aws.ACCOUNT_ID}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      lifecycleRules: [
        {
          id: "DeleteAfter24Hours",
          expiration: cdk.Duration.days(1),
        },
      ],
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    })

    // Output bucket - stores edited videos
    this.outputBucket = new s3.Bucket(this, "OutputBucket", {
      bucketName: `${stackNameBase}-output-${cdk.Aws.ACCOUNT_ID}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      cors: [
        {
          allowedMethods: [s3.HttpMethods.GET, s3.HttpMethods.HEAD],
          allowedOrigins: ["*"], // Will be restricted to CloudFront in production
          allowedHeaders: ["*"],
          maxAge: 3000,
        },
      ],
      lifecycleRules: [
        {
          id: "DeleteAfter24Hours",
          expiration: cdk.Duration.days(1),
        },
      ],
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    })

    // ========================================
    // DynamoDB Table for Job State
    // ========================================

    this.jobsTable = new dynamodb.Table(this, "JobsTable", {
      tableName: `${stackNameBase}-jobs`,
      partitionKey: {
        name: "PK",
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: "SK",
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: "ttl",
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    })

    // ========================================
    // IAM Roles for Lambda Functions
    // ========================================

    // Orchestrator Lambda role
    this.orchestratorRole = new iam.Role(this, "OrchestratorRole", {
      roleName: `${stackNameBase}-orchestrator-role`,
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaBasicExecutionRole"),
      ],
    })

    // Grant orchestrator access to DynamoDB
    this.jobsTable.grantReadWriteData(this.orchestratorRole)

    // Grant orchestrator ability to invoke other Lambdas
    this.orchestratorRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["lambda:InvokeFunction"],
        resources: [`arn:aws:lambda:${cdk.Aws.REGION}:${cdk.Aws.ACCOUNT_ID}:function:${stackNameBase}-*`],
      })
    )

    // Video Downloader Lambda role
    this.downloaderRole = new iam.Role(this, "DownloaderRole", {
      roleName: `${stackNameBase}-downloader-role`,
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaBasicExecutionRole"),
      ],
    })

    // Grant downloader access to raw videos bucket
    this.rawVideosBucket.grantWrite(this.downloaderRole)
    this.jobsTable.grantReadWriteData(this.downloaderRole)

    // Transcriber Lambda role
    this.transcriberRole = new iam.Role(this, "TranscriberRole", {
      roleName: `${stackNameBase}-transcriber-role`,
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaBasicExecutionRole"),
      ],
    })

    // Grant transcriber access to buckets and Amazon Transcribe
    this.rawVideosBucket.grantRead(this.transcriberRole)
    this.transcriptsBucket.grantWrite(this.transcriberRole)
    this.jobsTable.grantReadWriteData(this.transcriberRole)

    this.transcriberRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          "transcribe:StartTranscriptionJob",
          "transcribe:GetTranscriptionJob",
          "transcribe:DeleteTranscriptionJob",
        ],
        resources: ["*"],
      })
    )

    // Nova Analyzer Lambda role
    this.analyzerRole = new iam.Role(this, "AnalyzerRole", {
      roleName: `${stackNameBase}-analyzer-role`,
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaBasicExecutionRole"),
      ],
    })

    // Grant analyzer access to buckets and Amazon Bedrock
    this.rawVideosBucket.grantRead(this.analyzerRole)
    this.transcriptsBucket.grantRead(this.analyzerRole)
    this.analysisBucket.grantWrite(this.analyzerRole)
    this.jobsTable.grantReadWriteData(this.analyzerRole)

    this.analyzerRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
        ],
        resources: [
          `arn:aws:bedrock:${cdk.Aws.REGION}::foundation-model/amazon.nova-*`,
        ],
      })
    )

    // Video Editor Lambda role
    this.editorRole = new iam.Role(this, "EditorRole", {
      roleName: `${stackNameBase}-editor-role`,
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaBasicExecutionRole"),
      ],
    })

    // Grant editor access to all buckets
    this.rawVideosBucket.grantRead(this.editorRole)
    this.analysisBucket.grantRead(this.editorRole)
    this.outputBucket.grantWrite(this.editorRole)
    this.jobsTable.grantReadWriteData(this.editorRole)

    // ========================================
    // Lambda Functions
    // ========================================

    // Video Downloader Lambda (Container Image)
    this.videoDownloaderFunction = new lambda.DockerImageFunction(this, "VideoDownloaderFunction", {
      functionName: `${stackNameBase}-video-downloader`,
      code: lambda.DockerImageCode.fromImageAsset(
        path.join(__dirname, "../lambdas/video-downloader")
      ),
      role: this.downloaderRole,
      timeout: cdk.Duration.minutes(10),
      memorySize: 2048,
      environment: {
        RAW_VIDEOS_BUCKET: this.rawVideosBucket.bucketName,
        JOBS_TABLE: this.jobsTable.tableName,
      },
      description: "Downloads YouTube videos and extracts audio",
    })

    // Transcriber Lambda (Container Image)
    this.transcriberFunction = new lambda.DockerImageFunction(this, "TranscriberFunction", {
      functionName: `${stackNameBase}-transcriber`,
      code: lambda.DockerImageCode.fromImageAsset(
        path.join(__dirname, "../lambdas/transcriber")
      ),
      role: this.transcriberRole,
      timeout: cdk.Duration.minutes(10),
      memorySize: 1024,
      environment: {
        RAW_VIDEOS_BUCKET: this.rawVideosBucket.bucketName,
        TRANSCRIPTS_BUCKET: this.transcriptsBucket.bucketName,
        JOBS_TABLE: this.jobsTable.tableName,
      },
      description: "Transcribes audio using Amazon Transcribe with speaker identification",
    })

    // Nova Analyzer Lambda (Container Image)
    const novaAnalyzerFunction = new lambda.DockerImageFunction(this, "NovaAnalyzerFunction", {
      functionName: `${stackNameBase}-nova-analyzer`,
      code: lambda.DockerImageCode.fromImageAsset(
        path.join(__dirname, "../lambdas/nova-analyzer")
      ),
      role: this.analyzerRole,
      timeout: cdk.Duration.minutes(10),
      memorySize: 3072,
      environment: {
        RAW_VIDEOS_BUCKET: this.rawVideosBucket.bucketName,
        TRANSCRIPTS_BUCKET: this.transcriptsBucket.bucketName,
        ANALYSIS_BUCKET: this.analysisBucket.bucketName,
        JOBS_TABLE: this.jobsTable.tableName,
      },
      description: "Analyzes video content using Amazon Nova for multimodal embeddings and fluff detection",
    })

    // ========================================
    // API Gateway
    // ========================================

    this.api = new apigateway.RestApi(this, "VideoEditorApi", {
      restApiName: `${stackNameBase}-api`,
      description: "YouTube Video Editor API",
      deployOptions: {
        stageName: "prod",
        throttlingRateLimit: 10,
        throttlingBurstLimit: 20,
      },
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
        allowHeaders: [
          "Content-Type",
          "X-Amz-Date",
          "Authorization",
          "X-Api-Key",
          "X-Amz-Security-Token",
        ],
      },
    })

    // Jobs resource
    const jobsResource = this.api.root.addResource("jobs")

    // POST /jobs - Submit new job (will be connected to Lambda later)
    jobsResource.addMethod("POST", undefined, {
      methodResponses: [
        {
          statusCode: "200",
          responseModels: {
            "application/json": apigateway.Model.EMPTY_MODEL,
          },
        },
      ],
    })

    // GET /jobs/{jobId} - Get job status
    const jobIdResource = jobsResource.addResource("{jobId}")
    jobIdResource.addMethod("GET", undefined, {
      methodResponses: [
        {
          statusCode: "200",
          responseModels: {
            "application/json": apigateway.Model.EMPTY_MODEL,
          },
        },
      ],
    })

    // GET /jobs/{jobId}/result - Get job result
    const resultResource = jobIdResource.addResource("result")
    resultResource.addMethod("GET", undefined, {
      methodResponses: [
        {
          statusCode: "200",
          responseModels: {
            "application/json": apigateway.Model.EMPTY_MODEL,
          },
        },
      ],
    })

    // ========================================
    // CloudFront Distribution for Video Delivery
    // ========================================

    this.distribution = new cloudfront.Distribution(this, "VideoDistribution", {
      comment: `${stackNameBase} - Video Delivery`,
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(this.outputBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD,
        cachedMethods: cloudfront.CachedMethods.CACHE_GET_HEAD,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
      },
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
    })

    // ========================================
    // CloudFormation Outputs
    // ========================================

    new cdk.CfnOutput(this, "RawVideosBucketName", {
      value: this.rawVideosBucket.bucketName,
      description: "S3 bucket for raw videos",
      exportName: `${stackNameBase}-RawVideosBucket`,
    })

    new cdk.CfnOutput(this, "TranscriptsBucketName", {
      value: this.transcriptsBucket.bucketName,
      description: "S3 bucket for transcripts",
      exportName: `${stackNameBase}-TranscriptsBucket`,
    })

    new cdk.CfnOutput(this, "AnalysisBucketName", {
      value: this.analysisBucket.bucketName,
      description: "S3 bucket for analysis results",
      exportName: `${stackNameBase}-AnalysisBucket`,
    })

    new cdk.CfnOutput(this, "OutputBucketName", {
      value: this.outputBucket.bucketName,
      description: "S3 bucket for edited videos",
      exportName: `${stackNameBase}-OutputBucket`,
    })

    new cdk.CfnOutput(this, "JobsTableName", {
      value: this.jobsTable.tableName,
      description: "DynamoDB table for job state",
      exportName: `${stackNameBase}-JobsTable`,
    })

    new cdk.CfnOutput(this, "ApiUrl", {
      value: this.api.url,
      description: "API Gateway URL",
      exportName: `${stackNameBase}-ApiUrl`,
    })

    new cdk.CfnOutput(this, "CloudFrontUrl", {
      value: `https://${this.distribution.distributionDomainName}`,
      description: "CloudFront distribution URL for video delivery",
      exportName: `${stackNameBase}-CloudFrontUrl`,
    })

    new cdk.CfnOutput(this, "VideoDownloaderFunctionArn", {
      value: this.videoDownloaderFunction.functionArn,
      description: "Video Downloader Lambda function ARN",
      exportName: `${stackNameBase}-VideoDownloaderFunctionArn`,
    })

    new cdk.CfnOutput(this, "TranscriberFunctionArn", {
      value: this.transcriberFunction.functionArn,
      description: "Transcriber Lambda function ARN",
      exportName: `${stackNameBase}-TranscriberFunctionArn`,
    })

    new cdk.CfnOutput(this, "NovaAnalyzerFunctionArn", {
      value: novaAnalyzerFunction.functionArn,
      description: "Nova Analyzer Lambda function ARN",
      exportName: `${stackNameBase}-NovaAnalyzerFunctionArn`,
    })
  }
}
