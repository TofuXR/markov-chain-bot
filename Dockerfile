# Update the Python version to 3.11.6
FROM python:3.11.6-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make port 8080 available to the world outside this container
EXPOSE 8080

# Define environment variables
ENV BOT_TOKEN=""
ENV LOG_LEVEL="INFO"
ENV MARKOV_ORDER="1"
ENV RANDOM_REPLY_CHANCE="0.01"
ENV INACTIVITY_CHECK_INTERVAL="3600"
ENV INACTIVITY_THRESHOLD="86400"
ENV WORD_FROM_USER_CHANCE="0.6"

# Run the application
CMD ["python", "telegram_markov_bot.py"]