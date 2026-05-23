# Video Editor Lambda Container Image
# Includes ffmpeg for video processing

FROM public.ecr.aws/lambda/python:3.12

# Install system dependencies
RUN yum update -y && \
    yum install -y \
    wget \
    tar \
    xz && \
    yum clean all

# Install ffmpeg (static build for Lambda)
RUN wget https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz && \
    tar xvf ffmpeg-release-amd64-static.tar.xz && \
    mv ffmpeg-*-amd64-static/ffmpeg /usr/local/bin/ && \
    mv ffmpeg-*-amd64-static/ffprobe /usr/local/bin/ && \
    rm -rf ffmpeg-* && \
    chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe

# Copy requirements and install Python dependencies
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Copy Lambda function code
COPY video_editor.py ${LAMBDA_TASK_ROOT}/

# Set the CMD to your handler
CMD ["video_editor.lambda_handler"]
