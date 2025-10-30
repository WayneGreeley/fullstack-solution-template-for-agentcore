import { APIGatewayProxyEvent, APIGatewayProxyResult } from 'aws-lambda';
import { DynamoDBClient, PutItemCommand } from '@aws-sdk/client-dynamodb';
import { randomUUID } from 'crypto';

const dynamodb = new DynamoDBClient({});
const TABLE_NAME = process.env.TABLE_NAME!;
const ALLOWED_ORIGINS = process.env.ALLOWED_ORIGINS || '';

// Validation constants
const MAX_SESSION_ID_LENGTH = 100;
const MAX_MESSAGE_LENGTH = 5000;
const SESSION_ID_PATTERN = /^[a-zA-Z0-9-_]+$/;

interface FeedbackRequest {
  sessionId: string;
  message: string;
  feedbackType: 'positive' | 'negative';
}

export const handler = async (
  event: APIGatewayProxyEvent
): Promise<APIGatewayProxyResult> => {
  const corsHeaders = {
    'Access-Control-Allow-Origin': ALLOWED_ORIGINS,
    'Access-Control-Allow-Headers': 'Content-Type,Authorization',
    'Access-Control-Allow-Methods': 'POST,OPTIONS',
  };

  try {
    if (event.httpMethod === 'OPTIONS') {
      return { statusCode: 200, headers: corsHeaders, body: '' };
    }

    if (!event.body) {
      return {
        statusCode: 400,
        headers: corsHeaders,
        body: JSON.stringify({ error: 'Request body is required' }),
      };
    }

    let body: FeedbackRequest;
    try {
      body = JSON.parse(event.body);
    } catch (parseError) {
      return {
        statusCode: 400,
        headers: corsHeaders,
        body: JSON.stringify({ error: 'Invalid JSON format' }),
      };
    }

    // Validate required fields and types
    if (!body.sessionId || !body.message || !body.feedbackType) {
      return {
        statusCode: 400,
        headers: corsHeaders,
        body: JSON.stringify({ error: 'sessionId, message, and feedbackType are required' }),
      };
    }

    // Validate feedbackType value
    if (body.feedbackType !== 'positive' && body.feedbackType !== 'negative') {
      return {
        statusCode: 400,
        headers: corsHeaders,
        body: JSON.stringify({ error: 'feedbackType must be either "positive" or "negative"' }),
      };
    }

    // Validate sessionId format and length
    if (body.sessionId.length > MAX_SESSION_ID_LENGTH || !SESSION_ID_PATTERN.test(body.sessionId)) {
      return {
        statusCode: 400,
        headers: corsHeaders,
        body: JSON.stringify({ 
          error: `sessionId must be alphanumeric with hyphens/underscores and max ${MAX_SESSION_ID_LENGTH} characters` 
        }),
      };
    }

    // Truncate message if it exceeds max length
    if (body.message.length > MAX_MESSAGE_LENGTH) {
      body.message = body.message.substring(0, MAX_MESSAGE_LENGTH);
    }

    const claims = event.requestContext.authorizer?.claims;
    if (!claims) {
      return {
        statusCode: 401,
        headers: corsHeaders,
        body: JSON.stringify({ error: 'Unauthorized' }),
      };
    }

    const username = claims['cognito:username'] || claims.email || 'unknown';
    const feedbackId = randomUUID();
    const timestamp = Date.now();

    await dynamodb.send(
      new PutItemCommand({
        TableName: TABLE_NAME,
        Item: {
          feedbackId: { S: feedbackId },
          sessionId: { S: body.sessionId },
          message: { S: body.message },
          username: { S: username },
          feedbackType: { S: body.feedbackType },
          timestamp: { N: timestamp.toString() },
        },
      })
    );

    return {
      statusCode: 200,
      headers: corsHeaders,
      body: JSON.stringify({ success: true, feedbackId }),
    };
  } catch (error) {
    console.error('Error saving feedback:', { 
      message: error instanceof Error ? error.message : 'Unknown error',
      timestamp: new Date().toISOString()
    });
    return {
      statusCode: 500,
      headers: corsHeaders,
      body: JSON.stringify({ error: 'Internal server error' }),
    };
  }
};
