# Deployment Scripts

This directory contains scripts for deploying the GenAI AgentCore Starter Pack infrastructure and frontend.

## Main Deployment Workflow

### 1. Deploy Infrastructure + Generate Config

```bash
./scripts/deploy-cdk.sh
```

This deploys the CDK stack and automatically generates `aws-exports.json`.

### 2. Deploy Frontend

```bash
./scripts/deploy-frontend.sh
```

This builds the frontend and deploys it to Amplify, including the configuration file.

## Individual Scripts

### Infrastructure Deployment

- `deploy-cdk.sh` - Deploys CDK stack and runs post-deployment tasks
- `post-deploy.js` - Runs after CDK deployment to generate configuration

### Configuration Generation

- `post-deploy.js` - Generates `aws-exports.json` from stack outputs (consolidated post-deployment script)

### Frontend Deployment

- `deploy-frontend.sh` - Builds and deploys frontend with configuration
- `deploy-frontend-v2.sh` - Alternative deployment script (legacy)

## Standalone Configuration Generation

Generate the `aws-exports.json` file without deploying:

```bash
# Using the consolidated post-deploy script
node scripts/post-deploy.js your-stack-name
```

## Generated Configuration

The script creates `frontend/public/aws-exports.json` with the following structure:

```json
{
  "authority": "https://your-cognito-domain.auth.region.amazoncognito.com",
  "client_id": "your-client-id",
  "redirect_uri": "https://your-amplify-url",
  "post_logout_redirect_uri": "https://your-amplify-url",
  "response_type": "code",
  "scope": "email openid profile",
  "automaticSilentRenew": true
}
```

## Requirements

- AWS CLI configured with appropriate permissions
- Node.js runtime
- CDK stack deployed with the required outputs:
  - `CognitoClientId`
  - `CognitoDomain`
  - `AmplifyUrl`

## Benefits

- **No Custom Resources**: Avoids CDK custom resource deployment issues
- **Local Generation**: Fast and reliable configuration generation
- **Simple Dependencies**: Only requires AWS CLI and Node.js
- **Easy Debugging**: Clear error messages and logging
