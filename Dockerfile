# Use an official Python runtime as the base image
FROM python:3.9

# Set the working directory in the container
WORKDIR /app

# Copy the requirements.txt file to the working directory
COPY requirements.txt .

# Install the project dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the project files to the working directory
COPY . .

# Copy the code to prepare enviroment
COPY prepare_environment.py .

# Flask App
ENV FLASK_APP=app.py

# Expose the port on which the API will run
EXPOSE 5000

# Specify the command to run your API script
CMD python prepare_environment.py && flask run --host 0.0.0.0
