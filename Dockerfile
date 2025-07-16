# Use an official Python runtime as a parent image
FROM debian:bookworm-slim

# Set the working directory in the container
WORKDIR /usr/src/app

# Install 
RUN apt-get update && \
    apt-get install -y python3-pip wget && \
    rm -rf /var/lib/apt/lists/*

# Download models
COPY download_models.sh .
RUN bash download_models.sh

# Install any needed packages specified in requirements.txt
COPY requirements.txt .
RUN pip install --break-system-packages --no-cache-dir -r requirements.txt

# Clone the repository
COPY . .
