# use python image
FROM python:3.9

# Allow statements and log messages to immediately appear in Knative logs
ENV PYTHONUNBUFFERED True

# copy local code to container image
ENV APP_HOME /app
WORKDIR $APP_HOME
COPY . ./

# Install production dependencies
RUN pip install -r requirements.txt

# Run the web service on container startup. Here we use the hypercorn
# webserver, with one worker process.
# For environments with multiple CPU cores, increase the number of workers
# to be equal to the cores available
CMD exec hypercorn --bind :$PORT --workers 1 app:app
