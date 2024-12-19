# Use a lightweight Python image
FROM python:3.10-slim

# Set the working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the bot's code into the container
COPY . .

# Expose a port (optional, if your bot listens to HTTP requests for webhooks)
# EXPOSE 8080

# Command to run the bot
CMD ["python", "main.py"]
