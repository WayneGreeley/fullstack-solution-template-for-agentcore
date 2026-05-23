# Use AWS Lambda Node.js 22 base image
FROM public.ecr.aws/lambda/nodejs:22

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci --only=production

# Copy TypeScript configuration
COPY tsconfig.json ./

# Copy source files
COPY types.ts job-manager.ts index.ts ./

# Install TypeScript and build
RUN npm install --save-dev typescript && \
    npm run build && \
    npm uninstall typescript

# Set the CMD to your handler
CMD [ "dist/index.handler" ]
