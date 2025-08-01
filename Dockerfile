# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY ./requirements.txt /app/requirements.txt

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code into the container at /app
COPY . /app

# Make port 3005 available to the world outside this container
EXPOSE 3005

# Run the app. Note that we are running on a random port in the 3000 range, as requested.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3005"]
