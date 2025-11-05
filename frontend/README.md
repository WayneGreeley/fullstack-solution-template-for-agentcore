# AgentCore Starter Pack - Frontend

**The perfect starting point for GenAI scientists and architects.** This frontend application is
part of the AgentCore Starter Pack, providing a flexible, production-ready React foundation that
works seamlessly with any backend.

**Why start here?** Skip the frontend setup complexity and jump straight into building your GenAI
applications. This starter pack gives you everything you need to create sophisticated user
interfaces without requiring deep React or TypeScript knowledge - perfect for vibe coding with AI
assistants.

What you get:

- A React/Next.js application that's ready to go
- Built-in Cognito authentication support
- A basic chat interface as your starting foundation
- Rich set of shadcn UI primitives for rapid development
- Vibe coding friendly - no React or TypeScript expertise required

![Chat example](readme-imgs/chat-example2.gif)

## What's Included

This starter pack provides a solid foundation with a basic chat interface that you can extend and customize for your specific GenAI applications. The included components serve as building blocks for creating sophisticated user experiences:

- **Basic Chat Interface** - Your starting point for conversational AI applications
- **Rich UI Component Library** - Complete shadcn component set for rapid development
- **Authentication Ready** - Cognito integration built-in and ready to configure
- **Vibe Coding Optimized** - Perfect structure for AI-assisted development

## Why This Stack?

GenAI scientists and architects need to focus on their core expertise - not wrestling with frontend
setup. This starter pack eliminates the complexity of modern React development while providing a
robust foundation that scales with your needs.

**Perfect for Vibe Coding:** The stack is specifically chosen to work seamlessly with AI coding
assistants. You don't need to be a React or TypeScript expert - just describe what you want to build
and let AI assistants handle the implementation details.

- **React & Next.js** - Modern React framework with excellent AI assistant support
- **TypeScript** - Type safety without the learning curve (AI handles the complexity)
- **Tailwind CSS** - Utility-first styling that AI assistants understand perfectly
- **Shadcn Components** - Rich set of pre-built UI primitives (in `src/components/ui`)

The combination makes it extremely easy to vibe code sophisticated interfaces with AI assistants. Whether you're building chat interfaces, data visualization dashboards, or complex forms - the primitives are all here and ready to extend. The only limitation is your creativity!

## Quickstart

### Prerequisites

- Node.js
- npm

### Installation

This frontend is part of the AgentCore Starter Pack. Navigate to the frontend directory and install dependencies:

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install

# Run the development server
npm run dev
```

That's it! Visit [http://localhost:3000](http://localhost:3000) to see your basic chat interface. Start making changes, and your browser will auto reload. It's that simple to get started building your GenAI application.

**NOTE** Authentication is optional during development - the app runs without any auth setup. This
makes local development fast and easy! However, once you deploy it to a public endpoint you'll want
to add authentication with Cognito. Continue reading to learn how to easily do that.

## Building with AI Assistants (Vibe Coding)

This starter pack is optimized for AI-assisted development. Here's how to get the most out of vibe coding:

### Getting Started with AI Assistants

1. **Describe your vision**: Tell your AI assistant what you want to build - "Create a document upload component with drag-and-drop functionality"
2. **Leverage the primitives**: The shadcn components provide rich building blocks that AI assistants understand well
3. **Iterate quickly**: Make changes, see results instantly, and refine with your AI assistant

### Key Directories for AI Development

- `src/components/ui/` - Pre-built shadcn components (buttons, forms, dialogs, etc.)
- `src/components/` - Your custom components go here
- `src/app/` - Next.js app router pages and layouts
- `src/lib/` - Utility functions and configurations

### Example AI Prompts

- "Add a file upload component to the chat interface"
- "Create a sidebar with navigation for different AI tools"
- "Build a data visualization dashboard using the existing design system"
- "Add a settings page with form validation"

The TypeScript and Tailwind setup means AI assistants can generate type-safe, well-styled components without you needing to understand the underlying complexity.

## Deployment

Deploying your frontend is incredibly simple with the AgentCore Starter Pack. The infrastructure and frontend deployment are handled by automated scripts from the root directory.

### Prerequisites

- AWS CLI configured with appropriate permissions
- Node.js and npm installed

### Deploy Everything

From the **root directory** of the AgentCore Starter Pack, run these two commands:

```bash
# Deploy the CDK infrastructure (includes Cognito User Pool)
./scripts/deploy-cdk.sh

# Deploy the frontend application
./scripts/deploy-frontend.sh
```

That's it! The deployment scripts will:

1. **Infrastructure Setup**: Create all necessary AWS resources including Cognito User Pool, S3 buckets, and hosting infrastructure
2. **Cognito Integration**: Automatically configure the frontend with the Cognito User Pool created by the CDK deployment
3. **Frontend Deployment**: Build and deploy your React application with all authentication properly configured

### What Gets Created

The CDK deployment automatically sets up:

- **Cognito User Pool** - Ready for user authentication
- **S3 Bucket** - For hosting your frontend application
- **CloudFront Distribution** - For global content delivery
- **IAM Roles** - With appropriate permissions for your application

The frontend deployment script automatically configures the React app with the correct Cognito settings from the infrastructure deployment.

## Local Development

### Development Mode

For local development, simply run:

```bash
cd frontend
npm run dev
```

The app runs without authentication by default, making local development fast and easy. Your browser will auto-reload when you make changes.

### Testing with Cognito Locally

If you want to test Cognito authentication locally after deployment:

1. The deployment scripts automatically generate a `.env.local` file with the correct Cognito configuration
2. Update the redirect URI in `.env.local` to use localhost:

```
NEXT_PUBLIC_COGNITO_REDIRECT_URI=http://localhost:3000
```

3. Remember to change it back to your deployed URL before redeploying

### Adding Users

After deployment, you can add users to your Cognito User Pool:

1. Navigate to the Cognito User Pool in the AWS Console
2. Add a new user, marking their email as verified
3. The user will receive an email with their temporary password

The Cognito integration is handled automatically by the AgentCore infrastructure - no manual configuration required!
