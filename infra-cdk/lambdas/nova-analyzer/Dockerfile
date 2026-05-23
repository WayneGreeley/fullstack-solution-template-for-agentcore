# Dockerfile for Nova Analyzer Lambda
FROM public.ecr.aws/lambda/python:3.12

# Install system dependencies for video processing
RUN dnf install -y \
    ffmpeg \
    && dnf clean all

# Copy requirements
COPY requirements.txt ${LAMBDA_TASK_ROOT}/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy function code
COPY nova_analyzer.py ${LAMBDA_TASK_ROOT}/

# Set the CMD to your handler
CMD [ "nova_analyzer.lambda_handler" ]
