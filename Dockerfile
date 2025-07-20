# Use an official Python runtime as a parent image
FROM python:3.10.18-slim

# Set the working directory in the container
WORKDIR /usr/src/app

# Install
# RUN apk add --no-cache bash
RUN apt-get update
RUN apt-get install wget -y
RUN apt-get install g++ -y

# RUN wget https://www.python.org/ftp/python/3.10.13/Python-3.10.13.tgz
# RUN tar -xf Python-3.10.*.tgz

# Download models
COPY download_models.sh .
RUN ./download_models.sh

# Install any needed packages specified in requirements.txt
COPY requirements.txt .
RUN pip install --break-system-packages --no-cache-dir -r requirements.txt

# Clone the repository
COPY . .
