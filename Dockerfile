# Use an official Python runtime as a parent image
FROM python:3.11-slim-bullseye

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt ./

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code into the container
COPY . /app

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Run app.main:app using uvicorn when the container launches
# Use 0.0.0.0 to listen on all network interfaces within the container
# Use --proxy-headers to handle proxy headers if needed in production
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]